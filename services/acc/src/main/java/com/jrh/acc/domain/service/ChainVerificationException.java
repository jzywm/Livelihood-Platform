package com.msz.acc.domain.service;

/**
 * 哈希链校验失败异常（防篡改检出让 R-04）。
 */
public final class ChainVerificationException extends RuntimeException {

    private final int index;

    public ChainVerificationException(int index, String message) {
        super(message);
        this.index = index;
    }

    /** 断链位置（链中下标，0 起）。 */
    public int index() {
        return index;
    }
}
