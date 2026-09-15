package com.msz.acc.infrastructure.auth;

import com.msz.acc.infrastructure.web.TraceIds;
import com.msz.common.api.Envelope;
import com.msz.common.api.ErrorCode;
import jakarta.servlet.Filter;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.ServletRequest;
import jakarta.servlet.ServletResponse;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;

import java.io.IOException;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Set;

/**
 * 信任头鉴权过滤器(2026-09-15,网关唯一鉴权点落地):服务内**不再验签 JWT**,
 * 只读取网关验签后透传的身份头并组装 {@link AuthContext}。
 *
 * <p>身份头(与网关 `JwtAuthFilter` 写入口径一致):{@code X-User-Id}(JWT sub)、
 * {@code X-User-Role}(六方角色)、{@code X-User-Mfa}(敏感操作二次鉴权)、{@code X-User-Jti}(审计)。</p>
 *
 * <p>逻辑:白名单路径(公开接口,及 callback/internal 由内部 Token 鉴权)直接放行;
 * **受保护路径缺少 {@code X-User-Id} → 401 + code 2001(fail-closed)**——网关是唯一鉴权点,
 * 内网直连且无身份头即视为未认证,不放行;通过 → 组装 AuthContext 写入
 * {@code request.setAttribute("authContext", ...)}。业务越权(2002/403)由 {@link FundsGuard} 在服务内执行。</p>
 *
 * <p><b>2026-09-15 会话端点接入</b>：白名单增 {@code /acc/auth/login}、{@code /acc/auth/refresh}
 * （无短 token 时的必经入口）；{@code /acc/auth/logout} **不进白名单**（需有效短 token 或有效长 token
 * Cookie，由 {@code AuthController} 自行判定）。白名单匹配改为**路径段边界**
 * （{@link AuthPathMatcher}），避免 {@code /acc/auth/loginAny} 蹭白名单。</p>
 *
 * <p>信任前提:服务只接受内网(网关/Nginx)流量,且网关在入口无条件剥离客户端伪造的
 * {@code X-User-*} 头(见 `services/gateway` RequestSanitizerFilter)。</p>
 */
public final class TrustedHeaderAuthFilter implements Filter {

    public static final String USER_ID_HEADER = "X-User-Id";
    public static final String USER_ROLE_HEADER = "X-User-Role";
    public static final String USER_MFA_HEADER = "X-User-Mfa";
    public static final String USER_JTI_HEADER = "X-User-Jti";

    private static final String ATTR_AUTH_CONTEXT = "authContext";

    private final Set<String> noAuthPaths;

    public TrustedHeaderAuthFilter(Set<String> noAuthPaths) {
        this.noAuthPaths = Set.copyOf(noAuthPaths);
    }

    @Override
    public void doFilter(ServletRequest request, ServletResponse response, FilterChain chain)
            throws IOException, ServletException {
        HttpServletRequest req = (HttpServletRequest) request;
        HttpServletResponse res = (HttpServletResponse) response;

        String uri = req.getRequestURI();
        if (AuthPathMatcher.matchesAny(uri, noAuthPaths)) {
            chain.doFilter(req, res);
            return;
        }

        String accountId = req.getHeader(USER_ID_HEADER);
        if (accountId == null || accountId.isBlank()) {
            writeUnauthorized(req, res);
            return;
        }
        String role = req.getHeader(USER_ROLE_HEADER);
        String jti = req.getHeader(USER_JTI_HEADER);
        boolean mfa = "true".equalsIgnoreCase(req.getHeader(USER_MFA_HEADER));

        req.setAttribute(ATTR_AUTH_CONTEXT, new AuthContext(accountId, role, jti, mfa));
        chain.doFilter(req, res);
    }

    private void writeUnauthorized(HttpServletRequest req, HttpServletResponse res) throws IOException {
        res.setStatus(HttpServletResponse.SC_UNAUTHORIZED);
        res.setContentType("application/json;charset=UTF-8");
        Envelope<Void> envelope = Envelope.fail(ErrorCode.UNAUTHORIZED, ErrorCode.message(ErrorCode.UNAUTHORIZED),
                TraceIds.of(req));
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("code", envelope.code());
        body.put("message", envelope.message());
        body.put("data", envelope.data());
        body.put("traceId", envelope.traceId());
        body.put("timestamp", envelope.timestamp());
        res.getWriter().write(Json.toJson(body));
    }
}
