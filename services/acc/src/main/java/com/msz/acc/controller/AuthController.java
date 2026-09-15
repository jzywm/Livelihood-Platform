package com.msz.acc.controller;

import com.msz.acc.application.SessionFlow;
import com.msz.acc.application.SessionOperations;
import com.msz.acc.controller.dto.SessionView;
import com.msz.acc.infrastructure.auth.AuthException;
import com.msz.acc.infrastructure.auth.JwtCodec;
import com.msz.acc.infrastructure.auth.OriginValidator;
import com.msz.acc.infrastructure.web.TraceIds;
import com.msz.common.api.Envelope;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.http.HttpHeaders;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

import java.time.Clock;
import java.util.Map;

/**
 * 会话凭据端点（openapi v1.2.0 `/acc/auth/{login,refresh,logout}`；spec `acc-session`）。
 *
 * <ul>
 *   <li>{@code POST /acc/auth/login}：手机号 + 人机验证票据免密登录；短 token 走响应体，
 *       长 token **仅** `Set-Cookie`（HttpOnly/Secure/SameSite/Path 见 {@link SessionCookie}）。</li>
 *   <li>{@code POST /acc/auth/refresh}：以 Cookie 中的长 token 换发新 token 对；先做
 *       Origin/Referer 校验（R-A3），**校验不过则不轮换任何 token**。</li>
 *   <li>{@code POST /acc/auth/logout}：吊销当前会话族（短 token 的 `jti` 入网关共享吊销名单 +
 *       族失效 + 清 Cookie）；同时接受「有效短 token」或「仅凭长 token Cookie」两种凭据，
 *       后者同样校验来源；**幂等**。</li>
 * </ul>
 *
 * <p><b>日志脱敏</b>：本类不打日志，token 原文与 Cookie 值只出现在响应体/响应头中，不进任何日志
 * 语句（审计事件由 {@link SessionFlow} 以族/jti/账户维度记录，不含 token 原文）。</p>
 *
 * <p><b>短 token 解析（登出）</b>：网关已验签并把身份放进 `X-User-*` 头，但登出需要**精确的 jti 与
 * 会话族**（还要算剩余有效期写吊销名单 TTL），故本控制器用同一个 {@link JwtCodec} 与**同一个
 * {@link Clock}**（与签发侧同源——用系统时钟另行判定会在时钟不可注入时把刚签发的合法 token
 * 误判为已过期）解析；解析失败一律按「无短 token」处置，交由 Cookie 兜底（不因头部异常直接 500）。</p>
 */
@RestController
public class AuthController {

    private static final String BEARER_PREFIX = "Bearer ";

    /** 登录请求体（openapi `LoginRequest`；refresh 无请求体）。 */
    public record LoginRequest(String mobile, String captchaToken) {
    }

    /** 登出响应（openapi `LogoutResult`）。 */
    public record LogoutResult(boolean revoked) {
    }

    private final SessionOperations sessionFlow;
    private final OriginValidator originValidator;
    private final SessionCookie sessionCookie;
    private final SessionViewMapper viewMapper;
    private final JwtCodec jwtCodec;
    private final String jwtSecret;
    private final Clock clock;

    public AuthController(SessionOperations sessionFlow, OriginValidator originValidator,
                          SessionCookie sessionCookie, SessionViewMapper viewMapper, JwtCodec jwtCodec,
                          String jwtSecret, Clock clock) {
        this.sessionFlow = sessionFlow;
        this.originValidator = originValidator;
        this.sessionCookie = sessionCookie;
        this.viewMapper = viewMapper;
        this.jwtCodec = jwtCodec;
        this.jwtSecret = jwtSecret;
        this.clock = clock;
    }

