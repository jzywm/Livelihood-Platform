package com.msz.acc.controller;

import com.msz.acc.infrastructure.auth.JwtCodec;

import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 测试夹具：签发一条**固定时刻**的短 token（与 ACC 生产口径同结构），供控制器测试断言
 * 「从 Authorization 头解析出 jti / fam / 剩余有效期」。
 *
 * <p>密钥字面量带 {@code fixture} 标记（本机凭据粗筛口径）。</p>
 */
final class TestSessionTokens {

    /** 固定时刻：与 token 内的 iat 一致，剩余有效期断言因此可精确到 899/900 秒。 */
    static final long FIXED_EPOCH_SECOND = 1_760_000_000L;

    static final String ACCESS_JTI = "at_fixture_0001";

    static final String FAMILY_ID = "fam_fixture";

    static final String REFRESH_JTI = "rf_fixture_0001";

    static final String FIXTURE_SECRET = "acc-jwt-fixture-secret-0123456789";

    static final String FIXTURE_ACCESS_TOKEN = accessToken();

    private TestSessionTokens() {
    }

    /** 固定时刻签发（与 {@code AccessTokenIssuer} 同声明结构）。 */
    static String accessToken() {
        JwtCodec codec = new JwtCodec(Clock.fixed(Instant.ofEpochSecond(FIXED_EPOCH_SECOND), ZoneOffset.UTC));
        Map<String, Object> claims = new LinkedHashMap<>();
        claims.put("sub", "1001");
        claims.put("role", "CONSUMER");
        claims.put("mfa", false);
        claims.put("jti", ACCESS_JTI);
        claims.put("fam", FAMILY_ID);
        claims.put("typ", "access");
        return codec.sign(claims, FIXTURE_SECRET, 900L);
    }

    /**
     * 固定时刻签发一条 **refresh**（{@code typ=refresh}、7 天）：用于断言「把 refresh 放进
     * {@code Authorization: Bearer} 时不得被当成短 token」——两者同算法同密钥，只能靠 {@code typ} 区分。
     */
    static String refreshToken() {
        JwtCodec codec = new JwtCodec(Clock.fixed(Instant.ofEpochSecond(FIXED_EPOCH_SECOND), ZoneOffset.UTC));
        Map<String, Object> claims = new LinkedHashMap<>();
        claims.put("sub", "1001");
        claims.put("role", "CONSUMER");
        claims.put("mfa", false);
        claims.put("jti", REFRESH_JTI);
        claims.put("fam", FAMILY_ID);
        claims.put("typ", "refresh");
        return codec.sign(claims, FIXTURE_SECRET, 604_800L);
    }
}
