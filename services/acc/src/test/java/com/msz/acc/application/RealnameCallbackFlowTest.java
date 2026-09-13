package com.msz.acc.application;

import com.msz.acc.application.port.SignatureVerifier;
import com.msz.acc.domain.model.Account;
import com.msz.acc.domain.model.RealnameRecord;
import com.msz.acc.domain.service.RealnameStatusMachine;
import com.msz.acc.domain.support.AccBusinessException;
import com.msz.acc.infrastructure.crypto.AesGcmCipher;
import com.msz.acc.infrastructure.crypto.FixedKeyProvider;
import com.msz.acc.repository.AccountMapper;
import com.msz.acc.repository.RealnameRecordMapper;
import com.msz.common.idgen.IdGenerator;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

import javax.crypto.SecretKey;
import javax.crypto.spec.SecretKeySpec;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * RealnameCallbackFlowTest（UT-A04~A07 口径）：验签失败 4001 拒收且状态不变；
 * 重放同 bizId（已 REALNAMED）幂等返回原 accountId；open_id 判重命中返回原账户；
 * pass=false 保持 REALNAMING 可重试；pass=true 建户 + REALNAMED + callback_at/account_id 回填；
 * suspendOnChannelUnavailable → SUSPENDED；时间戳超窗 1003。
 */
class RealnameCallbackFlowTest {

    private static final Instant NOW = Instant.parse("2026-01-15T00:00:00Z");

    private FakeSignatureVerifier signatureVerifier;
    private RealnameRecordMapper realnameRecordMapper;
    private AccountMapper accountMapper;
    private IdGenerator idGenerator;
    private AesGcmCipher cipher;
    private RealnameCallbackFlow flow;

    @BeforeEach
    void setUp() {
        signatureVerifier = new FakeSignatureVerifier();
        realnameRecordMapper = mock(RealnameRecordMapper.class);
        accountMapper = mock(AccountMapper.class);
        idGenerator = mock(IdGenerator.class);
        cipher = cipher();
        Clock clock = Clock.fixed(NOW, ZoneOffset.UTC);
        flow = new RealnameCallbackFlow(signatureVerifier, realnameRecordMapper, accountMapper,
                cipher, idGenerator, new RealnameStatusMachine(), clock);
    }

    @Test
    @DisplayName("UT-A05: 验签失败 4001 拒收且状态不变")
    void ut_signatureFailureRejected() {
        signatureVerifier.result = false;
        when(realnameRecordMapper.selectByBizId("rz_1")).thenReturn(record("rz_1", "REALNAMING"));

        assertThatThrownBy(() -> flow.handle(validRequest()))
                .isInstanceOfSatisfying(AccBusinessException.class,
                        e -> assertThat(e.code()).isEqualTo(4001));

        verify(accountMapper, never()).insert(any());
        verify(realnameRecordMapper, never()).updateCallback(any(), any(), any(), any());
    }

    @Test
    @DisplayName("UT-A06: 重放同 bizId（已 REALNAMED）→ 幂等返回原 accountId")
    void ut_replaySameBizIdReturnsOriginalAccount() {
        RealnameRecord already = record("rz_1", "REALNAMED");
        already.setAccountId(777L);
        when(realnameRecordMapper.selectByBizId("rz_1")).thenReturn(already);

        CallbackResult result = flow.handle(validRequest());

        assertThat(result.status()).isEqualTo("REALNAMED");
        assertThat(result.accountId()).isEqualTo(777L);
        verify(accountMapper, never()).insert(any());
    }

    @Test
    @DisplayName("UT-A04: open_id 判重命中其他 bizId 且已 REALNAMED → 返回原账户")
    void ut_openIdDuplicateReturnsOriginalAccount() {
        when(realnameRecordMapper.selectByBizId("rz_1")).thenReturn(record("rz_1", "REALNAMING"));
        RealnameRecord other = record("rz_other", "REALNAMED");
        other.setAccountId(555L);
        when(realnameRecordMapper.selectByOpenId("openid-1")).thenReturn(other);

        CallbackResult result = flow.handle(validRequest());

        assertThat(result.status()).isEqualTo("REALNAMED");
        assertThat(result.accountId()).isEqualTo(555L);
        verify(accountMapper, never()).insert(any());
    }

