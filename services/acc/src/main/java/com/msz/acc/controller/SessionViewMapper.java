package com.msz.acc.controller;

import com.msz.acc.application.SessionFlow;
import com.msz.acc.controller.dto.SessionView;
import com.msz.acc.infrastructure.auth.session.AccessTokenIssuer;

/**
 * {@link SessionFlow} 结果 → {@link SessionView} 视图映射（登录与换发共用，口径一致）。
 *
 * <p>刻意只映射短 token：长 token 由控制器写 `Set-Cookie`，不进入响应体（spec「the refresh token
 * MUST be delivered only through Set-Cookie and MUST NOT appear in the response body」）。</p>
 */
public final class SessionViewMapper {

    public SessionView toView(SessionFlow.LoginOutcome outcome) {
        return new SessionView(outcome.accessToken(), SessionView.BEARER,
                AccessTokenIssuer.ACCESS_TOKEN_TTL_SECONDS, accountIdOf(outcome.accountId()), outcome.role(),
                outcome.mfa());
    }

    public SessionView toView(SessionFlow.RefreshOutcome outcome) {
        return new SessionView(outcome.accessToken(), SessionView.BEARER,
                AccessTokenIssuer.ACCESS_TOKEN_TTL_SECONDS, accountIdOf(outcome.accountId()), outcome.role(),
                outcome.mfa());
    }

    /** 账户 ID 口径与 /acc/me 一致：{@code acc_<account_id>}。 */
    private static String accountIdOf(long accountId) {
        return "acc_" + accountId;
    }
}
