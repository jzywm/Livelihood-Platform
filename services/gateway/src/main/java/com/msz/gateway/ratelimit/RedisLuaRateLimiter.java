package com.msz.gateway.ratelimit;

import com.msz.gateway.redis.GatewayRedisOps;
import reactor.core.publisher.Mono;

import java.util.List;

/**
 * Redis+Lua 限流器(REDIS 存储模式,生产):INCR + PEXPIRE 原子固定窗口计数。
 * Lua 返回 1 = 放行,0 = 超限拒绝;Redis 故障由 GatewayRedisOps 统一映射
 * GatewayUnavailableException(fail-closed 503/5003)。
 */
public final class RedisLuaRateLimiter implements RateLimiter {

    private final GatewayRedisOps redis;
    private final String script;

    public RedisLuaRateLimiter(GatewayRedisOps redis, String script) {
        this.redis = redis;
        this.script = script;
    }

    @Override
    public Mono<Boolean> tryAcquire(String key, int capacity, long windowSeconds) {
        return redis.evalLong(script, List.of(key),
                        List.of(String.valueOf(windowSeconds * 1000), String.valueOf(capacity)))
                .map(result -> result == 1L);
    }
}
