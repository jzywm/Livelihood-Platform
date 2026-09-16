package com.msz.acc.controller;

import com.msz.acc.application.SessionFlow;
import com.msz.acc.controller.dto.SessionView;
import com.msz.acc.infrastructure.auth.AuthException;
import com.msz.acc.infrastructure.auth.OriginValidator;
import com.msz.acc.infrastructure.auth.session.SessionStoreUnavailableException;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * {@link AuthController} 组件测试（任务 4.1/4.3）：响应 Envelope 结构、`Set-Cookie` 属性、
 * token 不进 Cookie/不进 body 的口径、日志脱敏、来源校验与存储故障映射。
 *
 * <p>{@link SessionFlow} 用 mock：本用例只验证 **HTTP 契约**（Cookie 属性、状态码、错误码、
 * 参数来源），流程语义由 {@code SessionFlowTest} 覆盖。</p>
 */
class AuthControllerTest {

    private static final String FIXTURE_ACCESS = "eyJhbGciOiJIUzI1NiJ9.fixture-access.signature";
    private static final String FIXTURE_REFRESH = "eyJhbGciOiJIUzI1NiJ9.fixture-refresh.signature";

    private static final SessionCookie DEFAULT_COOKIE = SessionCookie.forSessionEndpoints("refresh_token", true,
            "Lax", "/api/v1/acc/auth", 604_800L);

    /** 固定时刻时钟：登出时短 token 剩余有效期因此可精确断言。 */
    private static final java.time.Clock FIXED_CLOCK = java.time.Clock.fixed(
            java.time.Instant.ofEpochSecond(TestSessionTokens.FIXED_EPOCH_SECOND), java.time.ZoneOffset.UTC);

    private StubSessionFlow sessionFlow;
    private MockMvc mockMvc;

    @BeforeEach
    void setUp() {
        sessionFlow = new StubSessionFlow();
        mockMvc = mockMvcWith(sessionFlow, new OriginValidator(""), DEFAULT_COOKIE);
    }

    private static MockMvc mockMvcWith(com.msz.acc.application.SessionOperations flow, OriginValidator validator, SessionCookie cookie) {
        AuthController controller = new AuthController(flow, validator, cookie, new SessionViewMapper(900L),
                new com.msz.acc.infrastructure.auth.JwtCodec(FIXED_CLOCK), TestSessionTokens.FIXTURE_SECRET,
                FIXED_CLOCK);
        // 注册全局异常处理器：断言 401/2001 与 503/5003 的映射口径
        return MockMvcBuilders.standaloneSetup(controller)
                .setControllerAdvice(new GlobalExceptionHandler())
                .build();
    }

    private SessionCookie cookieOf(boolean secure, String sameSite) {
        return SessionCookie.forSessionEndpoints("refresh_token", secure, sameSite, "/api/v1/acc/auth", 604_800L);
    }

    /**
     * 手工测试替身（不用 Mockito：本模块 MockMaker 为 {@code mock-maker-subclass}，无法 mock final
     * 的流程类；此处只需记录调用与给出返回值，替身比桩更直观）。
     */
    private static final class StubSessionFlow implements com.msz.acc.application.SessionOperations {

        private SessionFlow.LoginOutcome loginResult;
        private RuntimeException loginFailure;
        private SessionFlow.RefreshOutcome refreshResult;
        private RuntimeException refreshFailure;
        private SessionFlow.LogoutOutcome logoutResult = new SessionFlow.LogoutOutcome(true);
        private RuntimeException logoutFailure;

        private final java.util.List<Object[]> loginCalls = new java.util.ArrayList<>();
        private final java.util.List<String> refreshCalls = new java.util.ArrayList<>();
        private final java.util.List<Object[]> logoutCalls = new java.util.ArrayList<>();

        @Override
        public SessionFlow.LoginOutcome login(String mobile, String captchaToken) {
            loginCalls.add(new Object[]{mobile, captchaToken});
            if (loginFailure != null) {
                throw loginFailure;
            }
            return loginResult;
        }

        @Override
        public SessionFlow.RefreshOutcome refresh(String refreshToken) {
            refreshCalls.add(refreshToken);
            if (refreshFailure != null) {
                throw refreshFailure;
            }
            return refreshResult;
        }

