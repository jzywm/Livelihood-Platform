package com.msz.common.idgen;

import com.msz.common.redis.StringRedisOps;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * infra-idgen 三档时钟回拨 + workerId 租约单测 · 对应 test-plan.md UT-F03~F07。
 * TimeSource / SegmentSource / IdGenAlert / IdGenMetrics / StringRedisOps 全部使用测试内 fake。
 */
class SnowflakeIdGeneratorTest {

    private static final long BASE = 1_767_225_600_000L; // CUSTOM_EPOCH = 2026-01-01T00:00:00Z

    // ---- fakes ----

    /** 可控时钟：每次 millis() 返回当前值并可选地前进 step 毫秒。 */
    static final class StubClock implements TimeSource {
        long now;
        long step;

        StubClock(long now) {
            this.now = now;
        }

        StubClock step(long step) {
            this.step = step;
            return this;
        }

        @Override
        public long millis() {
            long v = now;
            now += step;
            return v;
        }
    }

    /** 可控号段源：默认发 [start, end]，可注入 failure 模拟号段不可用。 */
    static final class StubSegmentSource implements SegmentSource {
        long start = 1000L;
        long end = 1_000_000L;
        RuntimeException failure;

        @Override
        public long[] nextRange(String bizTag) {
            if (failure != null) {
                throw failure;
            }
            return new long[]{start, end};
        }
    }

    static final class RecordingAlert implements IdGenAlert {
        final List<Integer> levels = new ArrayList<>();
        final List<String> messages = new ArrayList<>();

        @Override
        public void alert(int level, String message) {
            levels.add(level);
            messages.add(message);
        }

        boolean alerted(int level) {
            return levels.contains(level);
        }
    }

    static final class StubMetrics implements IdGenMetrics {
        long clockRollbackTotal;
        long segmentIssueTotal;
        long segmentFailureTotal;
        String mode = "snowflake";

        @Override
        public void incrementClockRollback() {
            clockRollbackTotal++;
        }

        @Override
        public long clockRollbackTotal() {
            return clockRollbackTotal;
        }

        @Override
        public void recordSegmentIssue() {
            segmentIssueTotal++;
        }

