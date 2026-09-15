package com.msz.gateway.filter;

import org.junit.jupiter.api.Test;
import org.springframework.mock.http.server.reactive.MockServerHttpRequest;
import org.springframework.mock.web.server.MockServerWebExchange;
import org.springframework.web.server.ServerWebExchange;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * RequestPaths:统一入口原始路径保留——路由级 RewritePath 会剥离 /api/v1 前缀,
 * 白名单/限流分级/内部路径守卫必须读「改写前」的原始路径。
 */
class RequestPathsTest {

    @Test
    void returnsRequestPathWhenNothingPreserved() {
        MockServerWebExchange exchange = MockServerWebExchange.from(
                MockServerHttpRequest.get("/api/v1/acc/me").build());

        assertThat(RequestPaths.of(exchange)).isEqualTo("/api/v1/acc/me");
    }

    @Test
    void returnsPreservedPathAfterRewrite() {
        MockServerWebExchange exchange = MockServerWebExchange.from(
                MockServerHttpRequest.get("/api/v1/assist/chat").build());
        RequestPaths.preserve(exchange);

        // 模拟路由 RewritePath 后的请求路径
        ServerWebExchange rewritten = exchange.mutate()
                .request(exchange.getRequest().mutate().path("/assist/chat").build())
                .build();

        assertThat(rewritten.getRequest().getPath().value()).isEqualTo("/assist/chat");
        assertThat(RequestPaths.of(rewritten)).isEqualTo("/api/v1/assist/chat");
    }

    @Test
    void preserveIsIdempotent() {
        MockServerWebExchange exchange = MockServerWebExchange.from(
                MockServerHttpRequest.get("/api/v1/acc/me").build());

        RequestPaths.preserve(exchange);
        RequestPaths.preserve(exchange);

        assertThat(RequestPaths.of(exchange)).isEqualTo("/api/v1/acc/me");
    }
}
