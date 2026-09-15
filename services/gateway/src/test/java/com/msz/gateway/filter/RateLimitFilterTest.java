package com.msz.gateway.filter;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.msz.gateway.config.GatewayProperties;
import com.msz.gateway.error.EnvelopeResponses;
import com.msz.gateway.error.GatewayErrorWebExceptionHandler;
import com.msz.gateway.error.GatewayUnavailableException;
import com.msz.gateway.ratelimit.InMemoryRateLimiter;
import com.msz.gateway.ratelimit.RateLimiter;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;
import org.springframework.core.io.buffer.DataBuffer;
import org.springframework.http.MediaType;
import org.springframework.test.web.reactive.server.WebTestClient;
import org.springframework.web.server.WebHandler;
import reactor.core.publisher.Mono;

import java.nio.charset.StandardCharsets;
import java.util.List;

import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.when;

/**
 * 任务 5.2/5.3 验证:RateLimitFilter——分级(读/写/AI/资金)与 IP/账号/接口三级桶、
 * 超限 429+2004、无身份时仅 IP 级、Redis 故障 fail-closed 503+5003。
 */
class RateLimitFilterTest {

    private final GatewayErrorWebExceptionHandler errors =
            new GatewayErrorWebExceptionHandler(new ObjectMapper());
    private final EnvelopeResponses responses = new EnvelopeResponses(new ObjectMapper());

    private GatewayProperties props(int ipCapacity, int readCapacity, int writeCapacity,
                                    int aiCapacity, int fundsCapacity) {
        return new GatewayProperties(
                GatewayProperties.Auth.of(List.of(), ""),
                new GatewayProperties.RateLimit(
                        new GatewayProperties.Limit(ipCapacity, 1),
                        new GatewayProperties.Limit(readCapacity, 1),
                        new GatewayProperties.Limit(writeCapacity, 1),
                        new GatewayProperties.Limit(aiCapacity, 60),
                        new GatewayProperties.Limit(fundsCapacity, 1)),
                GatewayProperties.Store.MEMORY,
                List.of());
    }

    private WebHandler okHandler() {
        return exchange -> {
            byte[] bytes = "ok".getBytes(StandardCharsets.UTF_8);
            exchange.getResponse().getHeaders().setContentType(MediaType.TEXT_PLAIN);
            DataBuffer buffer = exchange.getResponse().bufferFactory().wrap(bytes);
            return exchange.getResponse().writeWith(Mono.just(buffer));
        };
    }

    private WebTestClient client(RateLimiter limiter, GatewayProperties props) {
        return client(limiter, props, null);
    }

    /** originalPath != null 时注入「改写前原始路径」,模拟路由 RewritePath 已生效的场景。 */
    private WebTestClient client(RateLimiter limiter, GatewayProperties props, String originalPath) {
        return client(limiter, props, originalPath, true);
    }

    /** withErrorHandler=false 时链上不挂错误处理器:用于验证过滤器自身短路写出(fail-closed)。 */
    private WebTestClient client(RateLimiter limiter, GatewayProperties props, String originalPath,
                                 boolean withErrorHandler) {
        RateLimitFilter filter = new RateLimitFilter(limiter, props, responses);
        WebHandler app = okHandler();
        WebHandler chained = exchange -> {
            if (originalPath != null) {
                exchange.getAttributes().put(RequestPaths.ORIGINAL_PATH_ATTR, originalPath);
            }
            Mono<Void> filtered = filter.filter(exchange, app::handle);
            return withErrorHandler ? filtered.onErrorResume(e -> errors.handle(exchange, e)) : filtered;
        };
        return WebTestClient.bindToWebHandler(chained).build();
    }

    private WebTestClient.RequestHeadersSpec<?> get(WebTestClient c, String uri, String sub, String ip) {
        WebTestClient.RequestHeadersSpec<?> spec = c.get().uri(uri).header("X-Forwarded-For", ip);
        if (sub != null) {
            spec.header(JwtAuthFilter.USER_ID_HEADER, sub);
        }
        return spec;
    }

    @Test
    void readTierLimitsPerAccount() {
        WebTestClient c = client(new InMemoryRateLimiter(), props(1000, 1, 1, 1, 1));

        get(c, "/api/v1/acc/me", "u1", "10.0.0.1").exchange().expectStatus().isOk();
        get(c, "/api/v1/acc/me", "u1", "10.0.0.2").exchange()
                .expectStatus().isEqualTo(429)
                .expectBody().jsonPath("$.code").isEqualTo(2004);
    }

    @Test
    void publicPathLimitsByIpOnly() {
        WebTestClient c = client(new InMemoryRateLimiter(), props(1, 1000, 1000, 1000, 1000));

        get(c, "/api/v1/acc/captcha", null, "10.0.0.9").exchange().expectStatus().isOk();
        get(c, "/api/v1/acc/captcha", null, "10.0.0.9").exchange()
                .expectStatus().isEqualTo(429)
                .expectBody().jsonPath("$.code").isEqualTo(2004);
        // 不同 IP 不受影响
        get(c, "/api/v1/acc/captcha", null, "10.0.0.10").exchange().expectStatus().isOk();
    }

