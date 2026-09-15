package com.msz.gateway.filter;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.msz.gateway.config.GatewayProperties;
import com.msz.gateway.error.EnvelopeResponses;
import com.msz.gateway.error.GatewayErrorWebExceptionHandler;
import org.junit.jupiter.api.Test;
import org.springframework.core.io.buffer.DataBuffer;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.test.web.reactive.server.WebTestClient;
import org.springframework.web.server.WebHandler;
import reactor.core.publisher.Mono;

import java.nio.charset.StandardCharsets;
import java.util.List;

/**
 * 任务 6.2 验证:InternalPathGuardFilter——内部接口网关不可达(404+3006)、
 * 其余路径放行、按「改写前」原始路径识别、internalPaths 为空/null 不误伤。
 */
class InternalPathGuardFilterTest {

    private final GatewayErrorWebExceptionHandler errors =
            new GatewayErrorWebExceptionHandler(new ObjectMapper());
    private final EnvelopeResponses responses = new EnvelopeResponses(new ObjectMapper());

    private GatewayProperties props(List<String> internalPaths) {
        return new GatewayProperties(
                GatewayProperties.Auth.of(List.of(), ""),
                GatewayProperties.RateLimit.defaults(),
                GatewayProperties.Store.MEMORY,
                internalPaths);
    }

    private WebHandler okHandler() {
        return exchange -> {
            byte[] bytes = "ok".getBytes(StandardCharsets.UTF_8);
            exchange.getResponse().setStatusCode(HttpStatus.OK);
            exchange.getResponse().getHeaders().setContentType(MediaType.TEXT_PLAIN);
            DataBuffer buffer = exchange.getResponse().bufferFactory().wrap(bytes);
            return exchange.getResponse().writeWith(Mono.just(buffer));
        };
    }

    private WebTestClient client(InternalPathGuardFilter filter) {
        return client(filter, null);
    }

    /** preservedPath == null 表示不注入原始路径(直接用请求路径)。 */
    private WebTestClient client(InternalPathGuardFilter filter, String preservedPath) {
        WebHandler app = okHandler();
        WebHandler chained = exchange -> {
            if (preservedPath != null) {
                exchange.getAttributes().put(RequestPaths.ORIGINAL_PATH_ATTR, preservedPath);
            }
            return filter.filter(exchange, app::handle)
                    .onErrorResume(e -> errors.handle(exchange, e));
        };
        return WebTestClient.bindToWebHandler(chained).build();
    }

    @Test
    void blocksConfiguredInternalPrefixWith404And3006() {
        InternalPathGuardFilter filter = new InternalPathGuardFilter(
                props(List.of("/api/v1/acc/internal/", "/api/v1/acc/realname/callback")), responses);

        client(filter).get().uri("/api/v1/acc/internal/account/1")
                .exchange()
                .expectStatus().isNotFound()
                .expectBody().jsonPath("$.code").isEqualTo(3006);

        client(filter).get().uri("/api/v1/acc/realname/callback")
                .exchange()
                .expectStatus().isNotFound();
    }

    @Test
    void blocksByOriginalPathEvenAfterRouteRewrite() {
        InternalPathGuardFilter filter = new InternalPathGuardFilter(
                props(List.of("/api/v1/acc/internal/")), responses);

        // 请求路径已被路由 RewritePath 改写为 /acc/internal/...,原始路径保留为 /api/v1/acc/internal/...
        client(filter, "/api/v1/acc/internal/account/1")
                .get().uri("/acc/internal/account/1")
                .exchange()
                .expectStatus().isNotFound()
                .expectBody().jsonPath("$.code").isEqualTo(3006);
    }

    @Test
    void passesNormalPaths() {
        InternalPathGuardFilter filter = new InternalPathGuardFilter(
                props(List.of("/api/v1/acc/internal/")), responses);

        client(filter).get().uri("/api/v1/acc/me").exchange().expectStatus().isOk();
    }

    @Test
    void toleratesNullInternalPaths() {
        InternalPathGuardFilter filter = new InternalPathGuardFilter(props(null), responses);

        client(filter).get().uri("/api/v1/acc/internal/account/1").exchange().expectStatus().isOk();
    }
}
