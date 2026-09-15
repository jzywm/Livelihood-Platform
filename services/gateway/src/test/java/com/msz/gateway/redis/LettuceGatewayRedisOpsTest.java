package com.msz.gateway.redis;

import com.msz.gateway.error.GatewayUnavailableException;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;
import org.springframework.data.redis.connection.ReactiveRedisConnection;
import org.springframework.data.redis.core.ReactiveStringRedisTemplate;
import org.springframework.data.redis.core.ReactiveValueOperations;
import org.springframework.data.redis.core.script.DefaultRedisScript;
import org.springframework.data.redis.core.script.RedisScript;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;
import reactor.test.StepVerifier;

import java.time.Duration;
import java.util.List;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyList;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.when;

/**
 * 任务 5.1/5.3 前置:GatewayRedisOps Lettuce 实现——脚本求值/get/set/exists/ping
 * 全部代理到 ReactiveStringRedisTemplate,Redis 故障统一映射 GatewayUnavailableException(fail-closed)。
 */
class LettuceGatewayRedisOpsTest {

    @SuppressWarnings("unchecked")
    private ReactiveStringRedisTemplate template() {
        return Mockito.mock(ReactiveStringRedisTemplate.class);
    }

    @Test
    void evaluatesScriptAsSingleLong() {
        ReactiveStringRedisTemplate template = template();
        when(template.execute(any(RedisScript.class), anyList(), anyList())).thenReturn(Flux.just(1L));
        LettuceGatewayRedisOps ops = new LettuceGatewayRedisOps(template);

        StepVerifier.create(ops.evalLong("return 1", List.of("k"), List.of("a")))
                .expectNext(1L)
                .verifyComplete();
    }

    @Test
    void delegatesGetSetExistsPing() {
        ReactiveStringRedisTemplate template = template();
        ReactiveValueOperations<String, String> valueOps = Mockito.mock(ReactiveValueOperations.class);
        when(template.opsForValue()).thenReturn(valueOps);
        when(valueOps.get("k")).thenReturn(Mono.just("v"));
        when(valueOps.set(eq("k"), eq("v"), eq(Duration.ofSeconds(5)))).thenReturn(Mono.just(true));
        when(template.hasKey("k")).thenReturn(Mono.just(true));
        when(template.execute(any(org.springframework.data.redis.core.ReactiveRedisCallback.class)))
                .thenReturn(Flux.just("PONG"));
        LettuceGatewayRedisOps ops = new LettuceGatewayRedisOps(template);

        StepVerifier.create(ops.get("k")).expectNext("v").verifyComplete();
        StepVerifier.create(ops.set("k", "v", Duration.ofSeconds(5))).expectNext(true).verifyComplete();
        StepVerifier.create(ops.exists("k")).expectNext(true).verifyComplete();
        StepVerifier.create(ops.ping()).expectNext("PONG").verifyComplete();
    }

    @Test
    void mapsRedisErrorsToGatewayUnavailable() {
        ReactiveStringRedisTemplate template = template();
        when(template.execute(any(RedisScript.class), anyList(), anyList()))
                .thenReturn(Flux.error(new RuntimeException("connection refused")));
        LettuceGatewayRedisOps ops = new LettuceGatewayRedisOps(template);

        StepVerifier.create(ops.evalLong("return 1", List.of("k"), List.of("a")))
                .expectError(GatewayUnavailableException.class)
                .verify();
    }
}
