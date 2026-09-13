package com.msz.common.idgen;

import java.util.concurrent.atomic.AtomicLong;

/**
 * {@link IdGenMetrics} 默认内存实现（进程内计数，供最小版使用）。
 */
public final class DefaultIdGenMetrics implements IdGenMetrics {

    private final AtomicLong clockRollbackTotal = new AtomicLong();
    private final AtomicLong segmentIssueTotal = new AtomicLong();
    private final AtomicLong segmentFailureTotal = new AtomicLong();
    private volatile String mode = "snowflake";

    @Override
    public void incrementClockRollback() {
        clockRollbackTotal.incrementAndGet();
    }

    @Override
    public long clockRollbackTotal() {
        return clockRollbackTotal.get();
    }

    @Override
    public void recordSegmentIssue() {
        segmentIssueTotal.incrementAndGet();
    }

    @Override
    public void recordSegmentFailure() {
        segmentFailureTotal.incrementAndGet();
    }

    @Override
    public void mode(String mode) {
        this.mode = mode;
    }

    @Override
    public String mode() {
        return mode;
    }
}
