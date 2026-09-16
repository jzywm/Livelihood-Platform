package com.msz.acc.controller;

import com.msz.acc.application.SessionFlow;
import com.msz.acc.controller.dto.SessionView;

/**
 * {@link SessionFlow} 结果 → {@link SessionView} 视图映射（登录与换发共用，口径一致）。
 *
 * <p>刻意只映射短 token：长 token 由控制器写 `Set-Cookie`，不进入响应体（spec「the refresh token
 * MUST be delivered only through Set-Cookie and MUST NOT appear in the response body」）。</p>
 *
 * <p><b>FIX-1/B6</b>：{@code expiresIn} 取**有效**短 token 有效期（装配层按
 * {@code acc.session.access-token-ttl-seconds} 夹紧后的值），不再硬编码 900——否则运维把有效期调小后
 * 客户端仍按 900s 使用已过期的短 token。</p>
 */
public final class SessionViewMapper {

    private final long accessTokenTtlSeconds;

    public SessionViewMapper(long accessTokenTtlSeconds) {
        this.accessTokenTtlSeconds = accessTokenTtlSeconds;
    }

    public SessionView toView(SessionFlow.LoginOutcome outcome) {
        return new SessionView(outcome.accessToken(), SessionView.BEARER,
                accessTokenTtlSeconds, accountIdOf(outcome.accountId()), outcome.role(),
                outcome.mfa());
    }

    public SessionView toView(SessionFlow.RefreshOutcome outcome) {
        return new SessionView(outcome.accessToken(), SessionView.BEARER,
                accessTokenTtlSeconds, accountIdOf(outcome.accountId()), outcome.role(),
                outcome.mfa());
    }

    /** 账户 ID 口径与 /acc/me 一致：{@code acc_<account_id>}。 */
    private static String accountIdOf(long accountId) {
        return "acc_" + accountId;
    }
}
