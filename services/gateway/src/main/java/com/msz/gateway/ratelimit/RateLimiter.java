package com.msz.gateway.ratelimit;

import reactor.core.publisher.Mono;

/**
 * 限流端口:固定窗口计数(Redis+Lua 令牌桶的原子形态,ADR-5 口径)。
 *
 * @param key          桶 key(三级:rl:ip / rl:acc / rl:api)
 * @param capacity     窗口内允许次数
 * @param windowSeconds 窗口秒
 */
public interface RateLimiter {

    Mono<Boolean> tryAcquire(String key, int capacity, long windowSeconds);
}
