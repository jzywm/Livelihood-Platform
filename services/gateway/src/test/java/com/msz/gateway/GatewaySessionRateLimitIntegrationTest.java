package com.msz.gateway;

import com.github.tomakehurst.wiremock.WireMockServer;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.web.reactive.server.WebTestClient;

import static com.github.tomakehurst.wiremock.client.WireMock.aResponse;
import static com.github.tomakehurst.wiremock.client.WireMock.post;
import static com.github.tomakehurst.wiremock.client.WireMock.postRequestedFor;
import static com.github.tomakehurst.wiremock.client.WireMock.urlEqualTo;
import static com.github.tomakehurst.wiremock.core.WireMockConfiguration.options;

/**
 * 任务 5.3 集成验证（spec「Session endpoints remain subject to gateway rate limiting」）：
 * **真实网关过滤器链**下限流容量置小后，登录端点的第二次请求返回 429 + 2004，
 * 且**被限流的请求从未到达下游**（限流短路点在路由转发之前）。
 *
 * <p>与 {@link GatewaySessionEndpointsIntegrationTest} 分开成类：后者把容量放宽到 10000，
 * 以免限流干扰白名单/Cookie 断言；两者属性集不同，各自一个 Spring 上下文，断言互不牵连。</p>
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT,
        properties = {
                "gateway.store=memory",
                "gateway.auth.jwt-secret=" + TestSecrets.FIXTURE_SECRET,
                // IP 档置 1：同一 IP 的第二次请求必被拦（限流桶按客户端 IP 计数、跨用例不重置，
                // 故本类**只保留一个用例**按固定顺序发两次请求，避免用例之间互相消耗额度）
                "gateway.rate-limit.ip.capacity=1",
                "gateway.rate-limit.write.capacity=1",
                "gateway.rate-limit.read.capacity=1"
        })
class GatewaySessionRateLimitIntegrationTest {

    private static final WireMockServer downstream = new WireMockServer(options().dynamicPort());

    static {
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
        downstream.resetRequests();
    }

    @BeforeAll
    static void stubDownstream() {
        downstream.stubFor(post("/acc/auth/login").willReturn(aResponse().withStatus(200)
                .withHeader("Content-Type", "application/json")
                .withBody("{\"code\":0,\"data\":{\"accessToken\":\"fixture\"}}")));
        downstream.stubFor(post("/acc/auth/refresh").willReturn(aResponse().withStatus(200)
                .withHeader("Content-Type", "application/json")
                .withBody("{\"code\":0,\"data\":{\"accessToken\":\"fixture\"}}")));
    }

    @AfterAll
    static void stopDownstream() {
        downstream.stop();
    }

    @Test
    @DisplayName("5.3 会话端点不获限流豁免：容量耗尽后 429 + 2004，且下游不再收到请求")
    void sessionEndpointsAreRateLimitedWith429() {
        // ① 首次登录：放行 → 下游收到
        client.post().uri("/api/v1/acc/auth/login")
                .header("Content-Type", "application/json")
                .bodyValue("{\"mobile\":\"13800138000\",\"captchaToken\":\"ct_1\"}")
                .exchange()
                .expectStatus().isOk();

        // ② 同一 IP 第二次请求：429 + 2004，且**下游不再收到**（限流短路在路由转发之前）
        client.post().uri("/api/v1/acc/auth/refresh")
                .header("Cookie", "refresh_token=fixture-2")
                .exchange()
                .expectStatus().isEqualTo(429)
                .expectBody()
                .jsonPath("$.code").isEqualTo(2004)
                .jsonPath("$.message").isEqualTo("请求过于频繁");

        downstream.verify(1, postRequestedFor(urlEqualTo("/acc/auth/login")));
        downstream.verify(0, postRequestedFor(urlEqualTo("/acc/auth/refresh")));
    }
}
