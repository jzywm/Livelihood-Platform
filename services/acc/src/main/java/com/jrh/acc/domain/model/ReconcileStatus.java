package com.msz.acc.domain.model;

/**
 * 对账任务状态（er.md §6.5）：RUNNING → DONE（无差异）/ DIFF（有差异，>0 报 3009）。
 */
public enum ReconcileStatus {
    RUNNING,
    DONE,
    DIFF
}
