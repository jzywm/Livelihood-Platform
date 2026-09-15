package com.msz.acc.controller;

import org.springframework.test.web.servlet.request.RequestPostProcessor;

/**
 * 测试用身份头构造(2026-09-15 网关唯一鉴权点口径):服务内不再验签 JWT,
 * 受保护接口只需网关透传的身份头 {@code X-User-Id/Role/Mfa/Jti}。
 */
final class TestIdentity {

    private TestIdentity() {
    }

    /** 构造指定账号/角色/MFA 的身份头(MockMvc 用 {@code .with(...)} 应用)。 */
    static RequestPostProcessor of(String accountId, String role, boolean mfa) {
        return request -> {
            request.addHeader("X-User-Id", accountId);
            request.addHeader("X-User-Role", role);
            request.addHeader("X-User-Mfa", String.valueOf(mfa));
            request.addHeader("X-User-Jti", "jti-" + accountId);
            return request;
        };
    }

    static RequestPostProcessor consumer() {
        return of("1001", "CONSUMER", true);
    }

    static RequestPostProcessor regulator() {
        return of("9001", "REGULATOR", true);
    }
}
