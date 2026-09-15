package com.msz.gateway.error;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.msz.common.api.ErrorCode;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.mock.http.server.reactive.MockServerHttpRequest;
import org.springframework.mock.web.server.MockServerWebExchange;
import reactor.test.StepVerifier;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * EnvelopeResponses:客户端错误短路写出(status + 平台码 + traceId),响应已提交时报错。
 */
class EnvelopeResponsesTest {

    private final EnvelopeResponses responses = new EnvelopeResponses(new ObjectMapper());

    @Test
    void writesEnvelopeWithRequestTraceId() {
        MockServerWebExchange exchange = MockServerWebExchange.from(
                MockServerHttpRequest.get("/api/v1/acc/me").header("X-Request-Id", "t-1").build());

        StepVerifier.create(responses.write(exchange, HttpStatus.NOT_FOUND, ErrorCode.OBJECT_NOT_FOUND))
                .verifyComplete();

        assertThat(exchange.getResponse().getStatusCode()).isEqualTo(HttpStatus.NOT_FOUND);
        assertThat(exchange.getResponse().getBodyAsString().block())
                .contains("\"code\":3006", "\"traceId\":\"t-1\"");
    }

    @Test
    void generatesTraceIdWhenHeaderMissing() {
        MockServerWebExchange exchange = MockServerWebExchange.from(
                MockServerHttpRequest.get("/api/v1/acc/me").build());

        StepVerifier.create(responses.write(exchange, HttpStatus.UNAUTHORIZED, ErrorCode.UNAUTHORIZED))
                .verifyComplete();

        String body = exchange.getResponse().getBodyAsString().block();
        assertThat(body).contains("\"code\":2001");
        assertThat(EnvelopeResponses.traceId(exchange)).isNotBlank();
    }

    @Test
    void failsWhenResponseAlreadyCommitted() {
        MockServerWebExchange exchange = MockServerWebExchange.from(
                MockServerHttpRequest.get("/api/v1/acc/me").build());
        exchange.getResponse().setComplete().block();

        StepVerifier.create(responses.write(exchange, HttpStatus.NOT_FOUND, ErrorCode.OBJECT_NOT_FOUND))
                .expectError(IllegalStateException.class)
                .verify();
    }
}
