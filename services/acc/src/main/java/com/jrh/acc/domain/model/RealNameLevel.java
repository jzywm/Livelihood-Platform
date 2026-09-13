package com.msz.acc.domain.model;

/**
 * 实名等级（er.md §6.2 / PDD §5.14.1 I-06）：
 * BASE 基础回传 / ENHANCED 强实名（NFC 读证 + 人脸活体，M2）。
 */
public enum RealNameLevel {
    BASE,
    ENHANCED
}
