package com.msz.acc.repository;

import org.apache.ibatis.session.SqlSession;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.Callable;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * IdempotencyGuardTest（UT-C07/D04 口径）：同 key 重复返回首次结果、不同 key 各自执行、
 * 并发 20 线程同 key 仅 action 执行一次。
 */
class IdempotencyGuardTest extends AbstractDbTest {

    @Test
    @DisplayName("UT-C07: 同 key 两次 → 第二次返回首次 payload，action 仅执行一次")
    void sameKeyTwiceReturnsFirstPayload() {
        AtomicInteger executions = new AtomicInteger();
        try (SqlSession s = openSession()) {
            IdempotencyGuard guard = new IdempotencyGuard(s.getMapper(IdempotencyRecordMapper.class), () -> "fallback");

            String first = guard.execute("scene-a", "key-twice", () -> {
                executions.incrementAndGet();
                return "first-payload";
            });
            String second = guard.execute("scene-a", "key-twice", () -> {
                executions.incrementAndGet();
                return "second-payload";
            });

            assertThat(first).isEqualTo("first-payload");
            assertThat(second).as("重复请求返回首次结果（3008 幂等口径）").isEqualTo("first-payload");
            assertThat(executions.get()).as("action 仅执行一次").isEqualTo(1);
        }
    }

    @Test
    @DisplayName("UT-C07: 不同 key 各自执行")
    void differentKeysExecuteIndependently() {
        AtomicInteger executions = new AtomicInteger();
        try (SqlSession s = openSession()) {
            IdempotencyGuard guard = new IdempotencyGuard(s.getMapper(IdempotencyRecordMapper.class), () -> "fallback");

            String r1 = guard.execute("scene-b", "key-1", () -> {
                executions.incrementAndGet();
                return "result-1";
            });
            String r2 = guard.execute("scene-b", "key-2", () -> {
                executions.incrementAndGet();
                return "result-2";
            });

            assertThat(r1).isEqualTo("result-1");
            assertThat(r2).isEqualTo("result-2");
            assertThat(executions.get()).isEqualTo(2);
        }
    }

    @Test
    @DisplayName("UT-D04: 并发 20 线程同 key → action 恰执行 1 次、其余拿到首次结果")
    void concurrentSameKeyExecutesOnce() throws Exception {
        AtomicInteger executions = new AtomicInteger();
        String scene = "scene-c";
        String key = "concurrent-key";
        ExecutorService pool = Executors.newFixedThreadPool(20);
        try {
            List<Callable<String>> tasks = new ArrayList<>();
            for (int i = 0; i < 20; i++) {
                tasks.add(() -> {
                    try (SqlSession s = openSession()) {
                        IdempotencyGuard guard = new IdempotencyGuard(
                                s.getMapper(IdempotencyRecordMapper.class), () -> "fallback");
                        return guard.execute(scene, key, () -> {
                            executions.incrementAndGet();
                            return "first-result";
                        });
                    }
                });
            }

            List<Future<String>> futures = pool.invokeAll(tasks, 30, TimeUnit.SECONDS);
            List<String> results = new ArrayList<>();
            for (Future<String> future : futures) {
                results.add(future.get());
            }

            assertThat(executions.get()).as("并发同 key 仅执行 action 一次").isEqualTo(1);
            assertThat(results).hasSize(20).containsOnly("first-result");
        } finally {
            pool.shutdownNow();
        }
    }
}
