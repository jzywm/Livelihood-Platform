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
 * 白名单(公开接口/内部接口)直接放行;mfa 缺失或非法一律 false。
 */
class TrustedHeaderAuthFilterTest {

    private static final Set<String> NO_AUTH_PATHS =
            Set.of("/acc/captcha", "/acc/register", "/acc/realname/status", "/acc/realname/callback", "/acc/internal");

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
}
