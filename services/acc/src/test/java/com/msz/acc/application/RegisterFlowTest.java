package com.msz.acc.application;

import com.msz.acc.application.port.CaptchaPort;
import com.msz.acc.application.port.RealnameChannelPort;
import com.msz.acc.application.support.HmacFingerprint;
import com.msz.acc.domain.model.Account;
import com.msz.acc.domain.model.RealnameRecord;
import com.msz.acc.domain.support.AccBusinessException;
import com.msz.acc.repository.AccountMapper;
import com.msz.acc.repository.RealnameRecordMapper;
import com.msz.common.idgen.IdGenerator;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * RegisterFlowTest（4.1）：合法注册返回 bizId/authorizeUrl/REALNAMING 且落 record；
 * mobile 非法 1002；captchaToken 已用 1003；mobile_hash 命中 REALNAMED 幂等返回原 accountId。
 */
class RegisterFlowTest {

    private CaptchaPort captchaPort;
    private RealnameChannelPort realnameChannelPort;
    private AccountMapper accountMapper;
    private RealnameRecordMapper realnameRecordMapper;
    private IdGenerator idGenerator;
    private HmacFingerprint hmacFingerprint;
    private RegisterFlow flow;

    @BeforeEach
    void setUp() {
        captchaPort = mock(CaptchaPort.class);
        realnameChannelPort = mock(RealnameChannelPort.class);
        accountMapper = mock(AccountMapper.class);
        realnameRecordMapper = mock(RealnameRecordMapper.class);
        idGenerator = mock(IdGenerator.class);
        hmacFingerprint = new HmacFingerprint("test-secret");
        Clock clock = Clock.fixed(Instant.parse("2026-01-15T00:00:00Z"), ZoneOffset.UTC);
        flow = new RegisterFlow(captchaPort, realnameChannelPort, accountMapper, realnameRecordMapper,
                idGenerator, hmacFingerprint, clock);
    }

    @Test
    @DisplayName("注册发起：返回 bizId/authorizeUrl/REALNAMING 且落 record")
    void ut_registerReturnsBizIdAuthorizeUrlAndRealnaming() {
        when(idGenerator.nextId()).thenReturn(123L);
        when(realnameChannelPort.requestAuthorization("rz_123", "13800138000", "CONSUMER"))
                .thenReturn("https://auth.example/authorize");

        RegisterResult result = flow.register("13800138000", "CONSUMER", "vt_ok");

        assertThat(result.bizId()).isEqualTo("rz_123");
        assertThat(result.authorizeUrl()).isEqualTo("https://auth.example/authorize");
        assertThat(result.realNameStatus()).isEqualTo("REALNAMING");
        assertThat(result.accountId()).isNull();
        assertThat(result.idempotent()).isFalse();

        verify(captchaPort).consumeToken("vt_ok");
        ArgumentCaptor<RealnameRecord> captor = ArgumentCaptor.forClass(RealnameRecord.class);
        verify(realnameRecordMapper).insert(captor.capture());
        assertThat(captor.getValue().getBizId()).isEqualTo("rz_123");
        assertThat(captor.getValue().getStatus()).isEqualTo("REALNAMING");
        assertThat(captor.getValue().getChannel()).isEqualTo("WECHAT");
        assertThat(captor.getValue().getOpenId()).isEqualTo("pending_rz_123");
        assertThat(captor.getValue().getName()).isEmpty();
        assertThat(captor.getValue().getIdNo()).isEmpty();
    }

    @Test
    @DisplayName("mobile 非法 → 1002")
    void ut_invalidMobileRejected() {
        assertThatThrownBy(() -> flow.register("12345", "CONSUMER", "vt"))
                .isInstanceOfSatisfying(AccBusinessException.class,
                        e -> assertThat(e.code()).isEqualTo(1002));
        verify(realnameRecordMapper, never()).insert(any());
    }

    @Test
    @DisplayName("captchaToken 已用 → 1003")
    void ut_consumedCaptchaTokenRejected() {
        doThrow(new AccBusinessException(1003, "captchaToken 已用"))
                .when(captchaPort).consumeToken("used-token");

        assertThatThrownBy(() -> flow.register("13800138000", "CONSUMER", "used-token"))
                .isInstanceOfSatisfying(AccBusinessException.class,
                        e -> assertThat(e.code()).isEqualTo(1003));
        verify(realnameRecordMapper, never()).insert(any());
    }

    @Test
    @DisplayName("mobile_hash 命中 REALNAMED → 幂等返回原 accountId，不再调通道")
    void ut_mobileHashHitReturnsIdempotent() {
        Account existing = new Account();
        existing.setAccountId(999L);
        existing.setRealNameStatus("REALNAMED");
        when(accountMapper.selectByMobileHash(anyString())).thenReturn(existing);

        RegisterResult result = flow.register("13800138000", "CONSUMER", "vt");

        assertThat(result.accountId()).isEqualTo(999L);
        assertThat(result.idempotent()).isTrue();
        assertThat(result.realNameStatus()).isEqualTo("REALNAMED");
        verify(accountMapper).selectByMobileHash(hmacFingerprint.hmacSha256Hex("13800138000"));
        verify(realnameChannelPort, never()).requestAuthorization(any(), any(), any());
        verify(realnameRecordMapper, never()).insert(any());
    }
}
