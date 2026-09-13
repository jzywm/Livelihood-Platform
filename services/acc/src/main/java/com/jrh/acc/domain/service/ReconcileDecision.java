package com.msz.acc.domain.service;

import com.msz.acc.domain.model.ReconcileStatus;
import com.msz.acc.domain.support.AccBusinessException;

/**
 * 对账任务决策：diff=0 → DONE；diff>0 → DIFF 并报 3009（er.md §6.5/§7.5）。
 * 口径对齐 test-plan.md UT-D02/UT-D03。
 */
public final class ReconcileDecision {

    public static final int DIFF_ALERT_CODE = 3009;

    /** 对账完成：仅 RUNNING 可结束；diffCount>0 → DIFF，否则 DONE。 */
    public ReconcileStatus finish(ReconcileStatus current, long diffCount) {
        if (current != ReconcileStatus.RUNNING) {
            throw new AccBusinessException(3007, "当前对账任务状态不允许结束");
        }
        return diffCount > 0 ? ReconcileStatus.DIFF : ReconcileStatus.DONE;
    }

    /** 是否需要触发对账不一致提示（3009）。 */
    public boolean needsAlert(ReconcileStatus status) {
        return status == ReconcileStatus.DIFF;
    }

    /** 不一致提示业务码：DIFF → 3009；否则 0。 */
    public int alertCode(ReconcileStatus status) {
        return needsAlert(status) ? DIFF_ALERT_CODE : 0;
    }
}
