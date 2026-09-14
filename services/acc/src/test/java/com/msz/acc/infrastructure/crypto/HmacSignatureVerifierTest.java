package com.msz.acc.infrastructure.crypto;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * HmacSignatureVerifier（S5）：HMAC-SHA256 回调验签——正确签名通过；篡改/错密钥/空签拒绝；
 * sign 与 verify 同源（供通道模拟与 WireMock 测试共用）。
 */
class HmacSignatureVerifierTest {

    private static final String SECRET = "acc-callback-test-secret";
    private static final String PAYLOAD = "rz_1|openid-1|张三|110101199001011234|true|1768435200|nonce1234";

    private final HmacSignatureVerifier verifier = new HmacSignatureVerifier(SECRET);

    @Test
    @DisplayName("正确签名 → 通过")
    void ut_validSignaturePasses() {
        String sign = verifier.sign(PAYLOAD);

        assertThat(verifier.verify(PAYLOAD, sign)).isTrue();
    }

    @Test
    @DisplayName("payload 被篡改 → 拒绝")
    void ut_tamperedPayloadRejected() {
        String sign = verifier.sign(PAYLOAD);
        String tampered = PAYLOAD.replace("true", "false");

        assertThat(verifier.verify(tampered, sign)).isFalse();
    }

    @Test
    @DisplayName("错误密钥签名 → 拒绝")
    void ut_wrongSecretRejected() {
        String sign = new HmacSignatureVerifier("other-secret").sign(PAYLOAD);

        assertThat(verifier.verify(PAYLOAD, sign)).isFalse();
    }

    @Test
    @DisplayName("空/非法签名 → 拒绝且不抛异常")
    void ut_malformedSignRejected() {
        assertThat(verifier.verify(PAYLOAD, null)).isFalse();
        assertThat(verifier.verify(PAYLOAD, "")).isFalse();
        assertThat(verifier.verify(PAYLOAD, "not-hex!!")).isFalse();
    }

    @Test
    @DisplayName("签名输出为小写十六进制 SHA-256（64 字符）")
    void ut_signIsHexSha256() {
        assertThat(verifier.sign("hello")).matches("^[0-9a-f]{64}$");
    }
}
