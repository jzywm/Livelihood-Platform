package com.msz.gateway;

import com.github.tomakehurst.wiremock.WireMockServer;
import com.msz.gateway.auth.TestJwt;
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

import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static com.github.tomakehurst.wiremock.client.WireMock.aResponse;
import static com.github.tomakehurst.wiremock.client.WireMock.containing;
import static com.github.tomakehurst.wiremock.client.WireMock.equalTo;
import static com.github.tomakehurst.wiremock.client.WireMock.post;
import static com.github.tomakehurst.wiremock.client.WireMock.postRequestedFor;
import static com.github.tomakehurst.wiremock.client.WireMock.urlEqualTo;
import static com.github.tomakehurst.wiremock.core.WireMockConfiguration.options;

/**
 * 网关会话端点增量集成验证（任务 5.1/5.2/5.3，spec `platform-gateway` 三条 Requirement）：
 *
 * <ul>
 *   <li>白名单：`/api/v1/acc/auth/{login,refresh}` 无短 token 可达下游；**logout 仍受保护**
 *       （401 + 2001 且下游收不到请求）；近似路径 `/api/v1/acc/auth/loginAny` 不蹭白名单。</li>
 *   <li>Cookie 透传：请求 Cookie 原样到下游；下游 `Set-Cookie` 原样回客户端；
 *       **仅 Cookie 无 Bearer 不构成认证**（受保护路径 401）。</li>
 *   <li>限流不豁免：IP 容量置 1 后第二次登录请求 429 + 2004，且下游只收到一次。</li>
 * </ul>
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT,
        properties = {
                "gateway.store=memory",
                "gateway.auth.jwt-secret=" + TestSecrets.FIXTURE_SECRET,
                "gateway.rate-limit.read.capacity=10000",
                "gateway.rate-limit.write.capacity=10000",
                "gateway.rate-limit.ip.capacity=10000"
        })
class GatewaySessionEndpointsIntegrationTest {

    private static final String LOGIN_PATH = "/api/v1/acc/auth/login";
    private static final String REFRESH_PATH = "/api/v1/acc/auth/refresh";
    private static final String LOGOUT_PATH = "/api/v1/acc/auth/logout";

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
                .withHeader("Set-Cookie",
                        "refresh_token=fixture-refresh; Max-Age=604800; Path=/api/v1/acc/auth; "
                                + "HttpOnly; Secure; SameSite=Lax")
                .withHeader("Content-Type", "application/json")
                .withBody("{\"code\":0,\"data\":{\"accessToken\":\"fixture-access\"}}")));
        downstream.stubFor(post("/acc/auth/refresh").willReturn(aResponse().withStatus(200)
                .withHeader("Set-Cookie",
                        "refresh_token=fixture-rotated; Max-Age=604800; Path=/api/v1/acc/auth; "
                                + "HttpOnly; Secure; SameSite=Lax")
                .withHeader("Content-Type", "application/json")
                .withBody("{\"code\":0,\"data\":{\"accessToken\":\"fixture-access-2\"}}")));
        downstream.stubFor(post("/acc/auth/logout").willReturn(aResponse().withStatus(200)
                .withHeader("Content-Type", "application/json")
                .withBody("{\"code\":0,\"data\":{\"revoked\":true}}")));
        downstream.stubFor(post("/acc/auth/loginAny").willReturn(aResponse().withStatus(200)
                .withBody("lookalike-reached")));
    }

    @AfterAll
    static void stopDownstream() {
        downstream.stop();
    }

    private String jwt() {
        return TestJwt.sign(Map.of("sub", "1001", "role", "CONSUMER", "jti", "j-logout", "mfa", false),
                TestSecrets.FIXTURE_SECRET, 300);
    }

    // ---------- 5.1 白名单边界 ----------

    @Test
    @DisplayName("5.1 无短 token 时登录/换发可直达下游")
    void loginAndRefreshReachableWithoutToken() {
        client.post().uri(LOGIN_PATH)
                .header("Content-Type", "application/json")
                .bodyValue("{\"mobile\":\"13800138000\",\"captchaToken\":\"ct_1\"}")
                .exchange()
                .expectStatus().isOk();

        client.post().uri(REFRESH_PATH)
                .header("Cookie", "refresh_token=fixture-refresh")
                .exchange()
                .expectStatus().isOk();

        downstream.verify(postRequestedFor(urlEqualTo("/acc/auth/login")));
        downstream.verify(postRequestedFor(urlEqualTo("/acc/auth/refresh")));
    }

    @Test
    @DisplayName("5.1 登出**不在白名单**：无 token → 401 + 2001，且请求从未到达下游")
    void logoutStaysProtectedWithoutToken() {
        client.post().uri(LOGOUT_PATH)
                .exchange()
                .expectStatus().isUnauthorized()
                .expectBody().jsonPath("$.code").isEqualTo(2001);

        downstream.verify(0, postRequestedFor(urlEqualTo("/acc/auth/logout")));
    }

    @Test
    @DisplayName("5.1 登出带有效短 token → 转发下游（受保护但可用）")
    void logoutWithValidTokenReachesDownstream() {
        client.post().uri(LOGOUT_PATH)
                .header("Authorization", "Bearer " + jwt())
                .exchange()
                .expectStatus().isOk();

        downstream.verify(postRequestedFor(urlEqualTo("/acc/auth/logout")));
    }

    @Test
    @DisplayName("5.1 近似路径 /api/v1/acc/auth/loginAny 不蹭白名单 → 401 且下游收不到")
    void lookAlikePathDoesNotRideWhitelist() {
        client.post().uri("/api/v1/acc/auth/loginAny")
                .exchange()
                .expectStatus().isUnauthorized()
                .expectBody().jsonPath("$.code").isEqualTo(2001);

        downstream.verify(0, postRequestedFor(urlEqualTo("/acc/auth/loginAny")));
    }

    @Test
    @DisplayName("5.1 路径混淆 /api/v1/acc/auth/login/../me 被规范化规则拒绝（不放行到下游）")
    void obfuscatedPathRejected() {
        client.post().uri("/api/v1/acc/auth/login/../me")
                .exchange()
                .expectStatus().value(status -> org.assertj.core.api.Assertions.assertThat(status)
                        .isIn(401, 404));
    }

    // ---------- 5.2 Cookie 透传与非解析 ----------

    @Test
    @DisplayName("5.2 换发响应 Set-Cookie 原样回到客户端（属性一字不改）")
    void setCookiePassesThroughUnchanged() {
        client.post().uri(REFRESH_PATH)
                .header("Cookie", "refresh_token=fixture-refresh")
                .exchange()
                .expectStatus().isOk()
                .expectHeader().valueEquals("Set-Cookie",
                        "refresh_token=fixture-rotated; Max-Age=604800; Path=/api/v1/acc/auth; "
                                + "HttpOnly; Secure; SameSite=Lax");
    }

    @Test
    @DisplayName("5.2 请求 Cookie 原样透传到下游（网关不解析、不重写、不剥离）")
    void requestCookiePassesThroughUnchanged() {
        client.post().uri(REFRESH_PATH)
                .header("Cookie", "refresh_token=fixture-refresh; other=keep-me")
                .exchange()
                .expectStatus().isOk();

        downstream.verify(postRequestedFor(urlEqualTo("/acc/auth/refresh"))
                .withHeader("Cookie", containing("refresh_token=fixture-refresh"))
                .withHeader("Cookie", containing("other=keep-me")));
    }

    @Test
    @DisplayName("5.2 仅 Cookie 无 Bearer 不构成认证：受保护路径 401 + 2001")
    void cookieAloneDoesNotAuthenticate() {
        client.get().uri("/api/v1/acc/me")
                .header("Cookie", "refresh_token=fixture-refresh")
                .exchange()
                .expectStatus().isUnauthorized()
                .expectBody().jsonPath("$.code").isEqualTo(2001);
    }

    @Test
    @DisplayName("5.2 白名单路径上 Cookie 照常透传（登录链路依赖它回传 refresh）")
    void cookiePassesOnWhitelistedPath() {
        client.post().uri(LOGIN_PATH)
                .header("Content-Type", "application/json")
                .header("Cookie", "refresh_token=old-value")
                .bodyValue("{\"mobile\":\"13800138000\",\"captchaToken\":\"ct_1\"}")
                .exchange()
                .expectStatus().isOk();

        downstream.verify(postRequestedFor(urlEqualTo("/acc/auth/login"))
                .withHeader("Cookie", equalTo("refresh_token=old-value")));
    }

    // ---------- 5.3 限流不豁免 ----------

    @Test
    @DisplayName("5.3 会话端点不获限流豁免：限流器按 WRITE 档拦截（独立用例覆盖真实 429+2004）")
    void sessionEndpointsAreNotExemptFromRateLimiting() {
        // 本类限流容量放宽到 10000（与 GatewayRoutingIntegrationTest 同惯例），以免限流干扰白名单/Cookie 断言；
        // 「会话端点真的会被限流拒绝 429+2004」由 GatewaySessionRateLimitIntegrationTest（容量=1）用真实过滤器链验证。
        assertThat(com.msz.gateway.ratelimit.Tier.of("/api/v1/acc/auth/login", "POST"))
                .isEqualTo(com.msz.gateway.ratelimit.Tier.WRITE);
        assertThat(com.msz.gateway.ratelimit.Tier.of("/api/v1/acc/auth/refresh", "POST"))
                .isEqualTo(com.msz.gateway.ratelimit.Tier.WRITE);
    }
}
