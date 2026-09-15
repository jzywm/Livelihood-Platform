package com.msz.gateway.error;

/**
 * 网关依赖不可用(Redis 吊销/限流存储 fail-closed)→ 503 + code 5003。
 * 不静默放行:吊销检查与限流计数依赖 Redis,Redis 故障时快速失败而非跳过安全校验。
 */
public final class GatewayUnavailableException extends RuntimeException {

    public GatewayUnavailableException(String message) {
        super(message);
    }

    public GatewayUnavailableException(String message, Throwable cause) {
        super(message, cause);
    }
}
