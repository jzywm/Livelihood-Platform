package com.msz.acc.infrastructure.auth;

/**
 * 访问拒绝异常（S5）：角色不足（监管二次鉴权）/内部 Token 校验失败统一抛出，
 * 由 GlobalExceptionHandler 映射为 403 + code 2002。
 */
public class AccessDeniedException extends RuntimeException {

    public AccessDeniedException(String message) {
        super(message);
    }
}
