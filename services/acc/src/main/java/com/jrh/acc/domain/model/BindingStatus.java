package com.msz.acc.domain.model;

/**
 * 收款账户绑定状态（er.md §6.4）：解绑置 UNBOUND 不删行，重新绑定复用原行置 BOUND。
 */
public enum BindingStatus {
    BOUND,
    UNBOUND
}
