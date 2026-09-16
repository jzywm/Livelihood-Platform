package com.msz.acc.infrastructure.auth.session;

import com.msz.acc.infrastructure.auth.JwtCodec;

import java.time.Clock;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.UUID;

/**
 * 短 token 签发口径（任务 3.6，spec「Access token claims match the gateway policy」，design D4）：
 * 默认 **15 分钟**（{@code acc.session.access-token-ttl-seconds} 可调，夹紧到 {@code [60, 900]}）、
 * 声明 {@code sub/role/mfa/jti/iat/exp}，另加 {@code typ=access} 与 {@code fam}（会话族）。
 *
 * <p>与网关策略的不变式：**ACC 签发 ≤ 网关上限 − 容差**。网关上限由
 * {@code gateway.auth.access-token-max-ttl}（默认 15m）+ {@code clock-skew}（默认 60s）守门，
 * 故 ACC 侧的**上限**固定为 900s（= 15 分钟）——配置超上限只夹紧并告警，绝不放大
 * （{@link #effectiveTtlSeconds(long)}；配置超限时由 {@code AccConfiguration#accessTokenIssuer} 打 WARN），
 * 并由 {@code AccessTokenIssuerTest} 用网关同批断言锁定（含超长必须被拒的反向守卫）。</p>
 *
 * <p><b>FIX-1/B6</b>：{@code acc.session.access-token-ttl-seconds} 原为「可配却被忽略」的键
 * （永远按常量 900s 签发，运维改小它没有任何效果）——现改为**真正生效且夹紧**：区间
 * {@code [ACCESS_TOKEN_TTL_MIN_SECONDS, ACCESS_TOKEN_TTL_SECONDS]}。同一有效值必须同时驱动
 * **签发**与**族内 jti 绑定**（{@code RefreshTokenStore} 的 access TTL 参数），否则族记录里短 token
 * 的到期时刻与实际不符，整族吊销写下的 `revoked:jti:*` TTL 会失真。</p>
 *
 * <p>{@code typ} 与 refresh 的 {@code typ=refresh} 对称：两者同算法同密钥，必须能相互区分，
 * 否则短 token 会被当成 refresh 使用（或反之）而绕过各自的判定。</p>
 */
public final class AccessTokenIssuer {

    /** 短 token 有效期常量：15 分钟（PDD v1.18 §8.4.1 定档，网关策略上限同值 + 60s 容差）。 */
    public static final long ACCESS_TOKEN_TTL_SECONDS = 900L;

    /** 可配置短 token 有效期的**下限**（秒）：避免把短 token 配成「一出即过期」（客户端永远用不上）。 */
    public static final long ACCESS_TOKEN_TTL_MIN_SECONDS = 60L;

    /** 短 token 类型标记（与 refresh 区分）。 */
    public static final String TYPE_ACCESS = "access";

    /**
     * 把配置值 {@code acc.session.access-token-ttl-seconds} 夹紧到
     * {@code [ACCESS_TOKEN_TTL_MIN_SECONDS, ACCESS_TOKEN_TTL_SECONDS]}（B6）。
     *
     * <p>上限 = 网关策略上限（15m），保证「ACC 签发 ≤ 网关上限 − 容差」不变式恒成立；
     * 配置被改动（无论放大还是缩小）都会由装配层打 WARN，不会静默生效或静默忽略。</p>
     */
    public static long effectiveTtlSeconds(long configuredTtlSeconds) {
        return Math.min(Math.max(configuredTtlSeconds, ACCESS_TOKEN_TTL_MIN_SECONDS), ACCESS_TOKEN_TTL_SECONDS);
    }

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
