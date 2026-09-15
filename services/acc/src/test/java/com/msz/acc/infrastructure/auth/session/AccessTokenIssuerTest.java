package com.msz.acc.infrastructure.auth.session;

import com.msz.acc.infrastructure.auth.JwtCodec;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * 短 token 签发口径（任务 3.6，spec「Access token claims match the gateway policy」）：
 * {@code exp - iat = 900s}、声明含 {@code sub/role/mfa/jti/iat/exp}、HS256。
 *
 * <p><b>网关策略复刻断言</b>：本用例内联实现网关 {@code JwtVerifier} 的同批判定
 * （`alg=HS256`、`sub` 非空白、`exp ≤ access-token-max-ttl(15m) + clock-skew(60s)`、未过期），
 * 使「ACC 签发 → 网关接受」这条不变式在 ACC 侧就有直接守卫（不必等联调才发现漂移）。</p>
 */
class AccessTokenIssuerTest {

    private static final String FIXTURE_SECRET = "acc-jwt-fixture-secret-0123456789";
    private static final long FIXED_EPOCH_SECOND = 1_760_000_000L;

    private final JwtCodec codec = new JwtCodec(Clock.fixed(Instant.ofEpochSecond(FIXED_EPOCH_SECOND), ZoneOffset.UTC));
    private final Clock clock = Clock.fixed(Instant.ofEpochSecond(FIXED_EPOCH_SECOND), ZoneOffset.UTC);
    private final AccessTokenIssuer issuer = new AccessTokenIssuer(codec, FIXTURE_SECRET, 900L, clock);

    @Test
    @DisplayName("签发：exp - iat = 900s（严格 15 分钟），且有独立 jti")
    void lifetimeIsExactlyFifteenMinutes() {
        AccessTokenIssuer.Issued issued = issuer.issue(1001L, "CONSUMER", false, "fam_1");

        Map<String, Object> claims = codec.verify(issued.token(), FIXTURE_SECRET);
        long iat = ((Number) claims.get("iat")).longValue();
        long exp = ((Number) claims.get("exp")).longValue();

        assertThat(exp - iat).isEqualTo(900L);
        assertThat(iat).isEqualTo(FIXED_EPOCH_SECOND);
        assertThat(issued.jti()).isEqualTo(claims.get("jti"));
        assertThat(issued.jti()).isNotBlank();
    }

    @Test
    @DisplayName("声明齐全：sub（= 账户 ID）/role/mfa/jti/iat/exp 一个不少，且带 fam 归属会话族")
    void claimsAreComplete() {
        AccessTokenIssuer.Issued issued = issuer.issue(1001L, "REGULATOR", true, "fam_9");

        Map<String, Object> claims = codec.verify(issued.token(), FIXTURE_SECRET);

        assertThat(claims.get("sub")).isEqualTo("1001");
        assertThat(claims.get("role")).isEqualTo("REGULATOR");
        assertThat(claims.get("mfa")).isEqualTo(Boolean.TRUE);
        assertThat(claims.get("jti")).isNotNull();
        assertThat(claims.get("iat")).isNotNull();
        assertThat(claims.get("exp")).isNotNull();
        assertThat(claims.get("fam")).isEqualTo("fam_9");
        assertThat(claims.get("typ")).isEqualTo(AccessTokenIssuer.TYPE_ACCESS);
    }

    @Test
    @DisplayName("每次签发 jti 唯一（吊销按 jti 精确到单次签发，不误伤同族已过期 token）")
    void jtiIsUniquePerIssue() {
        String first = issuer.issue(1001L, "CONSUMER", false, "fam_1").jti();
        String second = issuer.issue(1001L, "CONSUMER", false, "fam_1").jti();

        assertThat(first).isNotEqualTo(second);
    }

    @Test
    @DisplayName("角色缺失回退 CONSUMER（不签发无角色 token 导致下游越权判定异常）")
    void nullRoleFallsBackToConsumer() {
        AccessTokenIssuer.Issued issued = issuer.issue(1001L, null, false, "fam_1");

        assertThat(codec.verify(issued.token(), FIXTURE_SECRET).get("role")).isEqualTo("CONSUMER");
    }

