package com.msz.acc.application;

/**
 * 注册结果：幂等命中时仅回填 accountId + idempotent=true；首次发起时携带 bizId/authorizeUrl/REALNAMING。
 */
public record RegisterResult(Long accountId, String bizId, String authorizeUrl, String realNameStatus,
                             boolean idempotent) {
}
