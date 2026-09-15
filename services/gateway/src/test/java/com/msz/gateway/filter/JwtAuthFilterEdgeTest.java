package com.msz.gateway.filter;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.msz.gateway.auth.InMemoryRevocationStore;
import com.msz.gateway.auth.JwtVerifier;
import com.msz.gateway.auth.TestJwt;
import com.msz.gateway.error.EnvelopeResponses;
import com.msz.gateway.error.GatewayErrorWebExceptionHandler;
import org.junit.jupiter.api.Test;
import org.springframework.core.io.buffer.DataBuffer;
import org.springframework.http.MediaType;
import org.springframework.test.web.reactive.server.WebTestClient;
import org.springframework.web.server.WebHandler;
import reactor.core.publisher.Mono;

import java.nio.charset.StandardCharsets;
import java.util.Map;
import java.util.Set;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * JwtAuthFilter 边界分支:claim 缺失(jti/role/mfa)时的头透传行为。
 */
class JwtAuthFilterEdgeTest {

    private static final String FIXTURE_SECRET = "test-gateway-secret";

    private final GatewayErrorWebExceptionHandler errors =
            new GatewayErrorWebExceptionHandler(new ObjectMapper());
    private final EnvelopeResponses responses = new EnvelopeResponses(new ObjectMapper());

    private WebTestClient client() {
        JwtAuthFilter filter = new JwtAuthFilter(new JwtVerifier(), FIXTURE_SECRET,
                new InMemoryRevocationStore(), Set.of(), responses);
        WebHandler app = exchange -> {
            var headers = exchange.getRequest().getHeaders();
            String body = headers.getFirst(JwtAuthFilter.USER_ID_HEADER) + "|"
                    + headers.getFirst(JwtAuthFilter.USER_ROLE_HEADER) + "|"
                    + headers.getFirst(JwtAuthFilter.USER_MFA_HEADER) + "|"
                    + headers.getFirst(JwtAuthFilter.USER_JTI_HEADER);
            exchange.getResponse().setStatusCode(org.springframework.http.HttpStatus.OK);
            exchange.getResponse().getHeaders().setContentType(MediaType.TEXT_PLAIN);
            DataBuffer buffer = exchange.getResponse().bufferFactory()
                    .wrap(body.getBytes(StandardCharsets.UTF_8));
            return exchange.getResponse().writeWith(Mono.just(buffer));
        };
        WebHandler chained = exchange -> new TraceIdFilter()
                .filter(exchange, ex -> filter.filter(ex, app::handle))
                .onErrorResume(e -> errors.handle(exchange, e));
        return WebTestClient.bindToWebHandler(chained).build();
    }

    @Test
    void tokenWithoutJtiSkipsRevocationLookupAndOmitsJtiHeader() {
        String token = TestJwt.sign(Map.of("sub", "u1", "role", "CONSUMER"), FIXTURE_SECRET, 300);

        client().get().uri("/api/v1/acc/me")
                .header("Authorization", "Bearer " + token)
                .exchange()
                .expectStatus().isOk()
                .expectBody(String.class)
                .value(body -> assertThat(body).isEqualTo("u1|CONSUMER|false|null"));
    }

    @Test
    void missingRoleOmitsRoleHeaderAndMfaDefaultsFalse() {
        String token = TestJwt.sign(Map.of("sub", "u2", "jti", "j-2"), FIXTURE_SECRET, 300);

        client().get().uri("/api/v1/acc/me")
                .header("Authorization", "Bearer " + token)
                .exchange()
                .expectStatus().isOk()
                .expectBody(String.class)
                .value(body -> assertThat(body).isEqualTo("u2|null|false|j-2"));
    }

    @Test
    void stripsClientSuppliedIdentityHeadersAndUsesVerifiedClaimsOnly() {
        String token = TestJwt.sign(Map.of(
                "sub", "u9", "role", "REGULATOR", "jti", "j-9", "mfa", true), FIXTURE_SECRET, 300);

        client().get().uri("/api/v1/acc/me")
                .header("Authorization", "Bearer " + token)
                // 客户端伪造身份头:必须被网关剥离,服务内只见验签后的身份
                .header(JwtAuthFilter.USER_ID_HEADER, "attacker")
                .header(JwtAuthFilter.USER_ROLE_HEADER, "OPERATOR")
                .header(JwtAuthFilter.USER_MFA_HEADER, "true")
                .header(JwtAuthFilter.USER_JTI_HEADER, "forged-jti")
                .exchange()
                .expectStatus().isOk()
                .expectBody(String.class)
                .value(body -> assertThat(body).isEqualTo("u9|REGULATOR|true|j-9"));
    }
}
