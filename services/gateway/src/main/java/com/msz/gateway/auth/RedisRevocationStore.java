package com.msz.gateway.auth;

import com.msz.gateway.redis.GatewayRedisOps;
import reactor.core.publisher.Mono;

import java.time.Duration;

/**
 * Redis 吊销名单(REDIS 存储模式,生产):key = {@code revoked:jti:{jti}},短 TTL。
 * Redis 故障由 GatewayRedisOps 统一映射 GatewayUnavailableException(fail-closed)。
 */
public final class RedisRevocationStore implements RevocationStore {

    private static final String KEY_PREFIX = "revoked:jti:";

    private final GatewayRedisOps redis;

    public RedisRevocationStore(GatewayRedisOps redis) {
        this.redis = redis;
    }

    @Override
    public Mono<Boolean> isRevoked(String jti) {
        if (jti == null) {
            return Mono.just(false);
        }
        return redis.exists(KEY_PREFIX + jti);
    }

    @Override
    public Mono<Boolean> revoke(String jti, Duration ttl) {
        if (jti == null) {
            return Mono.just(true);
        }
        return redis.set(KEY_PREFIX + jti, "1", ttl);
    }
}
