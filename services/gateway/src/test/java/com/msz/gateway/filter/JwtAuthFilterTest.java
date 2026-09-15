package com.msz.gateway.filter;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.msz.gateway.auth.InMemoryRevocationStore;
import com.msz.gateway.auth.JwtVerifier;
import com.msz.gateway.auth.TestJwt;
import com.msz.gateway.error.EnvelopeResponses;
import com.msz.gateway.error.GatewayErrorWebExceptionHandler;
import com.msz.gateway.error.GatewayUnavailableException;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;
import org.springframework.core.io.buffer.DataBuffer;
import org.springframework.http.MediaType;
import org.springframework.test.web.reactive.server.WebTestClient;
import org.springframework.web.server.WebHandler;
import reactor.core.publisher.Mono;

import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.Map;
import java.util.Set;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.when;

/**
 * 任务 4.2~4.4 验证:JwtAuthFilter——白名单跳过/鉴权矩阵/四头透传/
 * 保留 Authorization 头/多值头取首个/吊销命中 401/Redis 故障 fail-closed 503。
 */
class JwtAuthFilterTest {

    private static final String FIXTURE_SECRET = "test-gateway-secret";

    private final JwtVerifier verifier = new JwtVerifier();
    private final GatewayErrorWebExceptionHandler errors =
            new GatewayErrorWebExceptionHandler(new ObjectMapper());
    private final EnvelopeResponses responses = new EnvelopeResponses(new ObjectMapper());

    private WebTestClient client(com.msz.gateway.auth.RevocationStore revocationStore,
                                 Set<String> whitelist) {
        return client(revocationStore, whitelist, true);
    }

    /** withErrorHandler=false 时链上不挂错误处理器:用于验证过滤器自身短路写出(fail-closed)。 */
    private WebTestClient client(com.msz.gateway.auth.RevocationStore revocationStore,
                                 Set<String> whitelist, boolean withErrorHandler) {
        JwtAuthFilter filter = new JwtAuthFilter(verifier, FIXTURE_SECRET, revocationStore, whitelist, responses);
        WebHandler app = exchange -> {
            var headers = exchange.getRequest().getHeaders();
            String body = headers.getFirst(JwtAuthFilter.USER_ID_HEADER) + "|"
                    + headers.getFirst(JwtAuthFilter.USER_ROLE_HEADER) + "|"
                    + headers.getFirst(JwtAuthFilter.USER_MFA_HEADER) + "|"
                    + headers.getFirst(JwtAuthFilter.USER_JTI_HEADER) + "|"
                    + headers.getFirst("Authorization");
            byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
            exchange.getResponse().getHeaders().setContentType(MediaType.TEXT_PLAIN);
            DataBuffer buffer = exchange.getResponse().bufferFactory().wrap(bytes);
            return exchange.getResponse().writeWith(Mono.just(buffer));
        };
        WebHandler chained = exchange -> {
            Mono<Void> filtered = new TraceIdFilter().filter(exchange, ex -> filter.filter(ex, app::handle));
            return withErrorHandler ? filtered.onErrorResume(e -> errors.handle(exchange, e)) : filtered;
        };
        return WebTestClient.bindToWebHandler(chained).build();
    }

    private String token(Map<String, Object> claims) {
        return TestJwt.sign(claims, FIXTURE_SECRET, 300);
    }

    @Test
    void forwardsValidTokenWithFourIdentityHeadersAndKeepsAuthorization() {
        String jwt = token(Map.of("sub", "1001", "role", "CONSUMER", "jti", "j-1", "mfa", true));

        client(new InMemoryRevocationStore(), Set.of())
                .get().uri("/api/v1/acc/me")
                .header("Authorization", "Bearer " + jwt)
                .header("X-Request-Id", "t-ok")
                .exchange()
                .expectStatus().isOk()
                .expectBody(String.class)
                .value(body -> assertThat(body)
                        .isEqualTo("1001|CONSUMER|true|j-1|Bearer " + jwt));
    }

    @Test
    void whitelistPathPassesWithoutToken() {
        client(new InMemoryRevocationStore(), Set.of("/api/v1/acc/captcha"))
                .get().uri("/api/v1/acc/captcha")
                .exchange()
                .expectStatus().isOk()
                .expectBody(String.class)
                .value(body -> assertThat(body).startsWith("null|"));
    }

