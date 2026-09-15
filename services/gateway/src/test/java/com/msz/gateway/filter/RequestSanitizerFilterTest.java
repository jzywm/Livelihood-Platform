package com.msz.gateway.filter;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.msz.gateway.error.EnvelopeResponses;
import com.msz.gateway.error.GatewayErrorWebExceptionHandler;
import org.junit.jupiter.api.Test;
import org.springframework.core.io.buffer.DataBuffer;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.mock.http.server.reactive.MockServerHttpRequest;
import org.springframework.mock.web.server.MockServerWebExchange;
import org.springframework.test.web.reactive.server.WebTestClient;
import org.springframework.web.server.WebHandler;
import reactor.core.publisher.Mono;
import reactor.test.StepVerifier;

import java.nio.charset.StandardCharsets;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 任务 6.2/审查 C1+C2 验证:前门净化过滤器(order -20)——
 * ① 所有路径(含白名单)无条件剥离客户端伪造的身份头;
 * ② 拒绝路径混淆(./ ../ // %2e)并把规范化路径落盘供下游判断。
 */
class RequestSanitizerFilterTest {

    private final EnvelopeResponses responses = new EnvelopeResponses(new ObjectMapper());
    private final GatewayErrorWebExceptionHandler errors =
            new GatewayErrorWebExceptionHandler(new ObjectMapper());

    /** 下游回显:身份头 + 网关判定用的原始路径。 */
    private WebTestClient client() {
        RequestSanitizerFilter sanitizer = new RequestSanitizerFilter(responses);
        WebHandler app = exchange -> {
            var headers = exchange.getRequest().getHeaders();
            String body = headers.getFirst(JwtAuthFilter.USER_ID_HEADER) + "|"
                    + headers.getFirst(JwtAuthFilter.USER_ROLE_HEADER) + "|"
                    + headers.getFirst(JwtAuthFilter.USER_MFA_HEADER) + "|"
                    + headers.getFirst(JwtAuthFilter.USER_JTI_HEADER) + "|"
                    + RequestPaths.of(exchange);
            byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
            exchange.getResponse().setStatusCode(HttpStatus.OK);
            exchange.getResponse().getHeaders().setContentType(MediaType.TEXT_PLAIN);
            DataBuffer buffer = exchange.getResponse().bufferFactory().wrap(bytes);
            return exchange.getResponse().writeWith(Mono.just(buffer));
        };
        WebHandler chained = exchange -> sanitizer.filter(exchange, app::handle)
                .onErrorResume(e -> errors.handle(exchange, e));
        return WebTestClient.bindToWebHandler(chained).build();
    }

    @Test
    void stripsForgedIdentityHeadersOnEveryPathIncludingWhitelist() {
        client().get().uri("/api/v1/acc/register")
                .header(JwtAuthFilter.USER_ID_HEADER, "victim-1001")
                .header(JwtAuthFilter.USER_ROLE_HEADER, "OPERATOR")
                .header(JwtAuthFilter.USER_MFA_HEADER, "true")
                .header(JwtAuthFilter.USER_JTI_HEADER, "forged")
                .exchange()
                .expectStatus().isOk()
                .expectBody(String.class)
                .value(body -> assertThat(body).isEqualTo("null|null|null|null|/api/v1/acc/register"));
    }

    @Test
    void rejectsPathConfusionAttempts() {
        // 直接对原始请求调用过滤器:WebTestClient/UriComponentsBuilder 会预先归一化路径,测不到线上原始形态
        RequestSanitizerFilter sanitizer = new RequestSanitizerFilter(responses);
        String[] attacks = {
                "/api/v1/acc/./internal/account/1",
                "/api/v1/acc/x/../internal/account/1",
                "/api/v1/acc//internal/account/1",
                "/api/v1/acc/%2e/internal/account/1",
                "/api/v1/acc/%2e%2e/acc/internal/account/1"};
        for (String attack : attacks) {
            MockServerWebExchange exchange = MockServerWebExchange.from(
                    MockServerHttpRequest.method(org.springframework.http.HttpMethod.GET,
                            java.net.URI.create(attack)).build());
            assertThat(exchange.getRequest().getPath().value())
                    .as("测试前置:客户端未归一化路径 [%s]", attack)
                    .isEqualTo(attack);

            StepVerifier.create(sanitizer.filter(exchange, ex -> Mono.empty())).verifyComplete();

            assertThat(exchange.getResponse().getStatusCode())
                    .as("路径混淆必须被拒 [%s]", attack)
                    .isEqualTo(HttpStatus.NOT_FOUND);
            assertThat(exchange.getResponse().getBodyAsString().block())
                    .as("错误码 [%s]", attack)
                    .contains("\"code\":3006");
        }
    }

    @Test
    void normalisesTrailingSlashForDownstreamDecisions() {
        client().get().uri("/api/v1/acc/captcha/")
                .exchange()
                .expectStatus().isOk()
                .expectBody(String.class)
                .value(body -> assertThat(body).endsWith("|/api/v1/acc/captcha"));
    }

    @Test
    void keepsCleanPathUntouched() {
        client().get().uri("/api/v1/acc/me")
                .exchange()
                .expectStatus().isOk()
                .expectBody(String.class)
                .value(body -> assertThat(body).endsWith("|/api/v1/acc/me"));
    }
}
