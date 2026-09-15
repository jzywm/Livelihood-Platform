package com.msz.acc.infrastructure.auth;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletRequest;
import jakarta.servlet.ServletResponse;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;

import java.util.Set;
import java.util.concurrent.atomic.AtomicReference;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * TrustedHeaderAuthFilter(2026-09-15 网关唯一鉴权点):服务内只读网关透传身份头——
 * 缺/空白 {@code X-User-Id} → 401 + 2001(fail-closed);有身份头 → 组装 authContext 放行;
 * 白名单(公开接口/内部接口/会话登录与换发)直接放行;mfa 缺失或非法一律 false。
 *
 * <p><b>2026-09-15 白名单增项与匹配口径</b>:会话端点登录/换发进入白名单（无短 token 时的必经入口），
 * <b>登出不进白名单</b>（需有效短 token）；匹配由 {@code startsWith} 改为**路径段边界**
 * （{@link AuthPathMatcher}），使 {@code /acc/auth/loginAny} 不能蹭 {@code /acc/auth/login}。</p>
 */
class TrustedHeaderAuthFilterTest {

    private static final Set<String> NO_AUTH_PATHS = Set.of(
            "/acc/captcha", "/acc/register", "/acc/realname/status", "/acc/realname/callback", "/acc/internal",
            "/acc/auth/login", "/acc/auth/refresh");

    private final TrustedHeaderAuthFilter filter = new TrustedHeaderAuthFilter(NO_AUTH_PATHS);

    private record Result(int status, String body, boolean chained, Object authContext) {
    }

    private Result run(String uri, java.util.Map<String, String> headers) throws Exception {
        MockHttpServletRequest request = new MockHttpServletRequest("GET", uri);
        headers.forEach(request::addHeader);
        MockHttpServletResponse response = new MockHttpServletResponse();
        AtomicReference<Object> context = new AtomicReference<>();
        AtomicReference<Boolean> chained = new AtomicReference<>(false);

        FilterChain chain = new FilterChain() {
            @Override
            public void doFilter(ServletRequest req, ServletResponse res) {
                chained.set(true);
                context.set(req.getAttribute("authContext"));
            }
        };
        filter.doFilter(request, response, chain);
        return new Result(response.getStatus(), response.getContentAsString(), chained.get(), context.get());
    }

    @Test
    @DisplayName("缺身份头 → 401 + code 2001(不泄露细节)")
    void missingIdentityHeaderRejected() throws Exception {
        Result result = run("/acc/me", java.util.Map.of());

        assertThat(result.status()).isEqualTo(401);
        assertThat(result.chained()).isFalse();
        assertThat(result.body()).contains("\"code\":2001", "\"message\":\"未登录 / Token 失效\"", "traceId");
    }

    @Test
    @DisplayName("空白身份头 → 401(fail-closed)")
    void blankIdentityHeaderRejected() throws Exception {
        Result result = run("/acc/me", java.util.Map.of("X-User-Id", "   "));

        assertThat(result.status()).isEqualTo(401);
        assertThat(result.chained()).isFalse();
    }

    @Test
    @DisplayName("有效身份头 → 放行并写入 authContext(四字段)")
    void validIdentityHeadersPassThrough() throws Exception {
        Result result = run("/acc/me", java.util.Map.of(
                "X-User-Id", "1001",
                "X-User-Role", "REGULATOR",
                "X-User-Mfa", "true",
                "X-User-Jti", "jti-1"));

        assertThat(result.status()).isEqualTo(200);
        assertThat(result.chained()).isTrue();
        assertThat(result.authContext()).isEqualTo(new AuthContext("1001", "REGULATOR", "jti-1", true));
    }

    @Test
    @DisplayName("mfa 缺失或非法 → false;角色可空")
    void mfaDefaultsFalseAndRoleOptional() throws Exception {
        Result missingMfa = run("/acc/me", java.util.Map.of("X-User-Id", "1001"));
        assertThat(missingMfa.authContext()).isEqualTo(new AuthContext("1001", null, null, false));

        Result bogusMfa = run("/acc/me", java.util.Map.of("X-User-Id", "1001", "X-User-Mfa", "yes"));
        assertThat(((AuthContext) bogusMfa.authContext()).mfa()).isFalse();
    }

    @Test
    @DisplayName("白名单路径(公开接口与内部接口)无身份头直接放行")
    void whitelistedPathsPassThrough() throws Exception {
        Result result = run("/acc/captcha", java.util.Map.of());
        assertThat(result.status()).isEqualTo(200);
        assertThat(result.chained()).isTrue();

        Result internal = run("/acc/internal/account/1001", java.util.Map.of());
        assertThat(internal.chained()).isTrue();
    }

    @Test
    @DisplayName("4.2 会话白名单：登录/换发无身份头放行（无短 token 时的必经入口）")
    void sessionLoginAndRefreshPassWithoutIdentityHeader() throws Exception {
        Result login = run("/acc/auth/login", java.util.Map.of());
        assertThat(login.status()).isEqualTo(200);
        assertThat(login.chained()).isTrue();

        Result refresh = run("/acc/auth/refresh", java.util.Map.of());
        assertThat(refresh.status()).isEqualTo(200);
        assertThat(refresh.chained()).isTrue();
    }

    @Test
    @DisplayName("4.2 登出**不在白名单**：无身份头 → 401（需有效短 token 或有效长 token Cookie）")
    void sessionLogoutStaysProtected() throws Exception {
        Result logout = run("/acc/auth/logout", java.util.Map.of());

        assertThat(logout.status()).isEqualTo(401);
        assertThat(logout.chained()).isFalse();
        assertThat(logout.body()).contains("\"code\":2001");
    }

    @Test
    @DisplayName("4.2 段边界：/acc/auth/loginAny 不得蹭 /acc/auth/login 的白名单（否则即绕过点）")
    void lookAlikePathsDoNotRideTheWhitelist() throws Exception {
        assertThat(run("/acc/auth/loginAny", java.util.Map.of()).status()).isEqualTo(401);
        assertThat(run("/acc/auth/login/../me", java.util.Map.of()).status()).isEqualTo(401);
        assertThat(run("/acc/auth/refreshAny", java.util.Map.of()).status()).isEqualTo(401);
        assertThat(run("/acc/registerAny", java.util.Map.of()).status()).isEqualTo(401);
        assertThat(run("/acc/captchaX", java.util.Map.of()).status()).isEqualTo(401);
    }

    @Test
    @DisplayName("4.2 段边界不削弱既有白名单：白名单前缀的子路径仍放行（/acc/auth/login 语义不外溢）")
    void segmentBoundaryKeepsSubPathSemantics() throws Exception {
        // 既有白名单项本身仍按「自身或子路径」放行（与网关 RequestPaths.matchesPrefix 同语义）
        assertThat(run("/acc/internal", java.util.Map.of()).chained()).isTrue();
        assertThat(run("/acc/auth/login", java.util.Map.of()).chained()).isTrue();
        assertThat(run("/acc/auth/login/extra", java.util.Map.of()).chained()).isTrue();
    }
}
