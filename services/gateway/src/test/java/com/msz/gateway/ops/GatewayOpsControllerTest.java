package com.msz.gateway.ops;

import com.msz.gateway.config.GatewayProperties;
import com.msz.gateway.redis.GatewayRedisOps;
import org.junit.jupiter.api.Test;
import org.springframework.cloud.gateway.route.RouteDefinition;
import org.springframework.cloud.gateway.route.RouteDefinitionLocator;
import org.springframework.test.web.reactive.server.WebTestClient;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;

import java.net.URI;
import java.util.List;
import java.util.Map;
import java.util.Optional;

import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * 任务 8.1/8.2 验证:运维接口——health(status/redis/version/instanceId,DOWN 时 503)
 * 与 routes(id/order/uri 脱敏/predicates/timeout/weight 摘要)。
 */
class GatewayOpsControllerTest {

    private GatewayProperties props(GatewayProperties.Store store) {
        return new GatewayProperties(
                GatewayProperties.Auth.of(List.of(), ""),
                GatewayProperties.RateLimit.defaults(),
                store,
                List.of());
    }

    private RouteDefinitionLocator locator(RouteDefinition... definitions) {
        return () -> Flux.fromArray(definitions);
    }

    private RouteDefinition accRoute() {
        RouteDefinition definition = new RouteDefinition();
        definition.setId("acc");
        definition.setUri(URI.create("http://user:secret@acc:8080"));
        definition.setOrder(1);
        definition.setPredicates(List.of(
                new org.springframework.cloud.gateway.handler.predicate.PredicateDefinition("Path=/api/v1/acc/**")));
        definition.setMetadata(Map.of("timeout", 1000, "weight", 100));
        return definition;
    }

    private WebTestClient client(GatewayProperties properties, Optional<GatewayRedisOps> redis,
                                 RouteDefinitionLocator locator) {
        GatewayOpsController controller = new GatewayOpsController(
                properties, redis, locator, "0.1.0-SNAPSHOT", "inst-test", null);
        return WebTestClient.bindToController(controller).build();
    }

    @Test
    void healthIsUpInMemoryStore() {
        client(props(GatewayProperties.Store.MEMORY), Optional.empty(), locator())
                .get().uri("/gateway/health")
                .exchange()
                .expectStatus().isOk()
                .expectBody()
                .jsonPath("$.status").isEqualTo("UP")
                .jsonPath("$.redis").isEqualTo("memory")
                .jsonPath("$.version").isEqualTo("0.1.0-SNAPSHOT")
                .jsonPath("$.instanceId").isEqualTo("inst-test");
    }

    @Test
    void healthIsUpWhenRedisResponds() {
        GatewayRedisOps redis = mock(GatewayRedisOps.class);
        when(redis.ping()).thenReturn(Mono.just("PONG"));

        client(props(GatewayProperties.Store.REDIS), Optional.of(redis), locator())
                .get().uri("/gateway/health")
                .exchange()
                .expectStatus().isOk()
                .expectBody()
                .jsonPath("$.status").isEqualTo("UP")
                .jsonPath("$.redis").isEqualTo("up");
    }

    @Test
    void healthIsDownWith503WhenRedisUnreachable() {
        GatewayRedisOps redis = mock(GatewayRedisOps.class);
        when(redis.ping()).thenReturn(Mono.error(new RuntimeException("connection refused")));

        client(props(GatewayProperties.Store.REDIS), Optional.of(redis), locator())
                .get().uri("/gateway/health")
                .exchange()
                .expectStatus().isEqualTo(503)
                .expectBody()
                .jsonPath("$.status").isEqualTo("DOWN")
                .jsonPath("$.redis").isEqualTo("down");
    }

    @Test
    void routesReturnsSanitizedSummary() {
        client(props(GatewayProperties.Store.MEMORY), Optional.empty(), locator(accRoute()))
                .get().uri("/gateway/routes")
                .exchange()
                .expectStatus().isOk()
                .expectBody()
                .jsonPath("$.routes[0].id").isEqualTo("acc")
                .jsonPath("$.routes[0].order").isEqualTo(1)
                .jsonPath("$.routes[0].predicates[0]").isEqualTo("Path=/api/v1/acc/**")
                .jsonPath("$.routes[0].timeout").isEqualTo(1000)
                .jsonPath("$.routes[0].weight").isEqualTo(100)
                // 凭据脱敏:不得出现明文账号口令
                .jsonPath("$.routes[0].uri").value(uri -> {
                    String value = String.valueOf(uri);
                    org.assertj.core.api.Assertions.assertThat(value)
                            .doesNotContain("secret")
                            .doesNotContain("user");
                });
    }

    @Test
    void routesToleratesMissingMetadata() {
        RouteDefinition definition = new RouteDefinition();
        definition.setId("plain");
        definition.setUri(URI.create("http://acc:8080"));

        client(props(GatewayProperties.Store.MEMORY), Optional.empty(), locator(definition))
                .get().uri("/gateway/routes")
                .exchange()
                .expectStatus().isOk()
                .expectBody()
                .jsonPath("$.routes[0].id").isEqualTo("plain")
                .jsonPath("$.routes[0].uri").isEqualTo("http://acc:8080")
                .jsonPath("$.routes[0].timeout").doesNotExist()
                .jsonPath("$.routes[0].weight").doesNotExist();
    }
}