    @Test
    void rejectsMissingHeaderWith401() {
        client(new InMemoryRevocationStore(), Set.of())
                .get().uri("/api/v1/acc/me")
                .header("X-Request-Id", "t-miss")
                .exchange()
                .expectStatus().isUnauthorized()
                .expectBody()
                .jsonPath("$.code").isEqualTo(2001)
                .jsonPath("$.traceId").isEqualTo("t-miss");
    }

    @Test
    void rejectsNonBearerHeaderWith401() {
        client(new InMemoryRevocationStore(), Set.of())
                .get().uri("/api/v1/acc/me")
                .header("Authorization", "Basic abc")
                .exchange()
                .expectStatus().isUnauthorized()
                .expectBody()
                .jsonPath("$.code").isEqualTo(2001);
    }

    @Test
    void rejectsTamperedAndExpiredTokensWith401() {
        WebTestClient c = client(new InMemoryRevocationStore(), Set.of());
        String tampered = TestJwt.tamper(token(Map.of("sub", "1001")));
        c.get().uri("/api/v1/acc/me").header("Authorization", "Bearer " + tampered)
                .exchange().expectStatus().isUnauthorized()
                .expectBody().jsonPath("$.code").isEqualTo(2001);

        String expired = TestJwt.sign(Map.of("sub", "1001"), FIXTURE_SECRET, -5);
        c.get().uri("/api/v1/acc/me").header("Authorization", "Bearer " + expired)
                .exchange().expectStatus().isUnauthorized()
                .expectBody().jsonPath("$.code").isEqualTo(2001);
    }

    @Test
    void rejectsRevokedJtiWith401() {
        InMemoryRevocationStore store = new InMemoryRevocationStore();
        store.revoke("j-revoked", Duration.ofMinutes(5)).block();
        String jwt = token(Map.of("sub", "1001", "role", "CONSUMER", "jti", "j-revoked", "mfa", false));

        client(store, Set.of())
                .get().uri("/api/v1/acc/me")
                .header("Authorization", "Bearer " + jwt)
                .exchange()
                .expectStatus().isUnauthorized()
                .expectBody().jsonPath("$.code").isEqualTo(2001);
    }

    @Test
    void usesFirstAuthorizationHeaderValue() {
        InMemoryRevocationStore store = new InMemoryRevocationStore();
        String valid = token(Map.of("sub", "1001", "role", "CONSUMER", "jti", "j-1", "mfa", false));

        client(store, Set.of())
                .get().uri("/api/v1/acc/me")
                .header("Authorization", "Basic bad", "Bearer " + valid)
                .exchange()
                .expectStatus().isUnauthorized();
    }

    @Test
    void failsClosedWhenRevocationStoreThrows() {
        var store = Mockito.mock(com.msz.gateway.auth.RevocationStore.class);
        when(store.isRevoked(anyString()))
                .thenReturn(Mono.error(new GatewayUnavailableException("redis down")));
        String jwt = token(Map.of("sub", "1001", "role", "CONSUMER", "jti", "j-1", "mfa", false));

        client(store, Set.of())
                .get().uri("/api/v1/acc/me")
                .header("Authorization", "Bearer " + jwt)
                .header("X-Request-Id", "t-fc")
                .exchange()
                .expectStatus().isEqualTo(503)
                .expectBody()
                .jsonPath("$.code").isEqualTo(5003)
                .jsonPath("$.traceId").isEqualTo("t-fc");
    }

    @Test
    void failsClosedByShortCircuitSoCircuitBreakerCannotConvertItTo5002() {
        var store = Mockito.mock(com.msz.gateway.auth.RevocationStore.class);
        when(store.isRevoked(anyString()))
                .thenReturn(Mono.error(new GatewayUnavailableException("redis down")));
        String jwt = token(Map.of("sub", "1001", "role", "CONSUMER", "jti", "j-1", "mfa", false));

        // 链上不挂错误处理器:过滤器必须自己写出 503+5003,否则异常会被网关级熔断当作下游失败转为 fallback(5002)
        client(store, Set.of(), false)
                .get().uri("/api/v1/acc/me")
                .header("Authorization", "Bearer " + jwt)
                .exchange()
                .expectStatus().isEqualTo(503)
                .expectBody().jsonPath("$.code").isEqualTo(5003);
    }
}
