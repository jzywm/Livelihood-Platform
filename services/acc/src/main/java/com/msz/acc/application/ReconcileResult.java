package com.msz.acc.application;

/**
 * 对账结果：reconcileId 任务号 + status（RUNNING/DONE/DIFF）+ diffCount + alertCode（DIFF → 3009，否则 0）。
 */
public record ReconcileResult(String reconcileId, String status, long diffCount, int alertCode) {
}
