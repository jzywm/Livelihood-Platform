package com.msz.common.api;

import java.time.Instant;

/**
 * 平台统一响应包络：所有接口成功/失败均返回此结构。
 * 业务码分段：0 成功 / 1xxx 参数校验 / 2xxx 鉴权权限 / 3xxx 业务规则 / 4xxx 第三方依赖 / 5xxx 系统。
 */
public record Envelope<T>(int code, String message, T data, String traceId, String timestamp) {

    /** 成功包络：code=0，data 为业务数据。 */
    public static <T> Envelope<T> ok(T data, String traceId) {
        return new Envelope<>(ErrorCode.OK, ErrorCode.message(ErrorCode.OK), data, traceId, Instant.now().toString());
    }

    /** 失败包络：data=null。 */
    public static <T> Envelope<T> fail(int code, String message, String traceId) {
        return new Envelope<>(code, message, null, traceId, Instant.now().toString());
    }
}
