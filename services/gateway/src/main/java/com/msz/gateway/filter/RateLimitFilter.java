package com.msz.gateway.filter;

import com.msz.common.api.ErrorCode;
import com.msz.gateway.config.GatewayProperties;
import com.msz.gateway.error.EnvelopeResponses;
import com.msz.gateway.error.GatewayUnavailableException;
import com.msz.gateway.ratelimit.RateLimiter;
import com.msz.gateway.ratelimit.Tier;
import org.springframework.cloud.gateway.filter.GatewayFilterChain;
import org.springframework.cloud.gateway.filter.GlobalFilter;
import org.springframework.core.Ordered;
import org.springframework.http.HttpStatus;
import org.springframework.http.server.reactive.ServerHttpRequest;
import org.springframework.web.server.ServerWebExchange;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;

import java.util.ArrayList;
import java.util.List;

/**
 * 网关级限流(F3,order 10):IP / 账号 / 接口三级固定窗口桶。
 *
 * <p>分级与容量(初值,TBD-3 定档):IP 200/s;读 1000/s/账号、写 100/s/账号、
 * AI 10/min/账号(路径前缀 /api/v1/assist /api/v1/aicore)、资金 100/s(/api/v1/settle
 * /api/v1/acc/funds);资金链路保护优先级最高(独立桶,不被其他流量挤占)。
 * 无身份头(白名单公开路径)仅做 IP 级;AI 链路只做 IP + 账号级(不做接口级全局桶,
 * 避免 10/min 全局阈值误伤多账号平台流量——AI 强限口径是"按账号")。
 * 超限 429+2004;Redis 故障 fail-closed 503+5003(由 GatewayRedisOps 映射)。</p>
 */
public final class RateLimitFilter implements GlobalFilter, Ordered {

    public static final int ORDER = 10;

    private static final org.slf4j.Logger log = org.slf4j.LoggerFactory.getLogger(RateLimitFilter.class);

    public static final String IP_KEY_PREFIX = "rl:ip:";
    public static final String ACCOUNT_KEY_PREFIX = "rl:acc:";
    public static final String API_KEY_PREFIX = "rl:api:";

    private final RateLimiter limiter;
    private final GatewayProperties properties;
    private final EnvelopeResponses responses;
    private final boolean trustForwardedFor;

    public RateLimitFilter(RateLimiter limiter, GatewayProperties properties, EnvelopeResponses responses) {
        this(limiter, properties, responses, true);
    }

    /**
     * @param trustForwardedFor 是否信任 {@code X-Forwarded-For} 链尾作为客户端 IP。
     *                         仅当入口只有可信代理(Nginx)时置 true;网关可被内网直连的场景应置 false
     *                         (改用 TCP 对端地址,防止伪造 XFF 绕过 IP 限流,审查 I13)。
     */
    public RateLimitFilter(RateLimiter limiter, GatewayProperties properties, EnvelopeResponses responses,
                           boolean trustForwardedFor) {
        this.limiter = limiter;
        this.properties = properties;
        this.responses = responses;
        this.trustForwardedFor = trustForwardedFor;
    }

