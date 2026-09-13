package com.msz.acc.infrastructure.auth;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * SEC-07：手写 HS256 JWT 编解码——round-trip、篡改签名、过期。
 */
class JwtCodecTest {

    private static final String SECRET = "test-secret-0123456789";

    private final JwtCodec codec = new JwtCodec();

    private static Map<String, Object> claims() {
        return Map.of("sub", "1001", "role", "CONSUMER", "jti", "jti-001");
    }

    @Test
    @DisplayName("SEC-07 sign/verify round-trip")
    void ut_signVerifyRoundTrip() {
        String token = codec.sign(claims(), SECRET, 300);

        Map<String, Object> verified = codec.verify(token, SECRET);

        assertThat(verified.get("sub")).isEqualTo("1001");
        assertThat(verified.get("role")).isEqualTo("CONSUMER");
        assertThat(verified.get("jti")).isEqualTo("jti-001");
        assertThat(verified.get("iat")).isInstanceOf(Number.class);
        assertThat(verified.get("exp")).isInstanceOf(Number.class);
    }

    @Test
    @DisplayName("SEC-07 篡改签名 → AuthException")
    void ut_tamperedSignatureThrowsAuthException() {
        String token = codec.sign(claims(), SECRET, 300);

        String tampered = tamperPayloadMiddle(token);

        assertThatThrownBy(() -> codec.verify(tampered, SECRET))
                .isInstanceOf(AuthException.class);
    }

    /**
     * 确定性篡改：改 payload 段（第 2 段）中间某字符。verify 的签名输入为原始字符串
     * {@code header + "." + payload}，任何字符变化必导致重算 HMAC 失配（不依赖 base64url 解码差异）。
     */
    private static String tamperPayloadMiddle(String token) {
        String[] parts = token.split("\\.");
        String payload = parts[1];
        int idx = payload.length() / 2;
        char original = payload.charAt(idx);
        char changed = original == 'A' ? 'B' : 'A';
        return parts[0] + "." + payload.substring(0, idx) + changed + payload.substring(idx + 1) + "." + parts[2];
    }

    @Test
    @DisplayName("SEC-07 过期（负 ttl）→ AuthException")
    void ut_expiredTokenThrowsAuthException() {
        String token = codec.sign(claims(), SECRET, -10);

        assertThatThrownBy(() -> codec.verify(token, SECRET))
                .isInstanceOf(AuthException.class);
    }
}