    @Test
    @DisplayName("UT-A07: pass=false → 保持 REALNAMING 可重试")
    void ut_passFalseKeepsRealnaming() {
        when(realnameRecordMapper.selectByBizId("rz_1")).thenReturn(record("rz_1", "REALNAMING"));
        when(realnameRecordMapper.selectByOpenId("openid-1")).thenReturn(null);

        RealnameCallbackRequest req = new RealnameCallbackRequest(
                "rz_1", "openid-1", "张三", "110101199001011234", false, "sig", NOW.getEpochSecond(), "nonce1234");

        CallbackResult result = flow.handle(req);

        assertThat(result.status()).isEqualTo("REALNAMING");
        assertThat(result.accountId()).isNull();
        verify(realnameRecordMapper).updateCallback("rz_1", "REALNAMING", null, NOW);
        verify(accountMapper, never()).insert(any());
    }

    @Test
    @DisplayName("pass=true → 建户 + REALNAMED + callback_at 回填 + account_id 回填")
    void ut_passTrueCreatesAccountAndBackfills() {
        when(realnameRecordMapper.selectByBizId("rz_1")).thenReturn(record("rz_1", "REALNAMING"));
        when(realnameRecordMapper.selectByOpenId("openid-1")).thenReturn(null);
        when(idGenerator.nextId()).thenReturn(888L);

        CallbackResult result = flow.handle(validRequest());

        assertThat(result.status()).isEqualTo("REALNAMED");
        assertThat(result.accountId()).isEqualTo(888L);

        ArgumentCaptor<Account> captor = ArgumentCaptor.forClass(Account.class);
        verify(accountMapper).insert(captor.capture());
        Account created = captor.getValue();
        assertThat(created.getAccountId()).isEqualTo(888L);
        assertThat(created.getRole()).isEqualTo("CONSUMER");
        assertThat(created.getRealNameStatus()).isEqualTo("REALNAMED");
        assertThat(cipher.decrypt("pii", created.getRealName())).isEqualTo("张三");
        assertThat(cipher.decrypt("pii", created.getIdNo())).isEqualTo("110101199001011234");

        verify(realnameRecordMapper).updateCallback("rz_1", "REALNAMED", 888L, NOW);
    }

    @Test
    @DisplayName("UT-A02: suspendOnChannelUnavailable → SUSPENDED")
    void ut_suspendOnChannelUnavailable() {
        when(realnameRecordMapper.selectByBizId("rz_1")).thenReturn(record("rz_1", "REALNAMING"));

        CallbackResult result = flow.suspendOnChannelUnavailable("rz_1");

        assertThat(result.status()).isEqualTo("SUSPENDED");
        verify(realnameRecordMapper).updateCallback("rz_1", "SUSPENDED", null, NOW);
    }

    @Test
    @DisplayName("时间戳超窗（±300s）→ 1003")
    void ut_timestampOutOfWindowRejected() {
        RealnameCallbackRequest req = new RealnameCallbackRequest(
                "rz_1", "openid-1", "张三", "110101199001011234", true, "sig",
                NOW.getEpochSecond() - 301L, "nonce1234");

        assertThatThrownBy(() -> flow.handle(req))
                .isInstanceOfSatisfying(AccBusinessException.class,
                        e -> assertThat(e.code()).isEqualTo(1003));
        verify(realnameRecordMapper, never()).selectByBizId(any());
    }

    private RealnameCallbackRequest validRequest() {
        return new RealnameCallbackRequest(
                "rz_1", "openid-1", "张三", "110101199001011234", true, "sig",
                NOW.getEpochSecond(), "nonce1234");
    }

    private static RealnameRecord record(String bizId, String status) {
        RealnameRecord record = new RealnameRecord();
        record.setBizId(bizId);
        record.setStatus(status);
        record.setChannel("WECHAT");
        record.setCreatedAt(Instant.parse("2026-01-01T00:00:00Z"));
        return record;
    }

    private static AesGcmCipher cipher() {
        byte[] bytes = new byte[32];
        for (int i = 0; i < bytes.length; i++) {
            bytes[i] = (byte) (i + 1);
        }
        SecretKey key = new SecretKeySpec(bytes, "AES");
        return new AesGcmCipher(new FixedKeyProvider(Map.of("pii", key)));
    }

    private static final class FakeSignatureVerifier implements SignatureVerifier {
        private boolean result = true;

        @Override
        public boolean verify(String payload, String sign) {
            return result;
        }
    }
}
