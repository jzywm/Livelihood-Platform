package com.msz.acc.domain.service;

import com.msz.acc.domain.model.BindingStatus;

/**
 * 收款账户绑定生命周期：一行一(账户,通道)复用（er.md §7.4 uk_account_channel），
 * 解绑不删行、重新绑定复用原行。幂等口径对齐 test-plan.md UT-C02/UT-C05。
 */
public final class BindingLifecycle {

    /** 绑定：UNBOUND→BOUND（复用原行）；BOUND→BOUND 幂等（重复绑定返回原绑定）。 */
    public BindingStatus bind(BindingStatus current) {
        return BindingStatus.BOUND;
    }

    /** 解绑：BOUND→UNBOUND（不删行）；UNBOUND→UNBOUND 幂等。 */
    public BindingStatus unbind(BindingStatus current) {
        return BindingStatus.UNBOUND;
    }
}