    @Test
    void ipKeyUsesLastForwardedForEntrySoClientsCannotSpoof() {
        // Nginx 以 $proxy_add_x_forwarded_for 追加真实客户端 IP 到链尾;取链尾才能防止客户端伪造绕过限流
        WebTestClient c = client(new InMemoryRateLimiter(), props(1, 1000, 1000, 1000, 1000));

        get(c, "/api/v1/acc/captcha", null, "1.1.1.1, 10.0.0.7").exchange().expectStatus().isOk();
        get(c, "/api/v1/acc/captcha", null, "2.2.2.2, 10.0.0.7").exchange()
                .expectStatus().isEqualTo(429)
                .expectBody().jsonPath("$.code").isEqualTo(2004);
    }

    @Test
    void blankForwardedForFallsBackToRemoteAddress() {
        WebTestClient c = client(new InMemoryRateLimiter(), props(1, 1000, 1000, 1000, 1000));

        get(c, "/api/v1/acc/captcha", null, "  ").exchange().expectStatus().isOk();
        get(c, "/api/v1/acc/captcha", null, "  ").exchange()
                .expectStatus().isEqualTo(429)
                .expectBody().jsonPath("$.code").isEqualTo(2004);
    }

    @Test
    void writeTierAppliesToPost() {
        WebTestClient c = client(new InMemoryRateLimiter(), props(1000, 1000, 1, 1, 1));

        c.post().uri("/api/v1/acc/account/close")
                .header("X-Forwarded-For", "10.0.0.1").header(JwtAuthFilter.USER_ID_HEADER, "u1")
                .exchange().expectStatus().isOk();
        c.post().uri("/api/v1/acc/account/close")
                .header("X-Forwarded-For", "10.0.0.2").header(JwtAuthFilter.USER_ID_HEADER, "u1")
                .exchange().expectStatus().isEqualTo(429)
                .expectBody().jsonPath("$.code").isEqualTo(2004);
    }

    @Test
    void aiTierAppliesToAssistPaths() {
        WebTestClient c = client(new InMemoryRateLimiter(), props(1000, 1000, 1000, 1, 1000));

        get(c, "/api/v1/assist/chat", "u1", "10.0.0.1").exchange().expectStatus().isOk();
        get(c, "/api/v1/assist/chat", "u1", "10.0.0.2").exchange()
                .expectStatus().isEqualTo(429)
                .expectBody().jsonPath("$.code").isEqualTo(2004);
    }

    @Test
    void fundsTierAppliesToFundsPaths() {
        WebTestClient c = client(new InMemoryRateLimiter(), props(1000, 1000, 1000, 1000, 1));

        get(c, "/api/v1/acc/funds/audit", "u1", "10.0.0.1").exchange().expectStatus().isOk();
        get(c, "/api/v1/acc/funds/audit", "u1", "10.0.0.2").exchange()
                .expectStatus().isEqualTo(429)
                .expectBody().jsonPath("$.code").isEqualTo(2004);
    }

    @Test
    void tierUsesOriginalPathWhenRouteRewriteAlreadyApplied() {
        // 路由 RewritePath 已把路径改写为 /assist/chat;原始路径 /api/v1/assist/chat → 必须落 AI 级(容量 1)
        WebTestClient c = client(new InMemoryRateLimiter(), props(1000, 1000, 1000, 1, 1000),
                "/api/v1/assist/chat");

        get(c, "/assist/chat", "u1", "10.0.0.1").exchange().expectStatus().isOk();
        get(c, "/assist/chat", "u1", "10.0.0.2").exchange()
                .expectStatus().isEqualTo(429)
                .expectBody().jsonPath("$.code").isEqualTo(2004);
    }

    @Test
    void failsClosedWhenLimiterThrows() {
        RateLimiter limiter = Mockito.mock(RateLimiter.class);
        when(limiter.tryAcquire(anyString(), anyInt(), anyLong()))
                .thenReturn(Mono.error(new GatewayUnavailableException("redis down")));
        WebTestClient c = client(limiter, props(1000, 1000, 1000, 1000, 1000));

        get(c, "/api/v1/acc/me", "u1", "10.0.0.1")
                .exchange()
                .expectStatus().isEqualTo(503)
                .expectBody().jsonPath("$.code").isEqualTo(5003);
    }

    @Test
    void failsClosedByShortCircuitSoCircuitBreakerCannotConvertItTo5002() {
        RateLimiter limiter = Mockito.mock(RateLimiter.class);
        when(limiter.tryAcquire(anyString(), anyInt(), anyLong()))
                .thenReturn(Mono.error(new GatewayUnavailableException("redis down")));

        // 链上不挂错误处理器:过滤器必须自己写出 503+5003,否则异常会被网关级熔断当作下游失败转为 fallback(5002)
        WebTestClient c = client(limiter, props(1000, 1000, 1000, 1000, 1000), null, false);

        get(c, "/api/v1/acc/me", "u1", "10.0.0.1")
                .exchange()
                .expectStatus().isEqualTo(503)
                .expectBody().jsonPath("$.code").isEqualTo(5003);
    }
}
