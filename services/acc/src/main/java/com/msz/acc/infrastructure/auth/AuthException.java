package com.msz.acc.infrastructure.auth;

/**
 * 鉴权异常（2.3）：JWT 验签/过期/格式非法统一抛出，不向调用方泄露具体失败原因。
 * {@link AuthFilter} 捕获后统一映射为 401 + code 2001。
 */
public class AuthException extends RuntimeException {

    public AuthException(String message) {
        super(message);
    }

    public AuthException(String message, Throwable cause) {
        super(message, cause);
    }
}
