package com.msz.gateway.auth;

import reactor.core.publisher.Mono;

import java.time.Duration;

/**
 * JWT 吊销名单端口(F2):网关只查询,吊销由签发侧(登录/登出流程)写入。
 * Redis 实现故障时抛 GatewayUnavailableException(fail-closed,503/5003),不静默放行。
 */
public interface RevocationStore {

    Mono<Boolean> isRevoked(String jti);

    Mono<Boolean> revoke(String jti, Duration ttl);
}
