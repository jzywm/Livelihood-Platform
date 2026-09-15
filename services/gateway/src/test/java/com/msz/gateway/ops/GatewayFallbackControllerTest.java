package com.msz.gateway.ops;

import com.msz.gateway.filter.TraceIdFilter;
import org.junit.jupiter.api.Test;
import org.springframework.cloud.gateway.support.ServerWebExchangeUtils;
import org.springframework.mock.http.server.reactive.MockServerHttpRequest;
import org.springframework.mock.web.server.MockServerWebExchange;
import reactor.test.StepVerifier;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 任务 7.1 验证(降级侧):熔断 fallback 端点——仅接受网关内部 forward(503+5002,
 * 带 {@code X-Gateway-Fallback} 标记头);外部直接访问返回 404,不能伪造"降级"响应。
 */
class GatewayFallbackControllerTest {

    private final GatewayFallbackController controller = new GatewayFallbackController();

    @Test
    void returns503WithEnvelopeAndFallbackMarkerForInternalForward() {
        MockServerWebExchange exchange = MockServerWebExchange.from(MockServerHttpRequest
                .get("/gateway-fallback")
                .header(TraceIdFilter.TRACE_ID_HEADER, "t-fb"));
        exchange.getAttributes().put(ServerWebExchangeUtils.CIRCUITBREAKER_EXECUTION_EXCEPTION_ATTR,
                new RuntimeException("downstream reset"));

        StepVerifier.create(controller.fallback(exchange))
                .assertNext(response -> {
                    assertThat(response.getStatusCode().value()).isEqualTo(503);
                    assertThat(response.getHeaders().getFirst(GatewayFallbackController.FALLBACK_HEADER))
                            .isEqualTo("true");
                    assertThat(response.getBody().code()).isEqualTo(5002);
                    assertThat(response.getBody().message()).isEqualTo("依赖超时 / 熔断");
                    assertThat(response.getBody().traceId()).isEqualTo("t-fb");
                })
                .verifyComplete();
    }

    @Test
    void rejectsExternalDirectAccessSoClientsCannotFakeDegradation() {
        MockServerWebExchange exchange = MockServerWebExchange.from(
                MockServerHttpRequest.get("/gateway-fallback"));

        StepVerifier.create(controller.fallback(exchange))
                .assertNext(response -> {
                    assertThat(response.getStatusCode().value()).isEqualTo(404);
                    assertThat(response.getBody().code()).isEqualTo(3006);
                    assertThat(response.getHeaders().getFirst(GatewayFallbackController.FALLBACK_HEADER))
                            .isNull();
                })
                .verifyComplete();
    }
}
