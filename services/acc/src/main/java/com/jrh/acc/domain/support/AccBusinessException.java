package com.msz.acc.domain.support;

/**
 * ACC 领域业务异常，携带平台统一业务码（对齐 services/_common/openapi.yaml 错误码分段）。
 * 领域层只依赖码值，不依赖 _common 模块，避免 M1 骨架未建时产生耦合。
 */
public class AccBusinessException extends RuntimeException {

    private final int code;

    public AccBusinessException(int code, String message) {
        super(message);
        this.code = code;
    }

    /** 平台统一业务码（如 3007 状态不允许该操作 / 1003 枚举或范围非法）。 */
    public int code() {
        return code;
    }
}
