package com.msz.gateway.auth;

import reactor.core.publisher.Mono;

import java.time.Duration;
import java.util.concurrent.ConcurrentHashMap;

/**
 * 内存吊销名单(MEMORY 存储模式,开发兜底,同 acc InMemory 惯例):M1 无 Redis 部署时使用。
 */
public final class InMemoryRevocationStore implements RevocationStore {

    private final ConcurrentHashMap<String, Long> expireAt = new ConcurrentHashMap<>();

    @Override
    public Mono<Boolean> isRevoked(String jti) {
        if (jti == null) {
            return Mono.just(false);
        }
        Long deadline = expireAt.get(jti);
        if (deadline == null) {
            return Mono.just(false);
        }
        if (System.currentTimeMillis() >= deadline) {
            expireAt.remove(jti);
            return Mono.just(false);
        }
        return Mono.just(true);
    }

    @Override
    public Mono<Boolean> revoke(String jti, Duration ttl) {
        if (jti != null) {
            expireAt.put(jti, System.currentTimeMillis() + ttl.toMillis());
        }
        return Mono.just(true);
    }
}
