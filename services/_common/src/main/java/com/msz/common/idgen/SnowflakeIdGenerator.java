package com.msz.common.idgen;

import java.util.Objects;

/**
 * 雪花 + 号段双轨 ID 生成器（时钟回拨三档）。
 *
 * <p>雪花公式：{@code (epochMs - CUSTOM_EPOCH) << 22 | workerId << 12 | sequence}；
 * CUSTOM_EPOCH = 2026-01-01T00:00:00Z；同毫秒 sequence 0..4095，超 4095 自旋到下毫秒。</p>
 *
 * <p>时钟回拨三档（W 可配，默认 5000ms）：</p>
 * <ul>
 *   <li>L1 回拨≤W：自旋等待（sleep 1ms 循环）到时钟追平再发号；等待超 W 预算仍不回正 → 进 L2。</li>
 *   <li>L2 回拨&gt;W：切号段模式（segment 轨，ID 仍唯一，无时间戳依赖），雪花挂起，mode() 返回 "segment"。</li>
 *   <li>L3 号段失败/不可用：抛 {@link IdGenException}（fast-fail）+ alert(0, …) P0。</li>
 * </ul>
 */
public final class SnowflakeIdGenerator implements IdGenerator {

    /** 自定义纪元：2026-01-01T00:00:00Z。 */
    public static final long CUSTOM_EPOCH = 1_767_225_600_000L;

    private static final long SEQUENCE_BITS = 12L;
    private static final long WORKER_BITS = 10L;
    private static final long SEQUENCE_MASK = (1L << SEQUENCE_BITS) - 1L; // 4095
    private static final long MAX_WORKER_ID = (1L << WORKER_BITS) - 1L;   // 1023
    private static final long WORKER_SHIFT = SEQUENCE_BITS;               // 12
    private static final long TIMESTAMP_SHIFT = SEQUENCE_BITS + WORKER_BITS; // 22
    private static final long DEFAULT_WAIT_BUDGET_MS = 5000L;
    private static final String MODE_SNOWFLAKE = "snowflake";
    private static final String MODE_SEGMENT = "segment";
    private static final String DEFAULT_BIZ_TAG = "default";

    private final long workerId;
    private final TimeSource clock;
    private final SegmentSource segmentSource;
    private final IdGenAlert alert;
    private final IdGenMetrics metrics;
    private final long waitBudgetMs;

    // 雪花轨状态
    private long lastTimestamp = -1L;
    private long sequence = 0L;

    // 号段轨状态
    private volatile String mode = MODE_SNOWFLAKE;
    private boolean segmentLoaded = false;
    private long segmentStart = 0L;
    private long segmentEnd = -1L;
    private long segmentCursor = 0L;

    public SnowflakeIdGenerator(long workerId, TimeSource clock, SegmentSource segmentSource,
                                IdGenAlert alert, IdGenMetrics metrics, Config cfg) {
        if (workerId < 0 || workerId > MAX_WORKER_ID) {
            throw new IllegalArgumentException(
                    "workerId 必须在 [0, " + MAX_WORKER_ID + "] 区间，实际: " + workerId);
        }
        this.workerId = workerId;
        this.clock = Objects.requireNonNull(clock, "clock");
        this.segmentSource = Objects.requireNonNull(segmentSource, "segmentSource");
        this.alert = Objects.requireNonNull(alert, "alert");
        this.metrics = Objects.requireNonNull(metrics, "metrics");
        this.waitBudgetMs = cfg == null ? DEFAULT_WAIT_BUDGET_MS : cfg.clockRollbackBudgetMs();
        this.metrics.mode(MODE_SNOWFLAKE);
    }

    @Override
    public long nextId() {
        return nextId(DEFAULT_BIZ_TAG);
    }

    @Override
    public synchronized long nextId(String bizTag) {
        if (MODE_SEGMENT.equals(mode)) {
            return nextSegmentId(bizTag);
        }
        return nextSnowflakeId(bizTag);
    }

    @Override
    public String mode() {
        return mode;
    }

    private long nextSnowflakeId(String bizTag) {
        long last = lastTimestamp;
        long now = clock.millis();
        if (now < last) {
            long rollback = last - now;
            metrics.incrementClockRollback();
            if (rollback > waitBudgetMs) {
                return switchToSegment(bizTag);
            }
            // L1：自旋等待时钟追平；等待超 W 预算仍不回正 → L2。
            long waitStart = now;
            long cur = now;
            while (cur < last) {
                if (cur - waitStart >= waitBudgetMs) {
                    return switchToSegment(bizTag);
                }
                sleep(1L);
                cur = clock.millis();
            }
            now = cur;
        }

        if (now == last) {
            sequence = (sequence + 1) & SEQUENCE_MASK;
            if (sequence == 0L) {
                now = awaitNextMillis(last);
            }
        } else {
            sequence = 0L;
        }
        lastTimestamp = now;
        return ((now - CUSTOM_EPOCH) << TIMESTAMP_SHIFT)
                | (workerId << WORKER_SHIFT)
                | sequence;
    }

    private long awaitNextMillis(long last) {
        long now = clock.millis();
        while (now <= last) {
            sleep(1L);
            now = clock.millis();
        }
        return now;
    }

    private long switchToSegment(String bizTag) {
        mode = MODE_SEGMENT;
        metrics.mode(MODE_SEGMENT);
        alert.alert(2, "雪花时钟回拨超过预算（W=" + waitBudgetMs + "ms），切号段模式兜底");
        return nextSegmentId(bizTag);
    }

    private long nextSegmentId(String bizTag) {
        if (!segmentLoaded || segmentCursor > segmentEnd) {
            loadSegment(bizTag);
        }
        long id = segmentCursor++;
        metrics.recordSegmentIssue();
        return id;
    }

    private void loadSegment(String bizTag) {
        long[] range;
        try {
            range = segmentSource.nextRange(bizTag);
        } catch (RuntimeException e) {
            failFast(bizTag, e);
            return;
        }
        if (range == null || range.length < 2 || range[1] < range[0]) {
            failFast(bizTag, null);
            return;
        }
        segmentStart = range[0];
        segmentEnd = range[1];
        segmentCursor = segmentStart;
        segmentLoaded = true;
    }

    private void failFast(String bizTag, Throwable cause) {
        metrics.recordSegmentFailure();
        alert.alert(0, "号段发号不可用（时钟回拨 L3），拒绝发号，bizTag=" + bizTag);
        throw new IdGenException("号段发号不可用，拒绝发号", cause);
    }

    private static void sleep(long millis) {
        try {
            Thread.sleep(millis);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new IdGenException("发号等待被中断", e);
        }
    }

    /** 时钟回拨预算 W（毫秒）配置。 */
    public static final class Config {
        public static final long DEFAULT_CLOCK_ROLLBACK_BUDGET_MS = 5000L;

        private final long clockRollbackBudgetMs;

        public Config() {
            this(DEFAULT_CLOCK_ROLLBACK_BUDGET_MS);
        }

        public Config(long clockRollbackBudgetMs) {
            if (clockRollbackBudgetMs <= 0) {
                throw new IllegalArgumentException(
                        "clockRollbackBudgetMs 必须为正，实际: " + clockRollbackBudgetMs);
            }
            this.clockRollbackBudgetMs = clockRollbackBudgetMs;
        }

        public long clockRollbackBudgetMs() {
            return clockRollbackBudgetMs;
        }
    }
}
