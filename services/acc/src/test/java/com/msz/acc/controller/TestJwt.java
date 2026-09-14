package com.msz.acc.controller;

import com.msz.acc.infrastructure.auth.JwtCodec;

import java.util.Map;

/**
 * 契约测试 JWT 工具：按 AccProperties 默认 {@code acc.jwt-secret} 签发六方角色 token。
 */
final class TestJwt {

    static final String SECRET = "acc-jwt-test-secret-0123456789abcdef";

    private TestJwt() {
    }

    static String token(String accountId, String role, boolean mfa) {
        return new JwtCodec().sign(Map.of(
                "sub", accountId,
                "role", role,
                "jti", "jti-" + accountId + "-" + role,
                "mfa", mfa), SECRET, 3600);
    }

    static String bearer(String accountId, String role, boolean mfa) {
        return "Bearer " + token(accountId, role, mfa);
    }
}
