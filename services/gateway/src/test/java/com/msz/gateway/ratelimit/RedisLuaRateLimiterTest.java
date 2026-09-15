package com.msz.gateway.ratelimit;

import com.msz.gateway.redis.GatewayRedisOps;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;
import reactor.core.publisher.Mono;
import reactor.test.StepVerifier;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.anyList;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.when;

/**
 * 任务 5.1 验证:RedisLuaRateLimiter——Lua 求值 1=放行/0=拒绝,
 * args = [窗口毫秒, 容量],key 原样透传。
 */
class RedisLuaRateLimiterTest {

    private static final String SCRIPT = "return 1";

    @Test
    void passesArgsAsWindowMillisAndCapacity() {
        GatewayRedisOps ops = Mockito.mock(GatewayRedisOps.class);
        when(ops.evalLong(eq(SCRIPT), eq(List.of("rl:ip:1.2.3.4")),
                eq(List.of("1000", "200")))).thenReturn(Mono.just(1L));
        RedisLuaRateLimiter limiter = new RedisLuaRateLimiter(ops, SCRIPT);

        StepVerifier.create(limiter.tryAcquire("rl:ip:1.2.3.4", 200, 1))
                .expectNext(true)
                .verifyComplete();
    }

    @Test
    void deniesWhenLuaReturnsZero() {
        GatewayRedisOps ops = Mockito.mock(GatewayRedisOps.class);
        when(ops.evalLong(anyString(), anyList(), anyList())).thenReturn(Mono.just(0L));
        RedisLuaRateLimiter limiter = new RedisLuaRateLimiter(ops, SCRIPT);

        StepVerifier.create(limiter.tryAcquire("k", 10, 60))
                .expectNext(false)
                .verifyComplete();
    }
}
