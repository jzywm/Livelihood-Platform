package com.msz.gateway.redis;

import com.msz.gateway.error.GatewayUnavailableException;
import org.springframework.data.redis.core.ReactiveRedisCallback;
import org.springframework.data.redis.core.ReactiveStringRedisTemplate;
import org.springframework.data.redis.core.script.DefaultRedisScript;
import reactor.core.publisher.Mono;

import java.time.Duration;
import java.util.List;

/**
 * GatewayRedisOps 的 Lettuce 实现(REDIS 存储模式,生产):
 * 全部代理到 ReactiveStringRedisTemplate;Redis 故障统一映射
 * {@link GatewayUnavailableException}(fail-closed:吊销/限流依赖不可用时快速失败,不静默放行)。
 */
public final class LettuceGatewayRedisOps implements GatewayRedisOps {

    private final ReactiveStringRedisTemplate template;

    public LettuceGatewayRedisOps(ReactiveStringRedisTemplate template) {
        this.template = template;
    }

    @Override
    public Mono<Long> evalLong(String script, List<String> keys, List<String> args) {
        return template.execute(new DefaultRedisScript<>(script, Long.class), keys, args)
                .single()
                .onErrorMap(this::wrap);
    }

    @Override
    public Mono<String> get(String key) {
        return template.opsForValue().get(key).onErrorMap(this::wrap);
    }

    @Override
    public Mono<Boolean> set(String key, String value, Duration ttl) {
        return template.opsForValue().set(key, value, ttl).onErrorMap(this::wrap);
    }

    @Override
    public Mono<Boolean> exists(String key) {
        return template.hasKey(key).onErrorMap(this::wrap);
    }

    @Override
    public Mono<String> ping() {
        ReactiveRedisCallback<String> callback = connection -> connection.ping();
        return template.execute(callback)
                .next()
                .onErrorMap(this::wrap);
    }

    private Throwable wrap(Throwable t) {
        if (t instanceof GatewayUnavailableException gue) {
            return gue;
        }
        return new GatewayUnavailableException("Redis 不可用", t);
    }
}
