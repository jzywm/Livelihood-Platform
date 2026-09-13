package com.msz.acc.domain.service;

import com.msz.acc.domain.model.ReconcileStatus;
import com.msz.acc.domain.support.AccBusinessException;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * 对账决策单元测试 · 对应 test-plan.md UT-D02/UT-D03：
 * diff=0 → DONE；diff>0 → DIFF + 3009 提示；非 RUNNING 不得结束（3007）。
 */
class ReconcileDecisionTest {

    private final ReconcileDecision decision = new ReconcileDecision();

    @Test
    @DisplayName("UT-D02: 对账无差异 diff=0 → DONE")
    void ut_d02_finishWithZeroDiffMarksDone() {
        assertThat(decision.finish(ReconcileStatus.RUNNING, 0)).isEqualTo(ReconcileStatus.DONE);
    }

    @Test
    @DisplayName("UT-D03: 对账有差异 diff>0 → DIFF")
    void ut_d03_finishWithDiffMarksDiff() {
        assertThat(decision.finish(ReconcileStatus.RUNNING, 3)).isEqualTo(ReconcileStatus.DIFF);
    }

    @Test
    @DisplayName("UT-D03: DIFF 触发 3009 不一致提示")
    void ut_d03_diffTriggersAlertCode3009() {
        ReconcileStatus status = decision.finish(ReconcileStatus.RUNNING, 1);
        assertThat(decision.needsAlert(status)).isTrue();
        assertThat(decision.alertCode(status)).isEqualTo(3009);
    }

    @Test
    @DisplayName("UT-D02: DONE 不触发不一致提示")
    void ut_d02_doneDoesNotAlert() {
        ReconcileStatus status = decision.finish(ReconcileStatus.RUNNING, 0);
        assertThat(decision.needsAlert(status)).isFalse();
        assertThat(decision.alertCode(status)).isZero();
    }

    @Test
    @DisplayName("UT-D02/D03: 非 RUNNING 状态不得结束（3007）")
    void ut_d02_finishOnDoneIsRejected() {
        assertThatThrownBy(() -> decision.finish(ReconcileStatus.DONE, 0))
                .isInstanceOfSatisfying(AccBusinessException.class,
                        e -> assertThat(e.code()).isEqualTo(3007));
        assertThatThrownBy(() -> decision.finish(ReconcileStatus.DIFF, 0))
                .isInstanceOfSatisfying(AccBusinessException.class,
                        e -> assertThat(e.code()).isEqualTo(3007));
    }
}
