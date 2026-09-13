package com.msz.common.idgen;

/**
 * 发号指标计数（最小实现）：时钟回拨次数、号段发号/失败次数、当前模式。
 */
public interface IdGenMetrics {

    void incrementClockRollback();

    long clockRollbackTotal();

    void recordSegmentIssue();

    void recordSegmentFailure();

    void mode(String mode);

    String mode();
}
