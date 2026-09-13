package com.msz.acc.domain.model;

/**
 * 实名状态机（er.md §6.1 / PDD §5.1.2）：
 * UNREALNAMED → REALNAMING → REALNAMED / SUSPENDED。
 */
public enum RealNameStatus {
    UNREALNAMED,
    REALNAMING,
    REALNAMED,
    SUSPENDED
}
