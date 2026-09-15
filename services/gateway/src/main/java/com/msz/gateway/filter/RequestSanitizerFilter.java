package com.msz.gateway.filter;

import com.msz.common.api.ErrorCode;
import com.msz.gateway.error.EnvelopeResponses;
import org.springframework.cloud.gateway.filter.GatewayFilterChain;
import org.springframework.cloud.gateway.filter.GlobalFilter;
import org.springframework.core.Ordered;
import org.springframework.http.HttpStatus;
import org.springframework.http.server.reactive.ServerHttpRequest;
import org.springframework.web.server.ServerWebExchange;
import reactor.core.publisher.Mono;

/**
 * 前门净化过滤器(order -20,链最前端,先于 traceId):网关作为唯一鉴权点,
 * 必须在入口处做两件事(审查 C1/C2):
 *
 * <ol>
 *   <li><b>无条件剥离客户端自带的身份头</b>({@code X-User-Id/Role/Mfa/Jti})——包括白名单路径与
 *       未命中路由的请求。否则客户端可在白名单请求(如 /acc/register)上伪造身份直达服务,
 *       或用受害者的 id 打爆其账号级限流桶;</li>
 *   <li><b>路径规范化</b>:含 {@code /./}、{@code /../}、{@code //}、{@code %2e} 等混淆形态的入口
 *       直接 404(避免绕过内部接口守卫与白名单边界),并把规范化路径落盘供下游判断。</li>
 * </ol>
 */
public final class RequestSanitizerFilter implements GlobalFilter, Ordered {

    public static final int ORDER = -20;

    private final EnvelopeResponses responses;

    public RequestSanitizerFilter(EnvelopeResponses responses) {
        this.responses = responses;
    }

    @Override
    public Mono<Void> filter(ServerWebExchange exchange, GatewayFilterChain chain) {
        String canonicalPath = RequestPaths.canonicalize(exchange.getRequest().getPath().value());
        if (canonicalPath == null) {
            return responses.write(exchange, HttpStatus.NOT_FOUND, ErrorCode.OBJECT_NOT_FOUND);
        }
        exchange.getAttributes().put(RequestPaths.ORIGINAL_PATH_ATTR, canonicalPath);

        ServerHttpRequest sanitized = exchange.getRequest().mutate()
                .headers(headers -> {
                    headers.remove(JwtAuthFilter.USER_ID_HEADER);
                    headers.remove(JwtAuthFilter.USER_ROLE_HEADER);
                    headers.remove(JwtAuthFilter.USER_MFA_HEADER);
                    headers.remove(JwtAuthFilter.USER_JTI_HEADER);
                })
                .build();
        return chain.filter(exchange.mutate().request(sanitized).build());
    }

    @Override
    public int getOrder() {
        return ORDER;
    }
}
