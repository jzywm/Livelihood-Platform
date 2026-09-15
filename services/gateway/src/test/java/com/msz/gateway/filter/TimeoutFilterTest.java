package com.msz.gateway.filter;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.msz.gateway.error.GatewayErrorWebExceptionHandler;
import org.junit.jupiter.api.Test;
import org.springframework.cloud.gateway.route.Route;
import org.springframework.cloud.gateway.support.ServerWebExchangeUtils;
import org.springframework.core.io.buffer.DataBuffer;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.mock.http.server.reactive.MockServerHttpRequest;
import org.springframework.mock.web.server.MockServerWebExchange;
import reactor.core.publisher.Mono;
import reactor.test.StepVerifier;

import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 任务 6.3 验证:TimeoutFilter——路由级超时分级(metadata.timeout),
 * 超时 → 503+5002;未配置超时用默认 1s;快速响应正常放行。
 */
class TimeoutFilterTest {

    private final GatewayErrorWebExceptionHandler errors =
            new GatewayErrorWebExceptionHandler(new ObjectMapper());

    private MockServerWebExchange exchangeWithRouteTimeout(Object timeout) {
        MockServerWebExchange exchange = MockServerWebExchange.from(
                MockServerHttpRequest.get("/api/v1/acc/slow").build());
        Route route = Route.async()
                .id("acc")
                .uri("http://localhost:8080")
                .asyncPredicate(ex -> Mono.just(true))
                .metadata(Map.of("timeout", timeout))
                .build();
        exchange.getAttributes().put(ServerWebExchangeUtils.GATEWAY_ROUTE_ATTR, route);
        return exchange;
    }

    private Mono<Void> slowChain(MockServerWebExchange exchange, long delayMillis) {
        return Mono.delay(Duration.ofMillis(delayMillis)).then(writeOk(exchange));
    }

    private Mono<Void> writeOk(MockServerWebExchange exchange) {
        byte[] bytes = "ok".getBytes(StandardCharsets.UTF_8);
        exchange.getResponse().setStatusCode(HttpStatus.OK);
        exchange.getResponse().getHeaders().setContentType(MediaType.TEXT_PLAIN);
        DataBuffer buffer = exchange.getResponse().bufferFactory().wrap(bytes);
        return exchange.getResponse().writeWith(Mono.just(buffer));
    }

    @Test
    void timesOutWhenDownstreamExceedsRouteTimeout() {
        MockServerWebExchange exchange = exchangeWithRouteTimeout(50);
        TimeoutFilter filter = new TimeoutFilter();

        StepVerifier.create(filter.filter(exchange, ex -> slowChain(exchange, 200))
                        .onErrorResume(e -> errors.handle(exchange, e)))
                .verifyComplete();

        assertThat(exchange.getResponse().getStatusCode().value()).isEqualTo(503);
        assertThat(exchange.getResponse().getBodyAsString().block()).contains("\"code\":5002");
    }

    @Test
    void passesWhenDownstreamIsFast() {
        MockServerWebExchange exchange = exchangeWithRouteTimeout(1000);
        TimeoutFilter filter = new TimeoutFilter();

        StepVerifier.create(filter.filter(exchange, ex -> slowChain(exchange, 20))
                        .onErrorResume(e -> errors.handle(exchange, e)))
                .verifyComplete();

        assertThat(exchange.getResponse().getStatusCode().value()).isEqualTo(200);
    }

    @Test
    void usesDefaultTimeoutWhenRouteHasNoMetadata() {
        MockServerWebExchange exchange = MockServerWebExchange.from(
                MockServerHttpRequest.get("/api/v1/acc/me").build());
        Route route = Route.async()
                .id("acc")
                .uri("http://localhost:8080")
                .asyncPredicate(ex -> Mono.just(true))
                .build();
        exchange.getAttributes().put(ServerWebExchangeUtils.GATEWAY_ROUTE_ATTR, route);
        TimeoutFilter filter = new TimeoutFilter();

        StepVerifier.create(filter.filter(exchange, ex -> slowChain(exchange, 20))
                        .onErrorResume(e -> errors.handle(exchange, e)))
                .verifyComplete();

        assertThat(exchange.getResponse().getStatusCode().value()).isEqualTo(200);
    }
}
