package com.msz.gateway.filter;

import com.msz.common.api.ErrorCode;
import com.msz.gateway.auth.JwtVerifier;
import com.msz.gateway.auth.RevocationStore;
import com.msz.gateway.error.AuthException;
import com.msz.gateway.error.EnvelopeResponses;
import com.msz.gateway.error.GatewayUnavailableException;
import org.springframework.cloud.gateway.filter.GatewayFilterChain;
import org.springframework.cloud.gateway.filter.GlobalFilter;
import org.springframework.core.Ordered;
import org.springframework.http.HttpStatus;
import org.springframework.http.server.reactive.ServerHttpRequest;
import org.springframework.web.server.ServerWebExchange;
import reactor.core.publisher.Mono;

import java.util.Map;
import java.util.Set;

/**
 * 统一鉴权链(F2,order 0):白名单跳过 → Bearer JWT 验签 → Redis 吊销检查 →
 * 四头身份透传(X-User-Id/X-User-Role/X-User-Mfa/X-User-Jti,与 ACC AuthContext 四字段对齐),
 * 保留原始 Authorization 头(过渡期兼容);失败统一 401+2001,Redis 故障 fail-closed 503+5003。
 */
public final class JwtAuthFilter implements GlobalFilter, Ordered {

    public static final String USER_ID_HEADER = "X-User-Id";
    public static final String USER_ROLE_HEADER = "X-User-Role";
    public static final String USER_MFA_HEADER = "X-User-Mfa";
    public static final String USER_JTI_HEADER = "X-User-Jti";
    public static final int ORDER = 0;

    private static final org.slf4j.Logger log = org.slf4j.LoggerFactory.getLogger(JwtAuthFilter.class);

    private static final String AUTH_HEADER = "Authorization";
    private static final String BEARER_PREFIX = "Bearer ";

    private final JwtVerifier verifier;
    private final String secret;
    private final RevocationStore revocationStore;
    private final Set<String> whitelistPrefixes;
    private final EnvelopeResponses responses;

    public JwtAuthFilter(JwtVerifier verifier, String secret,
                         RevocationStore revocationStore, Set<String> whitelistPrefixes,
                         EnvelopeResponses responses) {
        this.verifier = verifier;
        this.secret = secret;
        this.revocationStore = revocationStore;
        this.whitelistPrefixes = Set.copyOf(whitelistPrefixes);
        this.responses = responses;
    }

    @Override
    public Mono<Void> filter(ServerWebExchange exchange, GatewayFilterChain chain) {
        // 白名单按「改写前」原始入口路径判断,并做段边界匹配(避免 /registerAny 蹭 /register 白名单)
        String path = RequestPaths.of(exchange);
        if (whitelistPrefixes.stream().anyMatch(prefix -> RequestPaths.matchesPrefix(path, prefix))) {
            return chain.filter(exchange);
        }

        return Mono.defer(() -> {
            String header = exchange.getRequest().getHeaders().getFirst(AUTH_HEADER);
            if (header == null || !header.startsWith(BEARER_PREFIX)) {
                return unauthorized(exchange, "缺少 Bearer Token");
            }
            String token = header.substring(BEARER_PREFIX.length()).trim();

            Map<String, Object> claims;
            try {
                claims = verifier.verify(token, secret);
            } catch (AuthException e) {
                return unauthorized(exchange, "验签失败或已过期");
            }
            String jti = (String) claims.get("jti");
            Mono<Boolean> revoked = jti == null ? Mono.just(false) : revocationStore.isRevoked(jti);

            return revoked.flatMap(isRevoked -> {
                if (isRevoked) {
                    return unauthorized(exchange, "Token 已吊销");
                }
                String sub = (String) claims.get("sub");
                String role = (String) claims.get("role");
                boolean mfa = claims.get("mfa") instanceof Boolean b && b;

                ServerHttpRequest.Builder builder = exchange.getRequest().mutate()
                        // 纵深防御:先剥离客户端可能伪造的身份头,再注入验签后的可信身份
                        // (服务内只信任这些头,网关是唯一鉴权点)
                        .headers(headers -> {
                            headers.remove(USER_ID_HEADER);
                            headers.remove(USER_ROLE_HEADER);
                            headers.remove(USER_MFA_HEADER);
                            headers.remove(USER_JTI_HEADER);
                        });
                if (sub != null) {
                    builder.header(USER_ID_HEADER, sub);
                }
                if (role != null) {
                    builder.header(USER_ROLE_HEADER, role);
                }
                builder.header(USER_MFA_HEADER, String.valueOf(mfa));
                if (jti != null) {
                    builder.header(USER_JTI_HEADER, jti);
                }
                ServerWebExchange mutated = exchange.mutate().request(builder.build()).build();
                return chain.filter(mutated);
            });
        })
        // 吊销存储不可用(fail-closed):自己写出 503+5003,不让异常冒泡被熔断转成 fallback(5002)
        .onErrorResume(GatewayUnavailableException.class, e -> unavailable(exchange));
    }

    /** 鉴权失败:直接写出 401+2001(短路,不抛异常——避免被网关级熔断计为下游失败)。 */
    private Mono<Void> unauthorized(ServerWebExchange exchange, String reason) {
        log.warn("鉴权失败 uri={} reason={}", exchange.getRequest().getPath().value(), reason);
        return responses.write(exchange, HttpStatus.UNAUTHORIZED, ErrorCode.UNAUTHORIZED);
    }

    /** 依赖不可用:直接写出 503+5003(fail-closed,不静默放行)。 */
    private Mono<Void> unavailable(ServerWebExchange exchange) {
        log.error("吊销名单不可用,快速失败 503/5003 uri={}", exchange.getRequest().getPath().value());
        return responses.write(exchange, HttpStatus.SERVICE_UNAVAILABLE, ErrorCode.GATEWAY_UNAVAILABLE);
    }

    @Override
    public int getOrder() {
        return ORDER;
    }
}
