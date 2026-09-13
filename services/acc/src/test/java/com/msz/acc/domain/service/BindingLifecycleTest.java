package com.msz.acc.domain.service;

import com.msz.acc.domain.model.BindingStatus;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 绑定生命周期单元测试 · 对应 test-plan.md UT-C02/UT-C05：
 * 一行一(账户,通道)复用——重复绑定幂等返回原绑定；解绑置 UNBOUND 不删行；再绑复用原行。
 */
class BindingLifecycleTest {

    private final BindingLifecycle lifecycle = new BindingLifecycle();

    @Test
    @DisplayName("UT-C02: 未绑定 → 绑定成功 BOUND")
    void ut_c02_bindFromUnboundCreatesBound() {
        assertThat(lifecycle.bind(BindingStatus.UNBOUND)).isEqualTo(BindingStatus.BOUND);
    }

    @Test
    @DisplayName("UT-C02: 已绑定重复绑定幂等（复用原行）")
    void ut_c02_bindOnBoundIsIdempotent() {
        assertThat(lifecycle.bind(BindingStatus.BOUND)).isEqualTo(BindingStatus.BOUND);
    }

    @Test
    @DisplayName("UT-C05: 解绑置 UNBOUND（不删行语义）")
    void ut_c05_unbindFromBoundMovesToUnbound() {
        assertThat(lifecycle.unbind(BindingStatus.BOUND)).isEqualTo(BindingStatus.UNBOUND);
    }

    @Test
    @DisplayName("UT-C05: 重复解绑幂等")
    void ut_c05_unbindOnUnboundIsIdempotent() {
        assertThat(lifecycle.unbind(BindingStatus.UNBOUND)).isEqualTo(BindingStatus.UNBOUND);
    }

    @Test
    @DisplayName("UT-C05: 解绑后重新绑定复用原行置 BOUND（完整生命周期）")
    void ut_c05_rebindAfterUnbindReusesRow() {
        BindingStatus afterUnbind = lifecycle.unbind(BindingStatus.BOUND);
        assertThat(lifecycle.bind(afterUnbind)).isEqualTo(BindingStatus.BOUND);
    }
}
