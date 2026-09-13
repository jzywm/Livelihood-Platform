package com.msz.acc.infrastructure.auth;

/**
 * 鉴权上下文（2.3）：经 {@link AuthFilter} 解析 JWT claims 后透传，写入
 * {@code request.setAttribute("authContext", ...)} 供后续越权/角色校验使用。
 *
 * @param accountId 账号 ID（JWT sub）
 * @param role      六方角色（CONSUMER/MERCHANT/SUPPLIER/WORKER/REGULATOR/OPERATOR）
 * @param jti       JWT 唯一 ID（吊销检查用）
 */
public record AuthContext(String accountId, String role, String jti) {
}
