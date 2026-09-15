package com.msz.gateway.error;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.mock.http.server.reactive.MockServerHttpRequest;
import org.springframework.mock.web.server.MockServerWebExchange;
import org.springframework.web.server.ResponseStatusException;

import java.util.concurrent.TimeoutException;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 任务 3.3 验证:统一错误处理——网关自产错误全部走 Envelope 五字段结构,
 * 错误码映射 2001/2004/5002/5003,404 映射 3006,未知异常 5000,traceId 取自请求头。
 */
class GatewayErrorWebExceptionHandlerTest {

    private final GatewayErrorWebExceptionHandler handler =
            new GatewayErrorWebExceptionHandler(new ObjectMapper());

    private MockServerWebExchange exchange(String traceId) {
        return MockServerWebExchange.from(MockServerHttpRequest
                .get("/api/v1/acc/me")
                .header("X-Request-Id", traceId));
    }

    private String body(MockServerWebExchange exchange, Throwable ex) {
        handler.handle(exchange, ex).block();
        return exchange.getResponse().getBodyAsString().block();
    }

    @Test
    void mapsAuthExceptionTo401With2001() {
        MockServerWebExchange exchange = exchange("t-auth");
        String body = body(exchange, new AuthException("验签失败"));

        assertThat(exchange.getResponse().getStatusCode()).isEqualTo(HttpStatus.UNAUTHORIZED);
        assertThat(body).contains("\"code\":2001", "\"message\":\"未登录 / Token 失效\"", "\"traceId\":\"t-auth\"");
    }

    @Test
    void mapsRateLimitedExceptionTo429With2004() {
        MockServerWebExchange exchange = exchange("t-rl");
        String body = body(exchange, new RateLimitedException());

        assertThat(exchange.getResponse().getStatusCode()).isEqualTo(HttpStatus.TOO_MANY_REQUESTS);
        assertThat(body).contains("\"code\":2004", "\"message\":\"请求过于频繁\"", "\"traceId\":\"t-rl\"");
    }

    @Test
    void mapsTimeoutTo503With5002() {
        MockServerWebExchange exchange = exchange("t-to");
        String body = body(exchange, new TimeoutException("timeout"));

        assertThat(exchange.getResponse().getStatusCode()).isEqualTo(HttpStatus.SERVICE_UNAVAILABLE);
        assertThat(body).contains("\"code\":5002", "\"message\":\"依赖超时 / 熔断\"");
    }

    @Test
    void mapsGatewayUnavailableTo503With5003() {
        MockServerWebExchange exchange = exchange("t-gw");
        String body = body(exchange, new GatewayUnavailableException("redis down"));

        assertThat(exchange.getResponse().getStatusCode()).isEqualTo(HttpStatus.SERVICE_UNAVAILABLE);
        assertThat(body).contains("\"code\":5003", "\"message\":\"网关暂不可用\"");
    }

    @Test
    void mapsNotFoundTo404With3006() {
        MockServerWebExchange exchange = exchange("t-404");
        String body = body(exchange, new ResponseStatusException(HttpStatus.NOT_FOUND));

        assertThat(exchange.getResponse().getStatusCode()).isEqualTo(HttpStatus.NOT_FOUND);
        assertThat(body).contains("\"code\":3006", "\"message\":\"对象不存在\"");
    }

    @Test
    void mapsUnknownExceptionTo500With5000() {
        MockServerWebExchange exchange = exchange("t-500");
        String body = body(exchange, new IllegalStateException("boom"));

        assertThat(exchange.getResponse().getStatusCode()).isEqualTo(HttpStatus.INTERNAL_SERVER_ERROR);
        assertThat(body).contains("\"code\":5000", "\"message\":\"内部错误\"");
    }
}
