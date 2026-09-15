package com.msz.gateway;

import com.github.tomakehurst.wiremock.WireMockServer;
import com.github.tomakehurst.wiremock.http.Fault;
import com.msz.gateway.auth.TestJwt;
import com.msz.gateway.ops.GatewayFallbackController;
import org.junit.jupiter.api.AfterAll;
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
import static com.github.tomakehurst.wiremock.client.WireMock.ok;
import static com.github.tomakehurst.wiremock.core.WireMockConfiguration.options;

/**
 * 任务 7.1 验证:网关级熔断(R4J,default-filters CircuitBreaker)——下游连续失败后熔断打开,
 * 请求快速失败到 fallback(503+5002,带 X-Gateway-Fallback 标记);恢复后半开放行。
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT,
        properties = {
                "gateway.store=memory",
                "gateway.auth.jwt-secret=" + TestSecrets.FIXTURE_SECRET,
                "gateway.rate-limit.ip.capacity=10000",
                "gateway.rate-limit.read.capacity=10000",
                // 半开等待缩短到 300ms,便于测试恢复路径(生产 12s,见 application.yml)
                "resilience4j.circuitbreaker.configs.default.waitDurationInOpenState=300ms"
        })
class GatewayCircuitBreakerIntegrationTest {

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
        downstream.resetAll();
        downstream.stubFor(get("/acc/flaky")
                .willReturn(aResponse().withFault(Fault.CONNECTION_RESET_BY_PEER)));
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
    void opensAfterConsecutiveFailuresThenRecoversHalfOpen() {
        // 1) 连续失败(熔断阈值 minimumNumberOfCalls=4 / failureRate 50%)
        for (int i = 0; i < 4; i++) {
            client.get().uri("/api/v1/acc/flaky")
                    .header("Authorization", "Bearer " + jwt())
                    .exchange()
                    .expectStatus().is5xxServerError();
        }

        // 2) 熔断打开 → 快速失败走 fallback(标记头区分普通错误响应)
        client.get().uri("/api/v1/acc/flaky")
                .header("Authorization", "Bearer " + jwt())
                .exchange()
                .expectStatus().isEqualTo(503)
                .expectHeader().valueEquals(GatewayFallbackController.FALLBACK_HEADER, "true")
                .expectBody().jsonPath("$.code").isEqualTo(5002);

        // 3) 下游恢复 + 半开窗口(300ms)→ 放行并返回 200
        downstream.resetAll();
        downstream.stubFor(get("/acc/flaky").willReturn(ok("recovered")));
        sleepQuietly(400);

        client.get().uri("/api/v1/acc/flaky")
                .header("Authorization", "Bearer " + jwt())
                .exchange()
                .expectStatus().isOk()
                .expectBody(String.class).isEqualTo("recovered");
    }

    private void sleepQuietly(long millis) {
        try {
            Thread.sleep(millis);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new IllegalStateException(e);
        }
    }
}
