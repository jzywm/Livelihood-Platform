package com.msz.acc.application;

/**
 * 实名回调结果：bizId + 迁移后状态 + accountId（建户/幂等回填，未建户为 null）。
 */
public record CallbackResult(String bizId, String status, Long accountId) {
}
