package com.msz.gateway;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.test.web.reactive.server.WebTestClient;

/**
 * 任务 2.2 验证:应用可启动、actuator health 返回 UP(memory 存储模式,无 Redis 依赖)。
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT,
        properties = {"gateway.store=memory"})
class GatewayApplicationTest {

    @LocalServerPort
    private int port;

    @Autowired
    private WebTestClient client;

    @Test
    void contextLoadsAndHealthIsUp() {
        client.get().uri("/actuator/health")
                .exchange()
                .expectStatus().isOk()
                .expectBody()
                .jsonPath("$.status").isEqualTo("UP");
    }
}
