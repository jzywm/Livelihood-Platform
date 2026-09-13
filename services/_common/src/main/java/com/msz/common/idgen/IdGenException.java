package com.msz.common.idgen;

/**
 * ID 生成异常：号段不可用（L3）或 workerId 撞车时 fast-fail 抛出。
 */
public class IdGenException extends RuntimeException {

    public IdGenException(String message) {
        super(message);
    }

    public IdGenException(String message, Throwable cause) {
        super(message, cause);
    }
}
