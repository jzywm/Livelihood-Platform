package com.msz.gateway.ops;

import com.msz.gateway.config.GatewayProperties;
import org.junit.jupiter.api.Test;
import org.springframework.cloud.gateway.handler.predicate.PredicateDefinition;
import org.springframework.cloud.gateway.route.RouteDefinition;
import org.springframework.cloud.gateway.route.RouteDefinitionLocator;
import org.springframework.mock.http.server.reactive.MockServerHttpRequest;
import org.springframework.mock.web.server.MockServerWebExchange;
import org.springframework.test.web.reactive.server.WebTestClient;
import reactor.core.publisher.Flux;
import reactor.test.StepVerifier;

import java.net.URI;
import java.util.List;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 运维接口边界:URI 缺失、谓词缺失/多参数、metadata 缺失。
 */
class GatewayOpsControllerEdgeTest {

    private GatewayProperties props() {
        return new GatewayProperties(
                GatewayProperties.Auth.of(List.of(), ""),
                GatewayProperties.RateLimit.defaults(),
                GatewayProperties.Store.MEMORY,
                List.of());
    }

    private WebTestClient client(RouteDefinition... definitions) {
        RouteDefinitionLocator locator = () -> Flux.fromArray(definitions);
        return WebTestClient.bindToController(
                new GatewayOpsController(props(), Optional.<com.msz.gateway.redis.GatewayRedisOps>empty(),
                        locator, "dev", "local", null)).build();
    }

    @Test
    void routesToleratesMissingUriPredicatesAndMetadata() {
        RouteDefinition definition = new RouteDefinition();
        definition.setId("bare");

        client(definition).get().uri("/gateway/routes")
                .exchange()
                .expectStatus().isOk()
                .expectBody()
                .jsonPath("$.routes[0].id").isEqualTo("bare")
                .jsonPath("$.routes[0].order").isEqualTo(0)
                .jsonPath("$.routes[0].predicates").doesNotExist()
                .jsonPath("$.routes[0].timeout").doesNotExist();
    }

    @Test
    void routesRendersMultiArgumentPredicate() {
        RouteDefinition definition = new RouteDefinition();
        definition.setId("multi");
        definition.setUri(URI.create("http://acc:8080"));
        PredicateDefinition predicate = new PredicateDefinition();
        predicate.setName("Header");
        predicate.setArgs(new java.util.LinkedHashMap<>(java.util.Map.of("name", "X-Tag", "regexp", "v1")));
        definition.setPredicates(List.of(predicate));

        client(definition).get().uri("/gateway/routes")
                .exchange()
                .expectStatus().isOk()
                .expectBody()
                .jsonPath("$.routes[0].predicates[0]").value(value ->
                        org.assertj.core.api.Assertions.assertThat(String.valueOf(value))
                                .contains("Header")
                                .contains("X-Tag"));
    }

    @Test
    void routesReturnsEmptyListWhenNoRouteDefined() {
        client().get().uri("/gateway/routes")
                .exchange()
                .expectStatus().isOk()
                .expectBody().jsonPath("$.routes").isEmpty();
    }

    @Test
    void rejectsCallersOutsideAllowedNetworks() {
        RouteDefinitionLocator locator = () -> Flux.just(route());
        GatewayOpsController controller = new GatewayOpsController(props(), Optional.empty(), locator,
                "dev", "local", java.util.List.of("10.0.0.0/8"));

        // 公网来源 → 404(不暴露运维接口)
        MockServerWebExchange publicCaller = MockServerWebExchange.from(MockServerHttpRequest
                .get("/gateway/health")
                .remoteAddress(new java.net.InetSocketAddress("203.0.113.9", 4321)));
        StepVerifier.create(controller.health(publicCaller))
                .assertNext(response -> assertThat(response.getStatusCode().value()).isEqualTo(404))
                .verifyComplete();

        // 内网来源 → 200
        MockServerWebExchange privateCaller = MockServerWebExchange.from(MockServerHttpRequest
                .get("/gateway/health")
                .remoteAddress(new java.net.InetSocketAddress("10.1.2.3", 4321)));
        StepVerifier.create(controller.health(privateCaller))
                .assertNext(response -> assertThat(response.getStatusCode().value()).isEqualTo(200))
                .verifyComplete();
    }

    @Test
    void routesRejectsCallersOutsideAllowedNetworks() {
        GatewayOpsController controller = new GatewayOpsController(props(), Optional.empty(),
                () -> Flux.just(route()), "dev", "local", java.util.List.of("192.168.0.0/16"));

        MockServerWebExchange publicCaller = MockServerWebExchange.from(MockServerHttpRequest
                .get("/gateway/routes")
                .remoteAddress(new java.net.InetSocketAddress("203.0.113.9", 4321)));
        StepVerifier.create(controller.routes(publicCaller))
                .assertNext(body -> assertThat(body.get("routes")).isEqualTo(java.util.List.of()))
                .verifyComplete();
    }

    private RouteDefinition route() {
        RouteDefinition definition = new RouteDefinition();
        definition.setId("acc");
        definition.setUri(URI.create("http://acc:8080"));
        return definition;
    }
}
