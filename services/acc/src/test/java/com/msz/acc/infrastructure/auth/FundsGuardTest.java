package com.msz.acc.infrastructure.auth;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * SEC-01 / 2002 口径：资金访问守卫（监管专属）+ 资源归属校验（越权）。
 */
class FundsGuardTest {

    @Test
    @DisplayName("SEC-01 REGULATOR 可访问 funds")
    void ut_regulatorCanAccessFunds() {
        AuthContext ctx = new AuthContext("1001", "REGULATOR", "jti-1");

        assertThat(FundsGuard.canAccessFunds(ctx)).isTrue();
    }

    @Test
    @DisplayName("SEC-01 CONSUMER 不可访问 funds")
    void ut_consumerCannotAccessFunds() {
        AuthContext ctx = new AuthContext("1001", "CONSUMER", "jti-1");

        assertThat(FundsGuard.canAccessFunds(ctx)).isFalse();
    }

    @Test
    @DisplayName("SEC-01 同账号 ownsResource true")
    void ut_ownsResourceSameAccountTrue() {
        AuthContext ctx = new AuthContext("1001", "CONSUMER", "jti-1");

        assertThat(FundsGuard.ownsResource(ctx, 1001L)).isTrue();
    }

    @Test
    @DisplayName("SEC-01 跨账号 ownsResource false（越权 2002）")
    void ut_ownsResourceCrossAccountFalse() {
        AuthContext ctx = new AuthContext("1001", "CONSUMER", "jti-1");

        assertThat(FundsGuard.ownsResource(ctx, 1002L)).isFalse();
    }
}
