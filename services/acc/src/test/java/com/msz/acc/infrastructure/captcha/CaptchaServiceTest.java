package com.msz.acc.infrastructure.captcha;

import com.msz.acc.domain.support.AccBusinessException;
import com.msz.common.idgen.IdGenerator;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * CaptchaService（S5 端口适配）：挑战下发（缺省 SLIDER / IMAGE 降级 / 非法 type 1003）、
 * 校验成功即删 key（一次性）、错误不抛异常返回 success=false、verifyToken 一次性消费（1003）、TTL 300s。
 */
class CaptchaServiceTest {

    private static final Instant NOW = Instant.parse("2026-01-15T10:00:00Z");

    private final IdGenerator idGenerator = mock(IdGenerator.class);
    private final MutableClock clock = new MutableClock(NOW);

    private CaptchaService service() {
        when(idGenerator.nextId()).thenReturn(1L, 2L, 3L, 4L, 5L, 6L, 7L, 8L);
        return new CaptchaService(null, idGenerator, clock);
    }

    @Test
    @DisplayName("缺省 SLIDER：captchaId cap_ 前缀，答案仅服务端可查，TTL 300s 过期后校验失败")
    void ut_sliderChallengeLifecycle() {
        CaptchaService service = service();

        String captchaId = service.createChallenge(null);

        assertThat(captchaId).isEqualTo("cap_1");
        assertThat(service.expectedOffset(captchaId)).isNotNull();
        assertThat(service.expectedCode(captchaId)).isNull();

        // 正确偏移（容差内）→ 通过 + 下发 verifyToken
        int answer = service.expectedOffset(captchaId);
        var ok = service.verify(captchaId, answer + 2, null);
        assertThat(ok.success()).isTrue();
        assertThat(ok.verifyToken()).isEqualTo("ct_2");

        // 一次性：成功后 key 已删，再次校验失败
        assertThat(service.verify(captchaId, answer, null).success()).isFalse();
    }

    @Test
    @DisplayName("错误答案 → success=false 且不抛异常、不删 key（可重试），无 verifyToken")
    void ut_wrongAnswerRetryable() {
        CaptchaService service = service();
        String captchaId = service.createChallenge("SLIDER");
        int answer = service.expectedOffset(captchaId);

        var failed = service.verify(captchaId, answer + 100, null);
        assertThat(failed.success()).isFalse();
        assertThat(failed.verifyToken()).isNull();

        assertThat(service.verify(captchaId, answer, null).success()).isTrue();
    }

    @Test
    @DisplayName("IMAGE 降级：code 不区分大小写校验通过；滑块偏移对 IMAGE 无效")
    void ut_imageChallenge() {
        CaptchaService service = service();
        String captchaId = service.createChallenge("IMAGE");

        assertThat(service.expectedCode(captchaId)).matches("[A-Z0-9]{4}");
        String code = service.expectedCode(captchaId);

        assertThat(service.verify(captchaId, null, code.toLowerCase()).success()).isTrue();
    }

    @Test
    @DisplayName("非法 type → AccBusinessException(1003)")
    void ut_invalidTypeRejected() {
        assertThatThrownBy(() -> service().createChallenge("BOGUS"))
                .isInstanceOfSatisfying(AccBusinessException.class,
                        e -> assertThat(e.code()).isEqualTo(1003));
    }

    @Test
    @DisplayName("过期挑战（TTL 300s）→ success=false")
    void ut_expiredChallengeFails() {
        CaptchaService service = service();
        String captchaId = service.createChallenge(null);
        int answer = service.expectedOffset(captchaId);

        clock.advance(301);

        assertThat(service.verify(captchaId, answer, null).success()).isFalse();
    }

    @Test
    @DisplayName("未知 captchaId → success=false")
    void ut_unknownCaptchaFails() {
        assertThat(service().verify("cap_nope", 137, null).success()).isFalse();
    }

    @Test
    @DisplayName("consumeToken 一次性：消费成功、二次消费 1003、未知 token 1003")
    void ut_tokenConsumeOnce() {
        CaptchaService service = service();
        String captchaId = service.createChallenge(null);
        String token = service.verify(captchaId, service.expectedOffset(captchaId), null).verifyToken();

        service.consumeToken(token);
        assertThatThrownBy(() -> service.consumeToken(token))
                .isInstanceOfSatisfying(AccBusinessException.class,
                        e -> assertThat(e.code()).isEqualTo(1003));
        assertThatThrownBy(() -> service.consumeToken("ct_unknown"))
                .isInstanceOfSatisfying(AccBusinessException.class,
                        e -> assertThat(e.code()).isEqualTo(1003));
    }

    /** 可控时钟（TTL/过期测试）。 */
    private static final class MutableClock extends Clock {
        private Instant instant;

        private MutableClock(Instant instant) {
            this.instant = instant;
        }

        void advance(long seconds) {
            instant = instant.plusSeconds(seconds);
        }

        @Override
        public ZoneOffset getZone() {
            return ZoneOffset.UTC;
        }

        @Override
        public Clock withZone(java.time.ZoneId zone) {
            return this;
        }

        @Override
        public Instant instant() {
            return instant;
        }
    }
}
