package com.msz.acc.controller.dto;

import java.time.Instant;

/**
 * 账户视图（/acc/me 与 internal getAccount 共用）：敏感字段脱敏输出。
 */
public record AccountView(String accountId, String role, String realNameStatus, String walletStatus,
                          String mobile, String realName, Instant createdAt) {
}
