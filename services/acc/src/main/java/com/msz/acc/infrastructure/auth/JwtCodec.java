package com.msz.acc.infrastructure.auth;

import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import java.nio.charset.StandardCharsets;
import java.security.GeneralSecurityException;
import java.security.MessageDigest;
import java.time.Instant;
import java.util.Base64;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 手写 HS256 JWT 编解码器（2.3，不引入 JWT 库）。
 *
 * <p>结构：{@code base64url(header).base64url(payload).base64url(HMAC-SHA256(signingInput))}，
 * iat/exp 秒级；验签用常数时间比较；验签失败/过期/格式非法统一抛 {@link AuthException}，
 * 不泄露失败细节（SEC-07）。
 */
public final class JwtCodec {

    private static final String HEADER = "{\"alg\":\"HS256\",\"typ\":\"JWT\"}";
    private static final String HMAC_ALG = "HmacSHA256";

    /** 签发：claims + iat/exp（秒级），HS256 签名，返回完整 token。 */
    public String sign(Map<String, Object> claims, String secret, long ttlSeconds) {
        long now = Instant.now().getEpochSecond();
        Map<String, Object> payload = new LinkedHashMap<>(claims);
        payload.put("iat", now);
        payload.put("exp", now + ttlSeconds);

        String header = base64Url(HEADER.getBytes(StandardCharsets.UTF_8));
        String body = base64Url(Json.toJson(payload).getBytes(StandardCharsets.UTF_8));
        String signingInput = header + "." + body;
        String signature = base64Url(hmac(signingInput, secret));
        return signingInput + "." + signature;
    }

    /** 校验：验签 + 过期，成功返回 claims（含 iat/exp），失败抛 {@link AuthException}。 */
    public Map<String, Object> verify(String token, String secret) {
        if (token == null || token.isEmpty()) {
            throw new AuthException("token 缺失");
        }
        String[] parts = token.split("\\.");
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

        Map<String, Object> claims;
        try {
            String payloadJson = new String(base64UrlDecode(parts[1]), StandardCharsets.UTF_8);
            claims = Json.parseObject(payloadJson);
        } catch (RuntimeException e) {
            throw new AuthException("payload 解析失败", e);
        }

        Object expValue = claims.get("exp");
        if (!(expValue instanceof Number expNumber) || expNumber.longValue() <= Instant.now().getEpochSecond()) {
            throw new AuthException("token 已过期");
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

    private static String base64Url(byte[] bytes) {
        return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
    }

    private static byte[] base64UrlDecode(String s) {
        return Base64.getUrlDecoder().decode(s);
    }
}
