package com.msz.acc.domain.service;

import com.msz.acc.domain.model.RealNameLevel;
import com.msz.acc.domain.model.RealNameStatus;
import com.msz.acc.domain.support.AccBusinessException;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * 实名状态机单元测试 · 对应 test-plan.md §2.5 A 组：
 * UT-A01 合法迁移 UNREALNAMED→REALNAMING→REALNAMED
 * UT-A02 第三方不可用 REALNAMING→SUSPENDED，SUSPENDED→REALNAMING 重试（R-02 无人工降级路径）
 * UT-A03 非法迁移抛 AccBusinessException(3007)，状态不变
 * UT-A09 NFC 增强 BASE→ENHANCED，重复增强幂等
 */
class RealnameStatusMachineTest {

    private final RealnameStatusMachine machine = new RealnameStatusMachine();

    @Test
    @DisplayName("UT-A01: UNREALNAMED 发起实名 → REALNAMING")
    void ut_a01_startMovesUnrealnamedToRealnaming() {
        assertThat(machine.start(RealNameStatus.UNREALNAMED)).isEqualTo(RealNameStatus.REALNAMING);
    }

    @Test
    @DisplayName("UT-A01: 回调实名通过 REALNAMING → REALNAMED")
    void ut_a01_callbackPassMovesRealnamingToRealnamed() {
        assertThat(machine.onCallbackPass(RealNameStatus.REALNAMING)).isEqualTo(RealNameStatus.REALNAMED);
    }

    @Test
    @DisplayName("UT-A02: 第三方不可用 REALNAMING → SUSPENDED（暂停，不降级 R-02）")
    void ut_a02_suspendMovesRealnamingToSuspended() {
        assertThat(machine.suspend(RealNameStatus.REALNAMING)).isEqualTo(RealNameStatus.SUSPENDED);
    }

    @Test
    @DisplayName("UT-A02: 暂停后重试 SUSPENDED → REALNAMING")
    void ut_a02_retryMovesSuspendedToRealnaming() {
        assertThat(machine.retry(RealNameStatus.SUSPENDED)).isEqualTo(RealNameStatus.REALNAMING);
    }

    @Test
    @DisplayName("UT-A03: 已实名账户不得重新发起实名（3007）")
    void ut_a03_startOnRealnamedIsRejected() {
        assertThatThrownBy(() -> machine.start(RealNameStatus.REALNAMED))
                .isInstanceOfSatisfying(AccBusinessException.class,
                        e -> assertThat(e.code()).isEqualTo(3007));
    }

    @Test
    @DisplayName("UT-A03: SUSPENDED 不得不经 REALNAMING 直达 REALNAMED（3007）")
    void ut_a03_callbackPassOnSuspendedIsRejected() {
        assertThatThrownBy(() -> machine.onCallbackPass(RealNameStatus.SUSPENDED))
                .isInstanceOfSatisfying(AccBusinessException.class,
                        e -> assertThat(e.code()).isEqualTo(3007));
    }

    @Test
    @DisplayName("UT-A03: 未发起不得直接回调通过（3007）")
    void ut_a03_callbackPassOnUnrealnamedIsRejected() {
        assertThatThrownBy(() -> machine.onCallbackPass(RealNameStatus.UNREALNAMED))
                .isInstanceOfSatisfying(AccBusinessException.class,
                        e -> assertThat(e.code()).isEqualTo(3007));
    }

    @Test
    @DisplayName("UT-A09: NFC 增强 BASE → ENHANCED（I-06）")
    void ut_a09_enhanceMovesBaseToEnhanced() {
        assertThat(machine.enhance(RealNameLevel.BASE)).isEqualTo(RealNameLevel.ENHANCED);
    }

    @Test
    @DisplayName("UT-A09: 重复增强幂等 ENHANCED → ENHANCED")
    void ut_a09_enhanceOnEnhancedIsIdempotent() {
        assertThat(machine.enhance(RealNameLevel.ENHANCED)).isEqualTo(RealNameLevel.ENHANCED);
    }
}