        @Override
        public SessionFlow.LogoutOutcome logout(String accessJti, String accessFamilyId,
                                                long accessRemainingSeconds, String refreshToken) {
            logoutCalls.add(new Object[]{accessJti, accessFamilyId, accessRemainingSeconds, refreshToken});
            if (logoutFailure != null) {
                throw logoutFailure;
            }
            return logoutResult;
        }

        int refreshCallCount() {
            return refreshCalls.size();
        }

        Object[] lastLogoutCall() {
            return logoutCalls.get(logoutCalls.size() - 1);
        }
    }

    // ---------- 登录 ----------

    @Test
    @DisplayName("登录成功：短 token 在 body、长 token 仅 Set-Cookie（HttpOnly/Secure/SameSite/Path）")
    void loginReturnsAccessInBodyAndRefreshInCookie() throws Exception {
        sessionFlow.loginResult = new SessionFlow.LoginOutcome(1001L, "CONSUMER", false, "fam_1",
                        FIXTURE_ACCESS, FIXTURE_REFRESH);

        mockMvc.perform(post("/acc/auth/login")
                        .contentType("application/json")
                        .content("{\"mobile\":\"13800138000\",\"captchaToken\":\"ct_1\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(0))
                .andExpect(jsonPath("$.data.accessToken").value(FIXTURE_ACCESS))
                .andExpect(jsonPath("$.data.tokenType").value("Bearer"))
                .andExpect(jsonPath("$.data.expiresIn").value(900))
                .andExpect(jsonPath("$.data.accountId").value("acc_1001"))
                .andExpect(jsonPath("$.data.role").value("CONSUMER"))
                .andExpect(jsonPath("$.data.refreshToken").doesNotExist())
                // 长 token 只在 Set-Cookie 里出现，绝不在 body
                .andExpect(jsonPath("$.data").value(org.hamcrest.Matchers.not(
                        org.hamcrest.Matchers.containsString(FIXTURE_REFRESH))))
                .andExpect(header().string("Set-Cookie", org.hamcrest.Matchers.allOf(
                        org.hamcrest.Matchers.containsString("refresh_token=" + FIXTURE_REFRESH),
                        org.hamcrest.Matchers.containsString("HttpOnly"),
                        org.hamcrest.Matchers.containsString("Secure"),
                        org.hamcrest.Matchers.containsString("SameSite=Lax"),
                        org.hamcrest.Matchers.containsString("Path=/api/v1/acc/auth"),
                        org.hamcrest.Matchers.containsString("Max-Age=604800"))));
    }

    @Test
    @DisplayName("登录因子失败 → 401 + 2001（不泄露失败原因），且不下发任何 Cookie")
    void loginFailureIsUnauthorized() throws Exception {
        sessionFlow.loginFailure = new AuthException("账户不存在");

        mockMvc.perform(post("/acc/auth/login")
                        .contentType("application/json")
                        .content("{\"mobile\":\"13800138000\",\"captchaToken\":\"ct_bad\"}"))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.code").value(2001))
                .andExpect(jsonPath("$.message").value("未登录 / Token 失效"))
                .andExpect(header().doesNotExist("Set-Cookie"));
    }

    @Test
    @DisplayName("会话存储不可用 → 503 + 5003（fail-closed，不签发 token）")
    void loginFailsFastWhenStoreUnavailable() throws Exception {
        sessionFlow.loginFailure = new SessionStoreUnavailableException("存储不可用");

        mockMvc.perform(post("/acc/auth/login")
                        .contentType("application/json")
                        .content("{\"mobile\":\"13800138000\",\"captchaToken\":\"ct_1\"}"))
                .andExpect(status().isServiceUnavailable())
                .andExpect(jsonPath("$.code").value(5003))
                .andExpect(header().doesNotExist("Set-Cookie"));
    }

    // ---------- 换发 ----------

    @Test
    @DisplayName("换发成功：Cookie 中的 refresh 被消费，新 refresh 覆盖 Set-Cookie")
    void refreshRotatesCookie() throws Exception {
        sessionFlow.refreshResult = new SessionFlow.RefreshOutcome(1001L, "CONSUMER", false, "fam_1",
                        FIXTURE_ACCESS, "new-refresh-value");

        mockMvc.perform(post("/acc/auth/refresh").header("Cookie", "refresh_token=" + FIXTURE_REFRESH))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.accessToken").value(FIXTURE_ACCESS))
                .andExpect(header().string("Set-Cookie", org.hamcrest.Matchers.containsString(
                        "refresh_token=new-refresh-value")));

        assertThat(sessionFlow.refreshCalls).containsExactly(FIXTURE_REFRESH);
    }

    @Test
    @DisplayName("换发缺 Cookie → 401 + 2001，且不调用流程（无任何副作用）")
    void refreshWithoutCookieIsUnauthorized() throws Exception {
        mockMvc.perform(post("/acc/auth/refresh"))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.code").value(2001));

        assertThat(sessionFlow.refreshCallCount()).isZero();
    }

    @Test
    @DisplayName("Cookie 头中只有别的 Cookie 时视为缺失（不解析、不误取）")
    void refreshIgnoresUnrelatedCookies() throws Exception {
        mockMvc.perform(post("/acc/auth/refresh").header("Cookie", "other=1; another=2"))
                .andExpect(status().isUnauthorized());

        assertThat(sessionFlow.refreshCallCount()).isZero();
    }

    @Test
    @DisplayName("跨站来源 → 401 + 2001，且**不轮换任何 token**（流程零调用）")
    void crossSiteOriginRejectedWithoutRotation() throws Exception {
        MockMvc strict = mockMvcWith(sessionFlow, new OriginValidator("https://app.example.com"),
                cookieOf(true, "Lax"));

        strict.perform(post("/acc/auth/refresh")
                        .header("Cookie", "refresh_token=" + FIXTURE_REFRESH)
                        .header("Origin", "https://evil.example.com"))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.code").value(2001))
                .andExpect(header().doesNotExist("Set-Cookie"));

        assertThat(sessionFlow.refreshCallCount()).isZero();
    }

    @Test
    @DisplayName("合法来源放行；不带来源头（非浏览器）也放行")
    void allowedOriginAndNoOriginPass() throws Exception {
        sessionFlow.refreshResult = new SessionFlow.RefreshOutcome(1001L, "CONSUMER", false, "fam_1",
                        FIXTURE_ACCESS, "new-refresh");
        MockMvc strict = mockMvcWith(sessionFlow, new OriginValidator("https://app.example.com"),
                cookieOf(true, "Lax"));

        strict.perform(post("/acc/auth/refresh").header("Cookie", "refresh_token=" + FIXTURE_REFRESH)
                        .header("Origin", "https://app.example.com"))
                .andExpect(status().isOk());
        strict.perform(post("/acc/auth/refresh").header("Cookie", "refresh_token=" + FIXTURE_REFRESH)
                        .header("Referer", "https://app.example.com/me"))
                .andExpect(status().isOk());
        strict.perform(post("/acc/auth/refresh").header("Cookie", "refresh_token=" + FIXTURE_REFRESH))
                .andExpect(status().isOk());
    }

    @Test
    @DisplayName("R-A15 同源默认放行：未配置 allowed-origins 时，Origin = 请求自身来源的换发必须 200（原「登录可用、换发必 401」）")
    void sameOriginOriginPassesWithoutAllowListConfiguration() throws Exception {
        sessionFlow.refreshResult = new SessionFlow.RefreshOutcome(1001L, "CONSUMER", false, "fam_1",
                        FIXTURE_ACCESS, "new-refresh");
        // 默认装配：allowed-origins 为空（浏览器同源部署即可用）
        mockMvc.perform(post("/acc/auth/refresh")
                        .header("Cookie", "refresh_token=" + FIXTURE_REFRESH)
                        .header("Origin", "http://localhost"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.accessToken").value(FIXTURE_ACCESS));

        assertThat(sessionFlow.refreshCalls).containsExactly(FIXTURE_REFRESH);
    }

    @Test
    @DisplayName("R-A15 经网关/入口代理：同源判定取 X-Forwarded-Proto/Host（浏览器看到的对外来源）")
    void sameOriginBehindProxyUsesForwardedOrigin() throws Exception {
        sessionFlow.refreshResult = new SessionFlow.RefreshOutcome(1001L, "CONSUMER", false, "fam_1",
                        FIXTURE_ACCESS, "new-refresh");
        MockMvc strict = mockMvcWith(sessionFlow, new OriginValidator(""), cookieOf(true, "Lax"));

        strict.perform(post("/acc/auth/refresh")
                        .header("Cookie", "refresh_token=" + FIXTURE_REFRESH)
                        .header("Origin", "https://app.example.com")
                        .header("X-Forwarded-Proto", "https")
                        .header("X-Forwarded-Host", "app.example.com"))
                .andExpect(status().isOk());
        // 同样的 X-Forwarded-* 但来源是别的站点 → 仍拒绝（转发头不能被跨站请求利用）
        strict.perform(post("/acc/auth/refresh")
                        .header("Cookie", "refresh_token=" + FIXTURE_REFRESH)
                        .header("Origin", "https://evil.example.com")
                        .header("X-Forwarded-Proto", "https")
                        .header("X-Forwarded-Host", "app.example.com"))
                .andExpect(status().isUnauthorized());
    }

    // ---------- 登出 ----------

    @Test
    @DisplayName("登出：短 token 的 jti 与精确剩余有效期取自请求，清 Cookie（Max-Age=0）")
    void logoutRevokesAndClearsCookie() throws Exception {
        sessionFlow.logoutResult = new SessionFlow.LogoutOutcome(true);

        // 用固定密钥/固定时刻签一条短 token，验证控制器确实解析出 jti/fam/剩余有效期
        String accessToken = TestSessionTokens.accessToken();

        mockMvc.perform(post("/acc/auth/logout").header("Authorization", "Bearer " + accessToken))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.revoked").value(true))
                .andExpect(header().string("Set-Cookie", org.hamcrest.Matchers.allOf(
                        org.hamcrest.Matchers.containsString("refresh_token="),
                        org.hamcrest.Matchers.containsString("Max-Age=0"),
                        org.hamcrest.Matchers.containsString("HttpOnly"),
                        org.hamcrest.Matchers.containsString("Path=/api/v1/acc/auth"))));

        Object[] call = sessionFlow.lastLogoutCall();
        assertThat(call[0]).isEqualTo(TestSessionTokens.ACCESS_JTI);
        assertThat(call[1]).isEqualTo(TestSessionTokens.FAMILY_ID);
        assertThat((Long) call[2]).isEqualTo(900L);
        assertThat(call[3]).isNull();
    }

    @Test
    @DisplayName("登出：无效 Bearer 头按「无短 token」处置（不抛异常，交给 Cookie 兜底判定）")
    void logoutWithMalformedHeaderFallsBack() throws Exception {
        sessionFlow.logoutFailure = new AuthException("缺少有效会话凭据");

        mockMvc.perform(post("/acc/auth/logout").header("Authorization", "Bearer not-a-jwt"))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.code").value(2001));

        Object[] call = sessionFlow.lastLogoutCall();
        assertThat(call[0]).isNull();
        assertThat(call[3]).isNull();
    }

    @Test
    @DisplayName("FIX-1 登出：把 refresh 放进 Authorization: Bearer 时不当作短 token（typ 校验，避免给 rf_* 写 7 天冗余吊销键）")
    void refreshTokenInBearerHeaderIsNotTreatedAsAccessToken() throws Exception {
        sessionFlow.logoutResult = new SessionFlow.LogoutOutcome(true);

        mockMvc.perform(post("/acc/auth/logout")
                        .header("Authorization", "Bearer " + TestSessionTokens.refreshToken())
                        .header("Cookie", "refresh_token=" + FIXTURE_REFRESH))
                .andExpect(status().isOk());

        Object[] call = sessionFlow.lastLogoutCall();
        assertThat(call[0]).as("refresh 不是短 token：不得解析出它的 jti").isNull();
        assertThat(call[1]).as("也不得把它的族当作短 token 所属族").isNull();
        assertThat(call[3]).as("按「仅凭 Cookie 登出」路径处置（Cookie 兜底）").isEqualTo(FIXTURE_REFRESH);
    }

    @Test
    @DisplayName("仅凭 Cookie 登出：Cookie 值传给流程，且来源校验与换发同口径")
    void logoutWithCookieOnlyValidatesOrigin() throws Exception {
        MockMvc strict = mockMvcWith(sessionFlow, new OriginValidator("https://app.example.com"),
                cookieOf(true, "Lax"));

        strict.perform(post("/acc/auth/logout")
                        .header("Cookie", "refresh_token=" + FIXTURE_REFRESH)
                        .header("Origin", "https://evil.example.com"))
                .andExpect(status().isUnauthorized());

        assertThat(sessionFlow.logoutCalls).isEmpty();

        sessionFlow.logoutResult = new SessionFlow.LogoutOutcome(true);
        strict.perform(post("/acc/auth/logout")
                        .header("Cookie", "refresh_token=" + FIXTURE_REFRESH)
                        .header("Origin", "https://app.example.com"))
                .andExpect(status().isOk());
    }

    @Test
    @DisplayName("登出幂等：第二次 revoked=false 仍返回成功且清 Cookie（不报错）")
    void repeatedLogoutStillSucceeds() throws Exception {
        sessionFlow.logoutResult = new SessionFlow.LogoutOutcome(false);

        mockMvc.perform(post("/acc/auth/logout").header("Authorization", "Bearer " + TestSessionTokens.accessToken()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(0))
                .andExpect(jsonPath("$.data.revoked").value(false))
                .andExpect(header().string("Set-Cookie", org.hamcrest.Matchers.containsString("Max-Age=0")));
    }

    @Test
    @DisplayName("无任何有效凭据 → 401 + 2001")
    void logoutWithoutCredentialsRejected() throws Exception {
        sessionFlow.logoutFailure = new AuthException("缺少有效会话凭据");

        mockMvc.perform(post("/acc/auth/logout"))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.code").value(2001));
    }

    // ---------- Cookie 属性口径 ----------

    @Test
    @DisplayName("Cookie 属性可配：Secure 关闭与 SameSite=None 按配置输出（本地 HTTP 演练可切）")
    void cookieAttributesAreConfigurable() {
        SessionCookie lax = cookieOf(false, "Lax");
        assertThat(lax.setCookieValue("v")).doesNotContain("Secure").contains("SameSite=Lax");

        SessionCookie none = cookieOf(true, "None");
        assertThat(none.setCookieValue("v")).contains("Secure", "SameSite=None");

        SessionCookie clearing = cookieOf(true, "Lax");
        assertThat(clearing.clearCookieValue()).contains("Max-Age=0").doesNotContain("fixture");
    }

    @Test
    @DisplayName("Cookie 读取：只取配置名；空值/缺头均视为缺失")
    void cookieReadIsNameScoped() throws Exception {
        sessionFlow.refreshResult = new SessionFlow.RefreshOutcome(1001L, "CONSUMER",
                false, "fam_1", FIXTURE_ACCESS, "new");

        mockMvc.perform(post("/acc/auth/refresh").header("Cookie", "other=1; refresh_token=real-value; x=2"))
                .andExpect(status().isOk());
        assertThat(sessionFlow.refreshCalls).containsExactly("real-value");

        mockMvc.perform(post("/acc/auth/refresh").header("Cookie", "refresh_token="))
                .andExpect(status().isUnauthorized());
    }

    @Test
    @DisplayName("SessionView：accountId 前缀 acc_、expiresIn=900、tokenType=Bearer、mfa 透传")
    void sessionViewShape() {
        SessionView view = new SessionViewMapper(900L).toView(
                new SessionFlow.RefreshOutcome(1001L, "REGULATOR", true, "fam_1", FIXTURE_ACCESS, FIXTURE_REFRESH));

        assertThat(view.accountId()).isEqualTo("acc_1001");
        assertThat(view.tokenType()).isEqualTo("Bearer");
        assertThat(view.expiresIn()).isEqualTo(900L);
        assertThat(view.mfa()).isTrue();
        assertThat(view.role()).isEqualTo("REGULATOR");
        assertThat(view.accessToken()).isEqualTo(FIXTURE_ACCESS);
    }
}
