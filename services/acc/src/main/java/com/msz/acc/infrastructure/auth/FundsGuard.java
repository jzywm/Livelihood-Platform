package com.msz.acc.infrastructure.auth;

/**
 * 资金/资源访问守卫（2.3 纯函数版；Filter/Controller 装配留 5.x）。
 *
 * <p>六方角色：CONSUMER / MERCHANT / SUPPLIER / WORKER / REGULATOR / OPERATOR。
 * funds（监管对账/资金审计）仅监管角色 REGULATOR 可访问；资源归属校验按同账号判定（越权 2002 口径）。
 */
public final class FundsGuard {

    public static final String ROLE_REGULATOR = "REGULATOR";

    private FundsGuard() {
    }

    /** 是否可访问资金审计/对账：仅 role == REGULATOR 为 true。 */
    public static boolean canAccessFunds(AuthContext ctx) {
        return ctx != null && ROLE_REGULATOR.equals(ctx.role());
    }

    /** 资源归属校验：同账号才 true（越权 2002）。 */
    public static boolean ownsResource(AuthContext ctx, long accountId) {
        return ctx != null && String.valueOf(accountId).equals(ctx.accountId());
    }
}
