package com.msz.gateway;

import com.github.tomakehurst.wiremock.WireMockServer;
import com.msz.gateway.auth.TestJwt;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.web.reactive.server.WebTestClient;

import java.util.Map;

import static com.github.tomakehurst.wiremock.client.WireMock.aResponse;
import static com.github.tomakehurst.wiremock.client.WireMock.get;
import static com.github.tomakehurst.wiremock.client.WireMock.getRequestedFor;
import static com.github.tomakehurst.wiremock.client.WireMock.ok;
import static com.github.tomakehurst.wiremock.client.WireMock.urlEqualTo;
import static com.github.tomakehurst.wiremock.core.WireMockConfiguration.options;

/**
 * 任务 6.1/6.2/6.3 集成验证:真实 SCG 路由——路径重写 /api/v1/{svc}/** → /{svc}/**、
 * 未知服务前缀 404、callback/internal 不配路由不可达、路由级超时 503+5002。
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT,
        properties = {
                "gateway.store=memory",
                "gateway.auth.jwt-secret=" + TestSecrets.FIXTURE_SECRET,
                "gateway.rate-limit.ip.capacity=10000",
                "gateway.rate-limit.read.capacity=10000",
                "gateway.rate-limit.write.capacity=10000"
        })
class GatewayRoutingIntegrationTest {

    private static final WireMockServer downstream = new WireMockServer(options().dynamicPort());

    static {
        // 必须在 @DynamicPropertySource 与 @BeforeAll 之前启动(WireMock 静态 stub 走 admin 端口)
        downstream.start();
    }

    @DynamicPropertySource
    static void routeProperties(DynamicPropertyRegistry registry) {
        registry.add("GATEWAY_ACC_URI", () -> "http://localhost:" + downstream.port());
    }

    @LocalServerPort
    private int port;

    private WebTestClient client;

    @BeforeEach
    void setUp() {
        client = WebTestClient.bindToServer().baseUrl("http://localhost:" + port).build();
    }

    @BeforeAll
    static void stubDownstream() {
        downstream.stubFor(get("/acc/me").willReturn(ok("acc-ok")));
        downstream.stubFor(get("/acc/slow").willReturn(aResponse().withFixedDelay(2500).withBody("slow")));
        downstream.stubFor(get("/acc/internal/account/1").willReturn(ok("internal-leak")));
        downstream.stubFor(get("/acc/realname/callback").willReturn(ok("callback")));
        downstream.stubFor(get("/acc/captcha").willReturn(ok("captcha-ok")));
    }

    @AfterAll
    static void stopDownstream() {
        downstream.stop();
    }

    private String jwt() {
        return TestJwt.sign(Map.of("sub", "u1", "role", "CONSUMER", "jti", "j-1", "mfa", false),
                TestSecrets.FIXTURE_SECRET, 300);
    }

    @Test
    void rewritesApiV1PrefixAndProxiesToDownstream() {
        client.get().uri("/api/v1/acc/me")
                .header("Authorization", "Bearer " + jwt())
                .exchange()
                .expectStatus().isOk()
                .expectBody(String.class).isEqualTo("acc-ok");
        downstream.verify(getRequestedFor(com.github.tomakehurst.wiremock.client.WireMock.urlEqualTo("/acc/me")));    }

    @Test
    void unknownServicePrefixReturns404() {
        client.get().uri("/api/v1/unknown/anything")
                .header("Authorization", "Bearer " + jwt())
                .exchange()
                .expectStatus().isNotFound()
                .expectBody().jsonPath("$.code").isEqualTo(3006);
    }

    @Test
    void internalEndpointsNotReachableThroughGateway() {
        client.get().uri("/api/v1/acc/internal/account/1")
                .header("Authorization", "Bearer " + jwt())
                .exchange()
                .expectStatus().isNotFound();
        client.get().uri("/api/v1/acc/realname/callback")
                .header("Authorization", "Bearer " + jwt())
                .exchange()
                .expectStatus().isNotFound();
    }

    @Test
    void routeTimeoutReturns503With5002() {
        client.get().uri("/api/v1/acc/slow")
                .header("Authorization", "Bearer " + jwt())
                .exchange()
                .expectStatus().isEqualTo(503)
                .expectBody()
                .jsonPath("$.code").isEqualTo(5002);
    }

    @Test
    void opsEndpointsReachableWithoutToken() {
        client.get().uri("/gateway/health")
                .exchange()
                .expectStatus().isOk()
                .expectBody()
                .jsonPath("$.status").isEqualTo("UP")
                .jsonPath("$.redis").isEqualTo("memory");

        client.get().uri("/gateway/routes")
                .exchange()
                .expectStatus().isOk()
                .expectBody()
                .jsonPath("$.routes[0].id").isEqualTo("acc")
                .jsonPath("$.routes[0].timeout").isEqualTo(1000);
    }

    @Test
    void forgedIdentityHeadersNeverReachDownstream() {
        // 公开路径(白名单)上伪造身份头:端到端验证下游收不到任何 X-User-*
        client.get().uri("/api/v1/acc/captcha")
                .header("X-User-Id", "victim-1001")
                .header("X-User-Role", "OPERATOR")
                .header("X-User-Mfa", "true")
                .header("X-User-Jti", "forged")
                .exchange()
                .expectStatus().isOk()
                .expectBody(String.class).isEqualTo("captcha-ok");

        downstream.verify(getRequestedFor(urlEqualTo("/acc/captcha"))
                .withoutHeader("X-User-Id")
                .withoutHeader("X-User-Role")
                .withoutHeader("X-User-Mfa")
                .withoutHeader("X-User-Jti"));
    }
}