    @Test
    @DisplayName("3.6 通过网关策略：HS256 + sub 非空白 + exp ≤ 15m + 60s 容差 + 未过期")
    void passesGatewayTokenPolicy() {
        AccessTokenIssuer.Issued issued = issuer.issue(1001L, "CONSUMER", false, "fam_1");

        // 与 services/gateway JwtVerifier 同批判定（内联复刻，避免 ACC 依赖网关模块）
        assertThat(gatewayStyleVerify(issued.token(), FIXTURE_SECRET, 900L, 60L, FIXED_EPOCH_SECOND))
                .containsEntry("sub", "1001");
    }

    @Test
    @DisplayName("3.6 反向守卫：有效期超 15 分钟（1000s）必须被同一批判定拒绝")
    void overlyLongLifetimeIsRejectedByGatewayPolicy() {
        AccessTokenIssuer tooLong = new AccessTokenIssuer(codec, FIXTURE_SECRET, 1000L, clock);
        AccessTokenIssuer.Issued issued = tooLong.issue(1001L, "CONSUMER", false, "fam_1");

        assertThatThrownBy(() -> gatewayStyleVerify(issued.token(), FIXTURE_SECRET, 900L, 60L, FIXED_EPOCH_SECOND))
                .hasMessageContaining("有效期超出上限");
    }

    @Test
    @DisplayName("3.6 反向守卫：过期 token 被拒（exp ≤ now）")
    void expiredTokenIsRejected() {
        AccessTokenIssuer.Issued issued = issuer.issue(1001L, "CONSUMER", false, "fam_1");

        assertThatThrownBy(() -> gatewayStyleVerify(issued.token(), FIXTURE_SECRET, 900L, 60L,
                FIXED_EPOCH_SECOND + 901L))
                .hasMessageContaining("已过期");
    }

    /**
     * 复刻网关 {@code JwtVerifier} 的策略判定（仅策略相关的四条：HS256 / exp 上限 / 未过期 / sub 非空白）。
     * 使用手写 base64url + HMAC，与网关实现同算法。
     */
    private static Map<String, Object> gatewayStyleVerify(String token, String secret, long maxTtlSeconds,
                                                         long skewSeconds, long nowSecond) {
        String[] parts = token.split("\\.", -1);
        if (parts.length != 3) {
            throw new IllegalArgumentException("token 格式非法");
        }
        Map<String, Object> header = verifyAndParse(parts, secret);
        if (!"HS256".equals(header.get("alg"))) {
            throw new IllegalArgumentException("不支持的签名算法");
        }
        Map<String, Object> claims = com.msz.acc.infrastructure.auth.Json.parseObject(
                new String(java.util.Base64.getUrlDecoder().decode(parts[1]),
                        java.nio.charset.StandardCharsets.UTF_8));
        Object expValue = claims.get("exp");
        if (!(expValue instanceof Number expNumber)) {
            throw new IllegalArgumentException("token 缺少 exp");
        }
        long exp = expNumber.longValue();
        if (exp <= nowSecond) {
            throw new IllegalArgumentException("token 已过期");
        }
        if (exp > nowSecond + maxTtlSeconds + skewSeconds) {
            throw new IllegalArgumentException("token 有效期超出上限");
        }
        Object sub = claims.get("sub");
        if (!(sub instanceof String subValue) || subValue.isBlank()) {
            throw new IllegalArgumentException("token 缺少 sub");
        }
        return claims;
    }

    private static Map<String, Object> verifyAndParse(String[] parts, String secret) {
        byte[] expected;
        byte[] actual;
        try {
            javax.crypto.Mac mac = javax.crypto.Mac.getInstance("HmacSHA256");
            mac.init(new javax.crypto.spec.SecretKeySpec(secret.getBytes(
                    java.nio.charset.StandardCharsets.UTF_8), "HmacSHA256"));
            expected = mac.doFinal((parts[0] + "." + parts[1]).getBytes(
                    java.nio.charset.StandardCharsets.UTF_8));
            actual = java.util.Base64.getUrlDecoder().decode(parts[2]);
        } catch (Exception e) {
            throw new IllegalArgumentException("签名段非法", e);
        }
        if (!java.security.MessageDigest.isEqual(expected, actual)) {
            throw new IllegalArgumentException("签名校验失败");
        }
        return com.msz.acc.infrastructure.auth.Json.parseObject(
                new String(java.util.Base64.getUrlDecoder().decode(parts[0]),
                        java.nio.charset.StandardCharsets.UTF_8));
    }
}
