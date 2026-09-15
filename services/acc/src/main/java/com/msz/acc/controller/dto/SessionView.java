package com.msz.acc.controller.dto;

/**
 * 会话凭据视图（openapi `SessionView`，PDD v1.18 §8.4.1）。
 *
 * <p><b>长 token（refresh）刻意不在本视图内</b>——它只经 `Set-Cookie` 下发，进不了响应体，
 * 也就进不了前端任何持久化（localStorage）与日志采集面。</p>
 *
 * @param accessToken 短 token（HS256 JWT，15 分钟）
 * @param tokenType   固定 {@code Bearer}
 * @param expiresIn   短 token 剩余有效期（秒），固定 900
 * @param accountId   账户 ID（{@code acc_<account_id>}，与 /acc/me 口径一致）
 * @param role        六方角色
 * @param mfa         是否已完成 MFA（敏感操作二次鉴权标记）
 */
public record SessionView(String accessToken, String tokenType, long expiresIn, String accountId, String role,
                          boolean mfa) {

    /** 固定 Bearer（客户端拼 `Authorization: Bearer <accessToken>`）。 */
    public static final String BEARER = "Bearer";
}
