package com.msz.acc.infrastructure.auth;

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

/**
 * 鉴权 Filter 最小版（2.3）：Bearer JWT 解析 / 吊销检查 / 六方角色透传。
 *
 * <p>逻辑：无 Authorization 头或非 Bearer → 401 + code 2001；验签/过期失败 → 401 + 2001；
 * 已吊销 → 401 + 2001；通过 → 解析 sub/role/jti 组装 {@link AuthContext} 写入
 * {@code request.setAttribute("authContext", ...)} 并放行。资金/资源级越权（2002/403）由
 * {@link FundsGuard} 在后续装配（5.x）执行。
 */
public final class AuthFilter implements Filter {

    private static final String AUTH_HEADER = "Authorization";
    private static final String BEARER_PREFIX = "Bearer ";
    private static final String ATTR_AUTH_CONTEXT = "authContext";

    private final JwtCodec codec;
    private final String secret;
    private final RevocationStore revocationStore;

    public AuthFilter(JwtCodec codec, String secret, RevocationStore revocationStore) {
        this.codec = codec;
        this.secret = secret;
        this.revocationStore = revocationStore;
    }

    @Override
    public void doFilter(ServletRequest request, ServletResponse response, FilterChain chain)
            throws IOException, ServletException {
        HttpServletRequest req = (HttpServletRequest) request;
        HttpServletResponse res = (HttpServletResponse) response;

        String header = req.getHeader(AUTH_HEADER);
        if (header == null || !header.startsWith(BEARER_PREFIX)) {
            writeUnauthorized(res);
            return;
        }
        String token = header.substring(BEARER_PREFIX.length()).trim();

        Map<String, Object> claims;
        try {
            claims = codec.verify(token, secret);
        } catch (AuthException e) {
            writeUnauthorized(res);
            return;
        }

        String jti = (String) claims.get("jti");
        if (revocationStore.isRevoked(jti)) {
            writeUnauthorized(res);
            return;
        }

        AuthContext ctx = new AuthContext((String) claims.get("sub"), (String) claims.get("role"), jti);
        req.setAttribute(ATTR_AUTH_CONTEXT, ctx);
        chain.doFilter(req, res);
    }

    private void writeUnauthorized(HttpServletResponse res) throws IOException {
        res.setStatus(HttpServletResponse.SC_UNAUTHORIZED);
        res.setContentType("application/json;charset=UTF-8");
        Envelope<Void> envelope = Envelope.fail(ErrorCode.UNAUTHORIZED, ErrorCode.message(ErrorCode.UNAUTHORIZED), traceId());
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("code", envelope.code());
        body.put("message", envelope.message());
        body.put("data", envelope.data());
        body.put("traceId", envelope.traceId());
        body.put("timestamp", envelope.timestamp());
        res.getWriter().write(Json.toJson(body));
    }

    private String traceId() {
        return "";
    }
}
