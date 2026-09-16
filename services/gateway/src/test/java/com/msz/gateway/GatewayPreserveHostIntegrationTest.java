package com.msz.gateway;

import com.github.tomakehurst.wiremock.WireMockServer;
import com.github.tomakehurst.wiremock.verification.LoggedRequest;
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

import java.util.List;
import java.util.Map;

import static com.github.tomakehurst.wiremock.client.WireMock.equalTo;
import static com.github.tomakehurst.wiremock.client.WireMock.get;
import static com.github.tomakehurst.wiremock.client.WireMock.getRequestedFor;
import static com.github.tomakehurst.wiremock.client.WireMock.ok;
import static com.github.tomakehurst.wiremock.client.WireMock.urlEqualTo;
import static com.github.tomakehurst.wiremock.core.WireMockConfiguration.options;
import static org.assertj.core.api.Assertions.assertThat;

/**
 * 最终评审 Important I1(裁定 R-A16)的**网关侧**集成验证:路由必须把客户端(或入口代理)传来的
 * 原始 {@code Host} 原样透传给下游。
 *
 * <p>为什么需要:SCG 默认用路由目标(下游内网地址)作为发给下游的 {@code Host},ACC 的会话来源校验
 * (裁定 R-A15「同源默认放行」)必须知道**浏览器看到的来源**,否则「浏览器 → Nginx → 网关 → ACC」
 * 默认拓扑下换发/仅 Cookie 登出会被判跨源而 401(登录可用、换发必 401)。acc 路由上的
 * {@code PreserveHostHeader} 过滤器即为此设。</p>
 *
 * <p>断言分两层:①下游确实收到客户端给的 {@code Host}(含带端口的形态,证明是**原样**而不是改写);
 * ②同一上下文里既有的路径重写/白名单/伪造身份头剥离行为不变(证明该过滤器没有破坏路由与鉴权链路)。</p>
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT,
        properties = {
                "gateway.store=memory",
                "gateway.auth.jwt-secret=" + TestSecrets.FIXTURE_SECRET,
                "gateway.rate-limit.ip.capacity=10000",
                "gateway.rate-limit.read.capacity=10000",
                "gateway.rate-limit.write.capacity=10000"
        })
class GatewayPreserveHostIntegrationTest {

    private static final WireMockServer downstream = new WireMockServer(options().dynamicPort());

    static {
        // 与 GatewayRoutingIntegrationTest 同一手法:静态块先起桩,保证 @DynamicPropertySource 前可用
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

    /** 取下游最近一次命中该路径的请求(用于逐头核对)。 */
    private LoggedRequest lastDownstreamRequest(String path) {
        List<LoggedRequest> requests = downstream.findAll(getRequestedFor(urlEqualTo(path)));
        assertThat(requests).as("下游应收到一次 %s", path).isNotEmpty();
        return requests.get(requests.size() - 1);
    }

    @Test
    void preservesOriginalHostHeaderToDownstream() {
        // 浏览器/入口代理看到的对外域名;旧行为下下游会收到网关改写后的内网地址(下游端口)
        client.get().uri("/api/v1/acc/me")
                .header("Host", "api.example.com")
                .header("Authorization", "Bearer " + jwt())
                .exchange()
                .expectStatus().isOk()
                .expectBody(String.class).isEqualTo("acc-ok");

        downstream.verify(getRequestedFor(urlEqualTo("/acc/me"))
                .withHeader("Host", equalTo("api.example.com")));
        assertThat(lastDownstreamRequest("/acc/me").getHeader("Host")).isEqualTo("api.example.com");
    }

    @Test
    void preservesHostWithExplicitPortVerbatim() {
        // 带端口的 Host 必须原样(含端口),否则 ACC 推断出的「请求自身来源」会缺端口而被判跨源
        client.get().uri("/api/v1/acc/me")
                .header("Host", "api.example.com:8443")
                .header("Authorization", "Bearer " + jwt())
                .exchange()
                .expectStatus().isOk();

        assertThat(lastDownstreamRequest("/acc/me").getHeader("Host")).isEqualTo("api.example.com:8443");
    }

    @Test
    void rewriteWhitelistAndSanitizerUnaffectedByPreservedHost() {
        // 公开路径(白名单):保留 Host 的同时,路径仍被改写、伪造身份头仍被剥离
        client.get().uri("/api/v1/acc/captcha")
                .header("Host", "api.example.com")
                .header("X-User-Id", "victim-1001")
                .header("X-User-Role", "OPERATOR")
                .exchange()
                .expectStatus().isOk()
                .expectBody(String.class).isEqualTo("captcha-ok");

        downstream.verify(getRequestedFor(urlEqualTo("/acc/captcha"))
                .withHeader("Host", equalTo("api.example.com"))
                .withoutHeader("X-User-Id")
                .withoutHeader("X-User-Role"));
    }

    @Test
    void unauthenticatedRequestStillRejectedBeforeRouting() {
        // 未带 token(不在白名单):鉴权仍在路由前拦下,与 Host 保留无关
        client.get().uri("/api/v1/acc/me")
                .header("Host", "api.example.com")
                .exchange()
                .expectStatus().isUnauthorized()
                .expectBody().jsonPath("$.code").isEqualTo(2001);
    }
}
