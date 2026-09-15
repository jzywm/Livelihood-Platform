package com.msz.gateway.ratelimit;

import reactor.core.publisher.Mono;

import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * 内存限流器(MEMORY 存储模式,开发兜底,同 acc InMemory 惯例):固定窗口计数。
 * 每个 key 独立窗口;窗口过期自动重置。
 *
 * <p>读改写用 {@link ConcurrentHashMap#compute} 原子化(审查 I11):并发下不丢更新、计数不回退。</p>
 */
public final class InMemoryRateLimiter implements RateLimiter {

    private static final class Window {
        final long startMillis;
        final int count;

        Window(long startMillis, int count) {
            this.startMillis = startMillis;
            this.count = count;
        }
    }

    private final ConcurrentHashMap<String, Window> buckets = new ConcurrentHashMap<>();

    @Override
    public Mono<Boolean> tryAcquire(String key, int capacity, long windowSeconds) {
        long windowMillis = windowSeconds * 1000;
        long now = System.currentTimeMillis();
        AtomicBoolean admitted = new AtomicBoolean(false);

        buckets.compute(key, (k, window) -> {
            if (window == null || now - window.startMillis >= windowMillis) {
                admitted.set(true);
                return new Window(now, 1);
            }
            if (window.count < capacity) {
                admitted.set(true);
                return new Window(window.startMillis, window.count + 1);
            }
            return window; // 超限:窗口保持不变
        });
        return Mono.just(admitted.get());
    }
}
