package com.msz.gateway.error;

/**
 * 鉴权失败(JWT 验签失败/过期/吊销/缺失)→ 401 + code 2001。
 * 不携带失败细节(不泄露验签失败原因,SEC-07 口径)。
 */
public final class AuthException extends RuntimeException {

    public AuthException(String message) {
        super(message);
    }

    public AuthException(String message, Throwable cause) {
        super(message, cause);
    }
}