        @Override
        public void recordSegmentFailure() {
            segmentFailureTotal++;
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

    static final class FakeStringRedisOps implements StringRedisOps {
        final Map<String, String> store = new HashMap<>();
        final Map<String, Long> ttl = new HashMap<>();

        @Override
        public Long incr(String key) {
            long v = store.containsKey(key) ? Long.parseLong(store.get(key)) + 1 : 1L;
            store.put(key, String.valueOf(v));
            return v;
        }

        @Override
        public Boolean expire(String key, long seconds) {
            if (!store.containsKey(key)) {
                return false;
            }
            ttl.put(key, seconds);
            return true;
        }

        @Override
        public String get(String key) {
            return store.get(key);
        }

        @Override
        public Boolean setNx(String key, String value, long ttlSeconds) {
            if (store.containsKey(key)) {
                return false;
            }
            store.put(key, value);
            ttl.put(key, ttlSeconds);
            return true;
        }

        @Override
        public Object eval(String script, List<String> keys, List<String> args) {
            return null;
        }
    }

    // ---- tests ----

    @Test
    @DisplayName("UT-F03: 雪花 ID 批量 100k 无重复")
    void ut_f03_snowflake_100k_unique() {
        StubClock clock = new StubClock(BASE).step(1L);
        SnowflakeIdGenerator gen = new SnowflakeIdGenerator(1, clock, new StubSegmentSource(),
                new RecordingAlert(), new StubMetrics(), new SnowflakeIdGenerator.Config(5000));
        Set<Long> ids = new HashSet<>();
        for (int i = 0; i < 100_000; i++) {
            ids.add(gen.nextId());
        }
        assertThat(ids).hasSize(100_000);
        assertThat(gen.mode()).isEqualTo("snowflake");
    }

    @Test
    @DisplayName("UT-F04: 时钟回拨 L1(3s≤W=5s) 退避等待后继续发号，无失败")
    void ut_f04_l1_rollback_waits_then_continues() {
        StubClock clock = new StubClock(BASE);
        StubMetrics metrics = new StubMetrics();
        SnowflakeIdGenerator gen = new SnowflakeIdGenerator(1, clock, new StubSegmentSource(),
                new RecordingAlert(), metrics, new SnowflakeIdGenerator.Config(5000));
        gen.nextId(); // lastTimestamp = BASE
        clock.now = BASE - 3000; // 回拨 3s
        clock.step = 1000;       // 每次 millis() 前进 1s，3 次追平
        long id = gen.nextId();
        assertThat(id).isPositive();
        assertThat(gen.mode()).isEqualTo("snowflake");
        assertThat(metrics.clockRollbackTotal()).isEqualTo(1L);
    }

    @Test
    @DisplayName("UT-F05: 时钟回拨 L2(10s>W) 切号段，ID 唯一，mode()==segment")
    void ut_f05_l2_rollback_switches_to_segment() {
        StubClock clock = new StubClock(BASE);
        StubSegmentSource segment = new StubSegmentSource();
        SnowflakeIdGenerator gen = new SnowflakeIdGenerator(1, clock, segment,
                new RecordingAlert(), new StubMetrics(), new SnowflakeIdGenerator.Config(5000));
        gen.nextId(); // lastTimestamp = BASE
        clock.now = BASE - 10_000; // 回拨 10s > W
        Set<Long> ids = new HashSet<>();
        for (int i = 0; i < 100; i++) {
            ids.add(gen.nextId());
        }
        assertThat(gen.mode()).isEqualTo("segment");
        assertThat(ids).hasSize(100);
    }

    @Test
    @DisplayName("UT-F06: 时钟回拨 L3 号段不可用 → IdGenException + P0 alert(0)")
    void ut_f06_l3_segment_unavailable_fails_fast() {
        StubClock clock = new StubClock(BASE);
        StubSegmentSource segment = new StubSegmentSource();
        segment.failure = new IllegalStateException("segment unavailable");
        RecordingAlert alert = new RecordingAlert();
        SnowflakeIdGenerator gen = new SnowflakeIdGenerator(1, clock, segment,
                alert, new StubMetrics(), new SnowflakeIdGenerator.Config(5000));
        gen.nextId(); // lastTimestamp = BASE
        clock.now = BASE - 10_000; // 触发 L2 → 切号段 → 号段抛异常 → L3
        assertThatThrownBy(gen::nextId).isInstanceOf(IdGenException.class);
        assertThat(alert.alerted(0)).isTrue();
    }

    @Test
    @DisplayName("UT-F07: workerId 撞车（fake ops 预占）→ IdGenException + P0 alert(0)")
    void ut_f07_worker_id_collision_rejected() {
        FakeStringRedisOps ops = new FakeStringRedisOps();
        ops.store.put("idgen:worker:1", "other-instance"); // 预占租约
        RecordingAlert alert = new RecordingAlert();
        WorkerIdRegistry registry = new WorkerIdRegistry(ops, alert);
        assertThatThrownBy(() -> registry.acquire("my-instance")).isInstanceOf(IdGenException.class);
        assertThat(alert.alerted(0)).isTrue();
    }

    @Test
    @DisplayName("UT-F07: workerId 正常 acquire 落租约 + renew 续租")
    void ut_f07_worker_id_acquire_and_renew() {
        FakeStringRedisOps ops = new FakeStringRedisOps();
        WorkerIdRegistry registry = new WorkerIdRegistry(ops, new RecordingAlert());
        long id = registry.acquire("my-instance");
        assertThat(id).isEqualTo(1L);
        assertThat(ops.get("idgen:worker:1")).isEqualTo("my-instance");
        registry.renew();
        assertThat(ops.ttl.get("idgen:worker:1")).isEqualTo(60L);
    }
}
