package com.msz.gateway;

import com.msz.gateway.auth.TestJwt;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.test.web.reactive.server.WebTestClient;

import java.util.Map;

/**
 * REDIS 模式装配与 fail-closed 行为:依赖不可用时——
 * ① 运维 health 报 DOWN + HTTP 503(供 LB 摘除);
 * ② 受保护业务请求快速失败 503+5003(不静默放行、不长时间挂起);
 * ③ 公开路径同样失败(IP 限流同样依赖 Redis)。
 *
 * <p>测试指向一个未监听的端口(6399)以模拟 Redis 故障,并设置短超时保证快速失败。</p>
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT, properties = {
        "gateway.store=redis",
        "gateway.auth.jwt-secret=" + TestSecrets.FIXTURE_SECRET,
        "spring.data.redis.host=127.0.0.1",
        "spring.data.redis.port=6399",
        "spring.data.redis.timeout=300ms",
        "spring.data.redis.connect-timeout=300ms",
        "gateway.rate-limit.ip.capacity=10000"
})
class GatewayRedisModeIntegrationTest {

    @LocalServerPort
    private int port;

    private WebTestClient client() {
        return WebTestClient.bindToServer().baseUrl("http://localhost:" + port).build();
    }

    private String jwt() {
        return TestJwt.sign(Map.of("sub", "u1", "role", "CONSUMER", "jti", "j-1", "mfa", false),
                TestSecrets.FIXTURE_SECRET, 300);
    }

    @Test
    void healthReportsDownWhenRedisUnreachable() {
        client().get().uri("/gateway/health")
                .exchange()
                .expectStatus().isEqualTo(503)
                .expectBody()
                .jsonPath("$.status").isEqualTo("DOWN")
                .jsonPath("$.redis").isEqualTo("down");
    }

    @Test
    void protectedRequestFailsClosedWith5003() {
        client().get().uri("/api/v1/acc/me")
                .header("Authorization", "Bearer " + jwt())
                .exchange()
                .expectStatus().isEqualTo(503)
                .expectBody().jsonPath("$.code").isEqualTo(5003);
    }

    @Test
    void publicPathAlsoFailsClosedBecauseRateLimitNeedsRedis() {
        client().get().uri("/api/v1/acc/captcha")
                .exchange()
                .expectStatus().isEqualTo(503)
                .expectBody().jsonPath("$.code").isEqualTo(5003);
    }
}