    @Override
    public Mono<Void> filter(ServerWebExchange exchange, GatewayFilterChain chain) {
        return Mono.defer(() -> {
            ServerHttpRequest request = exchange.getRequest();
            // 分级按「改写前」原始入口路径判断(路由 RewritePath 可能已先执行)
            String path = RequestPaths.of(exchange);
            String method = request.getMethod() == null ? "" : request.getMethod().name();
            String sub = request.getHeaders().getFirst(JwtAuthFilter.USER_ID_HEADER);
            String ip = clientIp(request);

            Tier tier = Tier.of(path, method);
            GatewayProperties.Limit limit = properties.rateLimit().limitFor(tier);

            List<Mono<Boolean>> checks = new ArrayList<>();
            checks.add(limiter.tryAcquire(IP_KEY_PREFIX + ip,
                    properties.rateLimit().ip().capacity(), properties.rateLimit().ip().windowSeconds()));
            if (sub != null) {
                checks.add(limiter.tryAcquire(ACCOUNT_KEY_PREFIX + tier.key() + ":" + sub,
                        limit.capacity(), limit.windowSeconds()));
                if (tier != Tier.AI) {
                    checks.add(limiter.tryAcquire(API_KEY_PREFIX + tier.key() + ":" + method + ":" + svcPath(path),
                            limit.capacity(), limit.windowSeconds()));
                }
            }
            return Flux.concat(checks)
                    .all(Boolean::booleanValue)
                    .flatMap(allAllowed -> {
                        if (allAllowed) {
                            return chain.filter(exchange);
                        }
                        // 超限直接写出 429+2004(短路,不抛异常——避免被网关级熔断计为下游失败)
                        log.warn("网关级限流拒绝 uri={} tier={} sub={} ip={}", path, tier.key(), sub, ip);
                        return responses.write(exchange, HttpStatus.TOO_MANY_REQUESTS, ErrorCode.RATE_LIMITED);
                    })
                    // 限流存储不可用(fail-closed):自己写出 503+5003,不被熔断转成 fallback(5002)
                    .onErrorResume(GatewayUnavailableException.class, e -> {
                        log.error("限流存储不可用,快速失败 503/5003 uri={}", path);
                        return responses.write(exchange, HttpStatus.SERVICE_UNAVAILABLE,
                                ErrorCode.GATEWAY_UNAVAILABLE);
                    });
        });
    }

    /**
     * 客户端 IP:信任代理时取 {@code X-Forwarded-For} <b>最右侧</b>一段。
     *
     * <p>入口 Nginx 以 {@code $proxy_add_x_forwarded_for} 追加真实客户端 IP 到链尾,客户端自带的
     * 伪造条目只会留在左侧;取最右侧(最靠近网关的代理所见地址)才能防止伪造 XFF 绕过 IP 限流。
     * {@code trust-forwarded-for=false} 或缺失 XFF 时回退到 TCP 对端地址(审查 I13 信任边界)。</p>
     */
    private String clientIp(ServerHttpRequest request) {
        if (trustForwardedFor) {
            String xff = request.getHeaders().getFirst("X-Forwarded-For");
            if (xff != null && !xff.isBlank()) {
                String[] hops = xff.split(",");
                for (int i = hops.length - 1; i >= 0; i--) {
                    String hop = hops[i].trim();
                    if (!hop.isEmpty()) {
                        return hop;
                    }
                }
            }
        }
        if (request.getRemoteAddress() != null) {
            return request.getRemoteAddress().getAddress().getHostAddress();
        }
        return "unknown";
    }

    /**
     * 接口级桶 key 的路径部分:剥离 {@code /api/v1/{svc}} 前缀(锚定匹配,服务名允许字母数字下划线连字符),
     * 并把路径变量(纯数字 / UUID / 长十六进制)归一为 {@code {id}}——否则 {@code /acc/orders/1..N}
     * 各自成桶,换 ID 即可绕过接口级限流(审查 I10)。
     */
    private String svcPath(String path) {
        String stripped = path.replaceFirst("^/api/v1/[A-Za-z0-9_-]+", "");
        if (stripped.isEmpty()) {
            return path;
        }
        StringBuilder aggregated = new StringBuilder();
        for (String segment : stripped.split("/")) {
            if (segment.isEmpty()) {
                continue;
            }
            aggregated.append('/').append(isPathVariable(segment) ? "{id}" : segment);
        }
        return aggregated.length() == 0 ? stripped : aggregated.toString();
    }

    private boolean isPathVariable(String segment) {
        return segment.matches("\\d+")
                || segment.matches("[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
                || segment.matches("[0-9a-fA-F]{16,}");
    }

    @Override
    public int getOrder() {
        return ORDER;
    }
}
