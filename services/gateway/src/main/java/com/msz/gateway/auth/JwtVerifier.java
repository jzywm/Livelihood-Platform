package com.msz.gateway.auth;

import com.msz.gateway.error.AuthException;

import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import java.nio.charset.StandardCharsets;
import java.security.GeneralSecurityException;
import java.security.MessageDigest;
import java.time.Duration;
import java.time.Instant;
import java.util.Base64;
import java.util.Map;

/**
 * 手写 HS256 JWT 验签器(不引 JWT 库,与 acc JwtCodec.verify 同口径):
 * base64url(header).base64url(payload).base64url(HMAC-SHA256(signingInput)),
 * 验签用常数时间比较;格式非法/验签失败/过期统一抛 {@link AuthException},不泄露失败细节。
 *
 * <p><b>令牌策略(2026-09-15 审查 I9 + 用户裁决)</b>:① {@code alg} 必须为 HS256(防算法混淆);
 * ② {@code exp} 必须存在、未过期,且**不超过 {@code access-token-max-ttl}(默认 15 分钟)+ 容差**
 * ——网关只认短 token,超长有效期一律拒绝(签名密钥泄漏时爆炸半径受控);
 * ③ {@code sub} 必须存在且非空白(否则下游会收到空身份,鉴权点失守);
 * ④ 长 token(refresh,7 天)存 HttpOnly Cookie,**不经网关业务链路**,只用于换发短 token。</p>
 */
public final class JwtVerifier {

    private static final String HMAC_ALG = "HmacSHA256";

    private static final Duration DEFAULT_ACCESS_TOKEN_MAX_TTL = Duration.ofMinutes(15);
    private static final Duration DEFAULT_CLOCK_SKEW = Duration.ofSeconds(60);

    private final long accessTokenMaxTtlSeconds;
    private final long clockSkewSeconds;

    /** 默认策略:短 token 15 分钟 + 容差 60s。 */
    public JwtVerifier() {
        this(DEFAULT_ACCESS_TOKEN_MAX_TTL, DEFAULT_CLOCK_SKEW);
    }

    public JwtVerifier(Duration accessTokenMaxTtl, Duration clockSkew) {
        this.accessTokenMaxTtlSeconds =
                (accessTokenMaxTtl == null ? DEFAULT_ACCESS_TOKEN_MAX_TTL : accessTokenMaxTtl).toSeconds();
        this.clockSkewSeconds = (clockSkew == null ? DEFAULT_CLOCK_SKEW : clockSkew).toSeconds();
    }

    public Map<String, Object> verify(String token, String secret) {
        if (token == null || token.isEmpty()) {
            throw new AuthException("token 缺失");
        }
        String[] parts = token.split("\\.", -1);
        if (parts.length != 3) {
            throw new AuthException("token 格式非法");
        }
        String signingInput = parts[0] + "." + parts[1];
        byte[] expected;
        byte[] actual;
        try {
            expected = hmac(signingInput, secret);
            actual = base64UrlDecode(parts[2]);
        } catch (IllegalArgumentException e) {
            throw new AuthException("token 签名段非法", e);
        }
        if (!MessageDigest.isEqual(expected, actual)) {
            throw new AuthException("签名校验失败");
        }

        // 算法固定(审查 I9):拒绝 alg 非 HS256 的 token,避免算法混淆
        Map<String, Object> header;
        try {
            header = ClaimsJson.parseObject(new String(base64UrlDecode(parts[0]), StandardCharsets.UTF_8));
        } catch (RuntimeException e) {
            throw new AuthException("header 解析失败", e);
        }
        if (!"HS256".equals(header.get("alg"))) {
            throw new AuthException("不支持的签名算法");
        }

        Map<String, Object> claims;
        try {
            String payloadJson = new String(base64UrlDecode(parts[1]), StandardCharsets.UTF_8);
            claims = ClaimsJson.parseObject(payloadJson);
        } catch (RuntimeException e) {
            throw new AuthException("payload 解析失败", e);
        }

        Object expValue = claims.get("exp");
        if (!(expValue instanceof Number expNumber)) {
            throw new AuthException("token 缺少 exp");
        }
        long now = Instant.now().getEpochSecond();
        long exp = expNumber.longValue();
        // 过期判定严格(不留容差):容差只放宽「有效期上限」,避免过期 token 被额外接受
        if (exp <= now) {
            throw new AuthException("token 已过期");
        }
        if (exp > now + accessTokenMaxTtlSeconds + clockSkewSeconds) {
            throw new AuthException("token 有效期超出上限");
        }

        Object sub = claims.get("sub");
        if (!(sub instanceof String subValue) || subValue.isBlank()) {
            throw new AuthException("token 缺少 sub");
        }
        return claims;
    }

    private byte[] hmac(String data, String secret) {
        try {
            Mac mac = Mac.getInstance(HMAC_ALG);
            mac.init(new SecretKeySpec(secret.getBytes(StandardCharsets.UTF_8), HMAC_ALG));
            return mac.doFinal(data.getBytes(StandardCharsets.UTF_8));
        } catch (GeneralSecurityException e) {
            throw new IllegalStateException("HS256 签名失败", e);
        }
    }

    private static byte[] base64UrlDecode(String s) {
        return Base64.getUrlDecoder().decode(s);
    }
}
