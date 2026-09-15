package com.msz.gateway.redis;

import reactor.core.publisher.Mono;

import java.time.Duration;
import java.util.List;

/**
 * 网关 Redis 操作端口(仅网关所需的子集):Lua 脚本求值 / get / set(TTL)/ exists / ping。
 * 生产实现(Lettuce)将 Redis 故障统一映射 GatewayUnavailableException(fail-closed 503/5003)。
 */
public interface GatewayRedisOps {

    Mono<Long> evalLong(String script, List<String> keys, List<String> args);

    Mono<String> get(String key);

    Mono<Boolean> set(String key, String value, Duration ttl);

    Mono<Boolean> exists(String key);

    Mono<String> ping();
}
