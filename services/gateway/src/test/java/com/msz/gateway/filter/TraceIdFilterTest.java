package com.msz.gateway.filter;

import org.junit.jupiter.api.Test;
import org.springframework.core.io.buffer.DataBuffer;
import org.springframework.http.MediaType;
import org.springframework.test.web.reactive.server.WebTestClient;
import org.springframework.web.server.WebHandler;
import reactor.core.publisher.Mono;

import java.nio.charset.StandardCharsets;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 任务 3.2 验证:TraceIdFilter——缺失时 UUID 兜底(与 acc TraceIds 同口径)、
 * 已有时保持,且响应头回写同一 traceId。
 */
class TraceIdFilterTest {

    private WebTestClient client(TraceIdFilter filter) {
        WebHandler handler = exchange -> {
            String traceId = exchange.getRequest().getHeaders().getFirst(TraceIdFilter.TRACE_ID_HEADER);
            byte[] bytes = traceId == null ? new byte[0] : traceId.getBytes(StandardCharsets.UTF_8);
            exchange.getResponse().getHeaders().setContentType(MediaType.TEXT_PLAIN);
            DataBuffer buffer = exchange.getResponse().bufferFactory().wrap(bytes);
            return exchange.getResponse().writeWith(Mono.just(buffer));
        };
        WebHandler chained = exchange -> filter.filter(exchange, handler::handle);
        return WebTestClient.bindToWebHandler(chained).build();
    }

    @Test
    void generatesUuidWhenMissingAndEchoesInResponse() {
        client(new TraceIdFilter())
                .get().uri("/api/v1/acc/me")
                .exchange()
                .expectStatus().isOk()
                .expectHeader().valueMatches(TraceIdFilter.TRACE_ID_HEADER,
                        "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
                .expectBody(String.class)
                .value(v -> assertThat(v).matches("[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"));
    }

    @Test
    void keepsExistingRequestId() {
        client(new TraceIdFilter())
                .get().uri("/api/v1/acc/me")
                .header(TraceIdFilter.TRACE_ID_HEADER, "trace-123")
                .exchange()
                .expectStatus().isOk()
                .expectHeader().valueEquals(TraceIdFilter.TRACE_ID_HEADER, "trace-123")
                .expectBody(String.class).isEqualTo("trace-123");
    }

    @Test
    void replacesMalformedRequestIdToPreventLogInjection() {
        client(new TraceIdFilter())
                .get().uri("/api/v1/acc/me")
                .header(TraceIdFilter.TRACE_ID_HEADER, "bad id with spaces & newline")
                .exchange()
                .expectStatus().isOk()
                .expectHeader().valueMatches(TraceIdFilter.TRACE_ID_HEADER,
                        "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}");
    }

    @Test
    void replacesOverlongRequestId() {
        client(new TraceIdFilter())
                .get().uri("/api/v1/acc/me")
                .header(TraceIdFilter.TRACE_ID_HEADER, "x".repeat(65))
                .exchange()
                .expectStatus().isOk()
                .expectHeader().valueMatches(TraceIdFilter.TRACE_ID_HEADER,
                        "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}");
    }
}
