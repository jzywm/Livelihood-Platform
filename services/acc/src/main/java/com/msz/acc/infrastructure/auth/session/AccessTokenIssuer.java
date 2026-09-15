package com.msz.acc.infrastructure.auth.session;

import com.msz.acc.infrastructure.auth.JwtCodec;

import java.time.Clock;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.UUID;

/**
 * 短 token 签发口径（任务 3.6，spec「Access token claims match the gateway policy」，design D4）：
 * **15 分钟硬常量**、声明 {@code sub/role/mfa/jti/iat/exp}，另加 {@code typ=access} 与
 * {@code fam}（会话族）。
 *
 * <p>与网关策略的不变式：**ACC 签发 ≤ 网关上限 − 容差**。网关上限由
 * {@code gateway.auth.access-token-max-ttl}（默认 15m）+ {@code clock-skew}（默认 60s）守门，
 * ACC 侧固定 900s（= 15 分钟）——两侧不同源会漂移，故此处以**常量**而非可自由放大的配置表达，
 * 并由 {@code AccessTokenIssuerTest} 用网关同批断言锁定（含超长必须被拒的反向守卫）。</p>
 *
 * <p>{@code typ} 与 refresh 的 {@code typ=refresh} 对称：两者同算法同密钥，必须能相互区分，
 * 否则短 token 会被当成 refresh 使用（或反之）而绕过各自的判定。</p>
 */
public final class AccessTokenIssuer {

    /** 短 token 有效期常量：15 分钟（PDD v1.18 §8.4.1 定档，网关策略上限同值 + 60s 容差）。 */
    public static final long ACCESS_TOKEN_TTL_SECONDS = 900L;

    /** 短 token 类型标记（与 refresh 区分）。 */
    public static final String TYPE_ACCESS = "access";

    private static final String CLAIM_TYPE = "typ";
    private static final String CLAIM_FAMILY = "fam";

    private final JwtCodec jwtCodec;
    private final String secret;
    private final long ttlSeconds;
    private final Clock clock;

    public AccessTokenIssuer(JwtCodec jwtCodec, String secret, long ttlSeconds, Clock clock) {
        this.jwtCodec = jwtCodec;
        this.secret = secret;
        this.ttlSeconds = ttlSeconds;
        this.clock = clock;
    }

    /** 签发一条短 token（返回 token 与其 {@code jti}，后者用于按会话族吊销）。 */
    public Issued issue(long accountId, String role, boolean mfa, String familyId) {
        String jti = "at_" + UUID.randomUUID().toString().replace("-", "");
        Map<String, Object> claims = new LinkedHashMap<>();
        claims.put("sub", String.valueOf(accountId));
        claims.put("role", role == null || role.isBlank() ? "CONSUMER" : role);
        claims.put("mfa", mfa);
        claims.put("jti", jti);
        claims.put(CLAIM_FAMILY, familyId);
        claims.put(CLAIM_TYPE, TYPE_ACCESS);
        return new Issued(jwtCodec.sign(claims, secret, ttlSeconds), jti);
    }

    /** 短 token 有效期（秒）。 */
    public long ttlSeconds() {
        return ttlSeconds;
    }

    /** 剩余有效期（秒，≥1）：写吊销名单 TTL 用（调用方已在别处拿不到 exp 时使用）。 */
    public long remainingSeconds(long issuedAtEpochSecond) {
        long remaining = issuedAtEpochSecond + ttlSeconds - clock.instant().getEpochSecond();
        return Math.max(remaining, 1L);
    }

    /** 签发结果：token 原文（**只可进响应体，禁止进日志**）与 jti。 */
    public record Issued(String token, String jti) {
    }
}
