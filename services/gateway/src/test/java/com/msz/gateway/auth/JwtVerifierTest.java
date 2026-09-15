package com.msz.gateway.auth;

import com.msz.gateway.error.AuthException;
import org.junit.jupiter.api.Test;

import java.time.Duration;
import java.time.Instant;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * 任务 4.1 验证:JwtVerifier——手写 HS256 验签 + alg 固定 + exp/sub 令牌策略 + 常数时间比较,
 * 与 acc JwtCodec.verify 同口径,失败统一 AuthException 不泄露细节。
 */
class JwtVerifierTest {

    private static final String FIXTURE_SECRET = "test-gateway-secret";

    private final JwtVerifier verifier = new JwtVerifier();

    @Test
    void verifiesValidTokenAndReturnsClaims() {
        String token = TestJwt.sign(Map.of(
                "sub", "1001", "role", "CONSUMER", "jti", "j-1", "mfa", true), FIXTURE_SECRET, 300);

        Map<String, Object> claims = verifier.verify(token, FIXTURE_SECRET);

        assertThat(claims.get("sub")).isEqualTo("1001");
        assertThat(claims.get("role")).isEqualTo("CONSUMER");
        assertThat(claims.get("jti")).isEqualTo("j-1");
        assertThat(claims.get("mfa")).isEqualTo(true);
        assertThat(claims.get("exp")).isInstanceOf(Number.class);
    }

    @Test
    void rejectsTamperedSignature() {
        String token = TestJwt.tamper(TestJwt.sign(Map.of("sub", "1001"), FIXTURE_SECRET, 300));

        assertThatThrownBy(() -> verifier.verify(token, FIXTURE_SECRET))
                .isInstanceOf(AuthException.class);
    }

    @Test
    void rejectsExpiredToken() {
        String token = TestJwt.sign(Map.of("sub", "1001"), FIXTURE_SECRET, -10);

        assertThatThrownBy(() -> verifier.verify(token, FIXTURE_SECRET))
                .isInstanceOf(AuthException.class);
    }

    @Test
    void rejectsMalformedToken() {
        assertThatThrownBy(() -> verifier.verify("only-two.parts", FIXTURE_SECRET))
                .isInstanceOf(AuthException.class);
        assertThatThrownBy(() -> verifier.verify("", FIXTURE_SECRET))
                .isInstanceOf(AuthException.class);
        assertThatThrownBy(() -> verifier.verify(null, FIXTURE_SECRET))
                .isInstanceOf(AuthException.class);
    }

    @Test
    void rejectsWrongSecret() {
        String token = TestJwt.sign(Map.of("sub", "1001"), FIXTURE_SECRET, 300);

        assertThatThrownBy(() -> verifier.verify(token, "other-secret"))
                .isInstanceOf(AuthException.class);
    }

    @Test
    void rejectsNonJsonPayload() {
        String token = TestJwt.signPayload("not-json", FIXTURE_SECRET);

        assertThatThrownBy(() -> verifier.verify(token, FIXTURE_SECRET))
                .isInstanceOf(AuthException.class);
    }

    @Test
    void rejectsAlgorithmOtherThanHs256() {
        // alg=none 算法混淆尝试:签名段即使正确也必须拒绝
        String token = TestJwt.signWithHeader("{\"alg\":\"none\",\"typ\":\"JWT\"}",
                "{\"sub\":\"1001\",\"exp\":" + (Instant.now().getEpochSecond() + 300) + "}", FIXTURE_SECRET);

        assertThatThrownBy(() -> verifier.verify(token, FIXTURE_SECRET))
                .isInstanceOf(AuthException.class);
    }

    // ---------- 令牌策略(审查 I9 + 2026-09-15 双 token 裁决) ----------

    @Test
    void rejectsTokenWithoutSub() {
        String token = TestJwt.sign(Map.of("role", "CONSUMER"), FIXTURE_SECRET, 300);

        assertThatThrownBy(() -> verifier.verify(token, FIXTURE_SECRET))
                .as("无 sub 会让下游收到空身份,鉴权点失守")
                .isInstanceOf(AuthException.class);
    }

    @Test
    void rejectsTokenWithBlankSub() {
        String token = TestJwt.sign(Map.of("sub", "   "), FIXTURE_SECRET, 300);

        assertThatThrownBy(() -> verifier.verify(token, FIXTURE_SECRET))
                .isInstanceOf(AuthException.class);
    }

    @Test
    void rejectsTokenWithoutExp() {
        String token = TestJwt.signPayload(
                "{\"sub\":\"1001\",\"iat\":" + Instant.now().getEpochSecond() + "}", FIXTURE_SECRET);

        assertThatThrownBy(() -> verifier.verify(token, FIXTURE_SECRET))
                .isInstanceOf(AuthException.class);
    }

    @Test
    void rejectsTokenExceedingAccessTokenMaxTtl() {
        // 1 小时有效期 = 长 token 口径,网关只认 15 分钟短 token
        String token = TestJwt.sign(Map.of("sub", "1001"), FIXTURE_SECRET, 3600);

        assertThatThrownBy(() -> verifier.verify(token, FIXTURE_SECRET))
                .as("超长有效期 token 绕过了「密钥泄漏爆炸半径受控」的前提")
                .isInstanceOf(AuthException.class);
    }

    @Test
    void acceptsTokenWithinMaxTtlPlusClockSkew() {
        // 15min 上限 + 60s 容差 = 960s,边界内应放行
        String token = TestJwt.sign(Map.of("sub", "1001"), FIXTURE_SECRET, 960);

        assertThat(verifier.verify(token, FIXTURE_SECRET).get("sub")).isEqualTo("1001");
    }

    @Test
    void appliesConfiguredPolicy() {
        JwtVerifier strict = new JwtVerifier(Duration.ofMinutes(1), Duration.ZERO);

        assertThat(strict.verify(TestJwt.sign(Map.of("sub", "1001"), FIXTURE_SECRET, 30), FIXTURE_SECRET))
                .containsEntry("sub", "1001");
        assertThatThrownBy(() -> strict.verify(TestJwt.sign(Map.of("sub", "1001"), FIXTURE_SECRET, 300), FIXTURE_SECRET))
                .isInstanceOf(AuthException.class);
    }
}
