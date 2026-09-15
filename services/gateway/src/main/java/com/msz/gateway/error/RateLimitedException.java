package com.msz.gateway.error;

/**
 * 网关级限流超限 → 429 + code 2004。
 */
public final class RateLimitedException extends RuntimeException {

    public RateLimitedException() {
        super("网关级限流超限");
    }
}
