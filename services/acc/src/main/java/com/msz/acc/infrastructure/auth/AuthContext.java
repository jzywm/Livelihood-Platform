package com.msz.acc.infrastructure.auth;

/**
 * 鉴权上下文（2.3，S5 增补 mfa）：经 {@link AuthFilter} 解析 JWT claims 后透传，写入
 * {@code request.setAttribute("authContext", ...)} 供后续越权/角色/MFA 校验使用。
 *
 * @param accountId 账号 ID（JWT sub）
 * @param role      六方角色（CONSUMER/MERCHANT/SUPPLIER/WORKER/REGULATOR/OPERATOR）
 * @param jti       JWT 唯一 ID（吊销检查用）
 * @param mfa       是否已通过 MFA（敏感操作二次鉴权，如流水导出）；缺失默认 false（fail-closed）
 */
public record AuthContext(String accountId, String role, String jti, boolean mfa) {

    /** 兼容构造（无 MFA 信息时 fail-closed）。 */
    public AuthContext(String accountId, String role, String jti) {
        this(accountId, role, jti, false);
    }
}
