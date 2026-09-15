package com.msz.gateway.auth;

import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.Base64;
import java.util.LinkedHashMap;
import java.util.Map;

import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;

/**
 * 测试用 HS256 JWT 签发工具(与 acc JwtCodec.sign 同口径,仅供测试)。
 */
public final class TestJwt {

    private static final String HEADER = "{\"alg\":\"HS256\",\"typ\":\"JWT\"}";
    private static final String HMAC_ALG = "HmacSHA256";

    private TestJwt() {
    }

    public static String sign(Map<String, Object> claims, String secret, long ttlSeconds) {
        Map<String, Object> payload = new LinkedHashMap<>(claims);
        payload.put("iat", Instant.now().getEpochSecond());
        payload.put("exp", Instant.now().getEpochSecond() + ttlSeconds);
        return signRaw(payload, secret);
    }

    public static String signRaw(Map<String, Object> payload, String secret) {
        String header = base64Url(HEADER.getBytes(StandardCharsets.UTF_8));
        String body = base64Url(toJson(payload).getBytes(StandardCharsets.UTF_8));
        String signingInput = header + "." + body;
        String signature = base64Url(hmac(signingInput, secret));
        return signingInput + "." + signature;
    }

    /** 篡改 payload 段(第 2 段)中间某字符,签名必然失配。 */
    public static String tamper(String token) {
        String[] parts = token.split("\\.");
        char[] chars = parts[1].toCharArray();
        int mid = chars.length / 2;
        chars[mid] = chars[mid] == 'A' ? 'B' : 'A';
        return parts[0] + "." + new String(chars) + "." + parts[2];
    }

    /** 对任意原始 payload 文本直接签名(用于构造非 JSON payload 的合法签名 token)。 */
    public static String signPayload(String rawJsonPayload, String secret) {
        String header = base64Url(HEADER.getBytes(StandardCharsets.UTF_8));
        String body = base64Url(rawJsonPayload.getBytes(StandardCharsets.UTF_8));
        String signingInput = header + "." + body;
        return signingInput + "." + base64Url(hmac(signingInput, secret));
    }

    /** 使用自定义 header 段签名(用于构造 alg=none 等算法混淆用例)。 */
    public static String signWithHeader(String headerJson, String payloadJson, String secret) {
        String header = base64Url(headerJson.getBytes(StandardCharsets.UTF_8));
        String body = base64Url(payloadJson.getBytes(StandardCharsets.UTF_8));
        String signingInput = header + "." + body;
        return signingInput + "." + base64Url(hmac(signingInput, secret));
    }

    private static String toJson(Map<String, Object> map) {
        StringBuilder sb = new StringBuilder("{");
        boolean first = true;
        for (Map.Entry<String, Object> e : map.entrySet()) {
            if (!first) {
                sb.append(',');
            }
            first = false;
            sb.append('"').append(e.getKey()).append("\":");
            Object v = e.getValue();
            if (v instanceof String s) {
                sb.append('"').append(s).append('"');
            } else if (v instanceof Number || v instanceof Boolean) {
                sb.append(v);
            } else {
                throw new IllegalArgumentException("测试工具仅支持 String/Number/Boolean 值");
            }
        }
        return sb.append('}').toString();
    }

    private static byte[] hmac(String data, String secret) {
        try {
            Mac mac = Mac.getInstance(HMAC_ALG);
            mac.init(new SecretKeySpec(secret.getBytes(StandardCharsets.UTF_8), HMAC_ALG));
            return mac.doFinal(data.getBytes(StandardCharsets.UTF_8));
        } catch (Exception e) {
            throw new IllegalStateException("HS256 签名失败", e);
        }
    }

    private static String base64Url(byte[] bytes) {
        return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
    }
}