    /** 免密登录：签发双 token（长 token 仅 Set-Cookie）。 */
    @PostMapping("/acc/auth/login")
    public Envelope<SessionView> login(@RequestBody(required = false) LoginRequest body,
                                       HttpServletRequest request, HttpServletResponse response) {
        SessionFlow.LoginOutcome outcome = sessionFlow.login(body == null ? null : body.mobile(),
                body == null ? null : body.captchaToken());
        response.addHeader(HttpHeaders.SET_COOKIE, sessionCookie.setCookieValue(outcome.refreshToken()));
        return Envelope.ok(viewMapper.toView(outcome), TraceIds.of(request));
    }

    /** 换发：refresh 单次使用 + 轮换；来源校验不过则拒绝且不轮换。 */
    @PostMapping("/acc/auth/refresh")
    public Envelope<SessionView> refresh(HttpServletRequest request, HttpServletResponse response) {
        requireTrustedOrigin(request);
        String refreshToken = sessionCookie.refreshTokenOf(request);
        if (refreshToken == null) {
            throw new AuthException("缺少 refresh Cookie");
        }
        SessionFlow.RefreshOutcome outcome = sessionFlow.refresh(refreshToken);
        response.addHeader(HttpHeaders.SET_COOKIE, sessionCookie.setCookieValue(outcome.refreshToken()));
        return Envelope.ok(viewMapper.toView(outcome), TraceIds.of(request));
    }

    /** 登出：吊销会话族 + 清 Cookie（幂等）。 */
    @PostMapping("/acc/auth/logout")
    public Envelope<LogoutResult> logout(HttpServletRequest request, HttpServletResponse response) {
        AccessClaims claims = accessClaimsOf(request);
        String refreshToken = sessionCookie.refreshTokenOf(request);
        if (claims == null) {
            // 仅凭长 token Cookie 登出：与换发同口径校验来源（R-A3）
            requireTrustedOrigin(request);
        }
        SessionFlow.LogoutOutcome outcome = sessionFlow.logout(claims == null ? null : claims.jti(),
                claims == null ? null : claims.familyId(), claims == null ? 0L : claims.remainingSeconds(),
                refreshToken);
        response.addHeader(HttpHeaders.SET_COOKIE, sessionCookie.clearCookieValue());
        return Envelope.ok(new LogoutResult(outcome.revoked()), TraceIds.of(request));
    }

    /** 来源校验（R-A3）：带来源头且不在允许列表 → 401 + 2001（且调用方不做任何轮换）。 */
    private void requireTrustedOrigin(HttpServletRequest request) {
        if (!originValidator.isAllowed(request.getHeader("Origin"), request.getHeader("Referer"))) {
            throw new AuthException("来源不在允许列表");
        }
    }

    /** 解析短 token 的 jti / 会话族 / 剩余有效期；无有效短 token 返回 null。 */
    private AccessClaims accessClaimsOf(HttpServletRequest request) {
        String header = request.getHeader("Authorization");
        if (header == null || !header.startsWith(BEARER_PREFIX)) {
            return null;
        }
        String token = header.substring(BEARER_PREFIX.length()).trim();
        try {
            // 用与签发同一个 JwtCodec（含同一时钟）解析：过期判定的「现在」必须与签发侧同源，
            // 否则会因时钟不同步把刚签发的合法 token 误判为已过期
            Map<String, Object> claims = jwtCodec.verify(token, jwtSecret);
            Object jti = claims.get("jti");
            Object family = claims.get("fam");
            Object exp = claims.get("exp");
            if (!(jti instanceof String jtiValue) || jtiValue.isBlank()
                    || !(family instanceof String familyValue) || familyValue.isBlank()
                    || !(exp instanceof Number expValue)) {
                return null;
            }
            return new AccessClaims(jtiValue, familyValue,
                    Math.max(expValue.longValue() - clock.instant().getEpochSecond(), 1L));
        } catch (RuntimeException e) {
            // 头部不可解析：按「无短 token」处置（Cookie 兜底），不因头部异常直接 500
            return null;
        }
    }

    /** 短 token 解析结果。 */
    private record AccessClaims(String jti, String familyId, long remainingSeconds) {
    }
}
