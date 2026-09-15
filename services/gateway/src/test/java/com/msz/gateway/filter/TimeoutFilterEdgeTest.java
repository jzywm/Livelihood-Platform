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

import java.time.Duration;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * TimeoutFilter 边界分支:metadata 无 timeout 键、timeout 为字符串形态、超时错误码。
 */
class TimeoutFilterEdgeTest {

    private final GatewayErrorWebExceptionHandler errors =
            new GatewayErrorWebExceptionHandler(new ObjectMapper());

    private MockServerWebExchange exchangeWithMetadata(Map<String, Object> metadata) {
        MockServerWebExchange exchange = MockServerWebExchange.from(
                MockServerHttpRequest.get("/api/v1/acc/x").build());
        Route route = Route.async()
                .id("acc")
                .uri("http://localhost:8080")
                .asyncPredicate(ex -> Mono.just(true))
                .metadata(metadata)
                .build();
        exchange.getAttributes().put(ServerWebExchangeUtils.GATEWAY_ROUTE_ATTR, route);
        return exchange;
    }

    private Mono<Void> slowOk(MockServerWebExchange exchange, long delayMillis) {
        return Mono.delay(Duration.ofMillis(delayMillis)).then(Mono.fromRunnable(() -> {
            exchange.getResponse().setStatusCode(HttpStatus.OK);
        }).then(exchange.getResponse().writeWith(Mono.just(
                exchange.getResponse().bufferFactory().wrap("ok".getBytes())))));
    }

    @Test
    void usesDefaultTimeoutWhenMetadataHasNoTimeoutKey() {
        MockServerWebExchange exchange = exchangeWithMetadata(Map.of("weight", 100));

        StepVerifier.create(new TimeoutFilter()
                        .filter(exchange, ex -> slowOk(exchange, 20))
                        .onErrorResume(e -> errors.handle(exchange, e)))
                .verifyComplete();

        assertThat(exchange.getResponse().getStatusCode()).isEqualTo(HttpStatus.OK);
    }

    @Test
    void parsesStringTimeoutFromMetadata() {
        MockServerWebExchange exchange = exchangeWithMetadata(Map.of("timeout", "50"));

        StepVerifier.create(new TimeoutFilter()
                        .filter(exchange, ex -> slowOk(exchange, 200))
                        .onErrorResume(e -> errors.handle(exchange, e)))
                .verifyComplete();

        assertThat(exchange.getResponse().getStatusCode().value()).isEqualTo(503);
        assertThat(exchange.getResponse().getBodyAsString().block()).contains("\"code\":5002");
    }

    @Test
    void appliesDefaultTimeoutWhenNoRouteInExchange() {
        MockServerWebExchange exchange = MockServerWebExchange.from(
                MockServerHttpRequest.get("/api/v1/acc/x").build());

        StepVerifier.create(new TimeoutFilter()
                        .filter(exchange, ex -> slowOk(exchange, 20))
                        .onErrorResume(e -> errors.handle(exchange, e)))
                .verifyComplete();

        assertThat(exchange.getResponse().getStatusCode()).isEqualTo(HttpStatus.OK);
    }

    @Test
    void fallsBackToDefaultWhenTimeoutIsNotANumberOrNotPositive() {
        for (Object illegal : new Object[]{"abc", 0, -5, ""}) {
            MockServerWebExchange exchange = exchangeWithMetadata(Map.of("timeout", illegal));

            StepVerifier.create(new TimeoutFilter()
                            .filter(exchange, ex -> slowOk(exchange, 20))
                            .onErrorResume(e -> errors.handle(exchange, e)))
                    .verifyComplete();

            assertThat(exchange.getResponse().getStatusCode())
                    .as("非法超时值 [%s] 必须回退默认而非 500/立即超时", illegal)
                    .isEqualTo(HttpStatus.OK);
        }
    }

    @Test
    void writesResponseBodyForFastPath() {        MockServerWebExchange exchange = exchangeWithMetadata(Map.of("timeout", 1000));
        exchange.getResponse().getHeaders().setContentType(MediaType.TEXT_PLAIN);

        StepVerifier.create(new TimeoutFilter()
                        .filter(exchange, ex -> slowOk(exchange, 10)))
                .verifyComplete();

        DataBuffer ignored = exchange.getResponse().bufferFactory().wrap(new byte[0]);
        assertThat(ignored).isNotNull();
        assertThat(exchange.getResponse().getBodyAsString().block()).isEqualTo("ok");
    }
}
