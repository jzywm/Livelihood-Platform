package com.msz.gateway.auth;

import com.msz.gateway.error.GatewayUnavailableException;
import com.msz.gateway.redis.GatewayRedisOps;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;
import reactor.core.publisher.Mono;
import reactor.test.StepVerifier;

import java.time.Duration;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.when;

/**
 * 任务 4.2 验证:RevocationStore——内存实现(开发兜底)与 Redis 实现(生产,fail-closed)。
 */
class RevocationStoreTest {

    @Test
    void inMemoryStoreReturnsFalseUntilRevoked() {
        InMemoryRevocationStore store = new InMemoryRevocationStore();

        StepVerifier.create(store.isRevoked("j-1")).expectNext(false).verifyComplete();
        store.revoke("j-1", Duration.ofMinutes(5)).block();
        StepVerifier.create(store.isRevoked("j-1")).expectNext(true).verifyComplete();
    }

    @Test
    void inMemoryStoreExpiresRevocation() {
        InMemoryRevocationStore store = new InMemoryRevocationStore();

        store.revoke("j-2", Duration.ofMillis(20)).block();
        StepVerifier.create(store.isRevoked("j-2")).expectNext(true).verifyComplete();
        sleepQuietly(50);
        StepVerifier.create(store.isRevoked("j-2")).expectNext(false).verifyComplete();
    }

    @Test
    void inMemoryStoreTreatsNullAsNotRevoked() {
        InMemoryRevocationStore store = new InMemoryRevocationStore();
        StepVerifier.create(store.isRevoked(null)).expectNext(false).verifyComplete();
    }

    @Test
    void redisStoreChecksExistsKeyAndRevokesWithTtl() {
        GatewayRedisOps ops = Mockito.mock(GatewayRedisOps.class);
        when(ops.exists(eq("revoked:jti:j-1"))).thenReturn(Mono.just(true));
        when(ops.set(eq("revoked:jti:j-2"), eq("1"), eq(Duration.ofMinutes(5)))).thenReturn(Mono.just(true));
        RedisRevocationStore store = new RedisRevocationStore(ops);

        StepVerifier.create(store.isRevoked("j-1")).expectNext(true).verifyComplete();
        StepVerifier.create(store.revoke("j-2", Duration.ofMinutes(5))).expectNext(true).verifyComplete();
    }

    @Test
    void redisStorePropagatesGatewayUnavailable() {
        GatewayRedisOps ops = Mockito.mock(GatewayRedisOps.class);
        when(ops.exists(anyString())).thenReturn(Mono.error(new GatewayUnavailableException("down")));
        RedisRevocationStore store = new RedisRevocationStore(ops);

        StepVerifier.create(store.isRevoked("j-1"))
                .expectError(GatewayUnavailableException.class)
                .verify();
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
