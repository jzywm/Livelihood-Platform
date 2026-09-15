package com.msz.gateway.ratelimit;

import org.junit.jupiter.api.Test;
import reactor.test.StepVerifier;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 任务 5.1 验证:InMemoryRateLimiter(MEMORY 模式兜底)——固定窗口计数:
 * 容量内放行、超限拒绝、窗口回填后可再放行、key 之间互不影响。
 */
class InMemoryRateLimiterTest {

    private final InMemoryRateLimiter limiter = new InMemoryRateLimiter();

    @Test
    void allowsWithinCapacityAndRejectsBeyond() {
        StepVerifier.create(limiter.tryAcquire("k1", 2, 60)).expectNext(true).verifyComplete();
        StepVerifier.create(limiter.tryAcquire("k1", 2, 60)).expectNext(true).verifyComplete();
        StepVerifier.create(limiter.tryAcquire("k1", 2, 60)).expectNext(false).verifyComplete();
    }

    @Test
    void refillsAfterWindow() {
        StepVerifier.create(limiter.tryAcquire("k2", 1, 1)).expectNext(true).verifyComplete();
        StepVerifier.create(limiter.tryAcquire("k2", 1, 1)).expectNext(false).verifyComplete();
        sleepQuietly(1100);
        StepVerifier.create(limiter.tryAcquire("k2", 1, 1)).expectNext(true).verifyComplete();
    }

    @Test
    void keysAreIsolated() {
        StepVerifier.create(limiter.tryAcquire("ka", 1, 60)).expectNext(true).verifyComplete();
        StepVerifier.create(limiter.tryAcquire("kb", 1, 60)).expectNext(true).verifyComplete();
    }

    @Test
    void admitsExactlyCapacityUnderConcurrency() throws Exception {
        int capacity = 50;
        int threads = 16;
        int attemptsPerThread = 50;
        java.util.concurrent.atomic.AtomicInteger admitted = new java.util.concurrent.atomic.AtomicInteger();
        java.util.concurrent.CountDownLatch start = new java.util.concurrent.CountDownLatch(1);
        java.util.concurrent.ExecutorService pool = java.util.concurrent.Executors.newFixedThreadPool(threads);

        for (int t = 0; t < threads; t++) {
            pool.submit(() -> {
                start.await();
                for (int i = 0; i < attemptsPerThread; i++) {
                    if (Boolean.TRUE.equals(limiter.tryAcquire("hot-key", capacity, 60).block())) {
                        admitted.incrementAndGet();
                    }
                }
                return null;
            });
        }
        start.countDown();
        pool.shutdown();
        assertThat(pool.awaitTermination(30, java.util.concurrent.TimeUnit.SECONDS)).isTrue();

        // 原子化后放行次数恰好等于容量(读改写非原子时会超发)
        assertThat(admitted.get()).isEqualTo(capacity);
    }

    private void sleepQuietly(long millis) {
        try {
            Thread.sleep(millis);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new IllegalStateException(e);
        }
    }
}
