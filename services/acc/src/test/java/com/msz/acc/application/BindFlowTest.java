package com.msz.acc.application;

import com.msz.acc.application.port.PaymentChannelPort;
import com.msz.acc.domain.model.Account;
import com.msz.acc.domain.model.IdempotencyRecord;
import com.msz.acc.domain.model.WalletBinding;
import com.msz.acc.domain.support.AccBusinessException;
import com.msz.acc.repository.AccountMapper;
import com.msz.acc.repository.IdempotencyRecordMapper;
import com.msz.acc.repository.WalletBindingMapper;
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
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * BindFlowTest（UT-C01~C06 口径）：未实名 3001；户名与实名不符 3002；通道失败 4002 可重试（不落脏数据）；
 * 重复绑定幂等返回原 bindingId 复用原行；解绑 markUnbound；越权解绑他人 binding 2002；
 * IdempotencyGuard 同 key 第二次返回首次结果。
 */
class BindFlowTest {

    private static final Instant NOW = Instant.parse("2026-01-15T00:00:00Z");

    private AccountMapper accountMapper;
    private WalletBindingMapper walletBindingMapper;
    private FakePaymentChannelPort paymentChannelPort;
    private IdempotencyRecordMapper idempotencyRecordMapper;
    private IdGenerator idGenerator;
    private BindFlow flow;

    @BeforeEach
    void setUp() {
        accountMapper = mock(AccountMapper.class);
        walletBindingMapper = mock(WalletBindingMapper.class);
        paymentChannelPort = new FakePaymentChannelPort();
        idempotencyRecordMapper = mock(IdempotencyRecordMapper.class);
        idGenerator = mock(IdGenerator.class);
        Clock clock = Clock.fixed(NOW, ZoneOffset.UTC);
        flow = new BindFlow(accountMapper, walletBindingMapper, paymentChannelPort,
                idempotencyRecordMapper, idGenerator, clock);
    }

    @Test
    @DisplayName("UT-C01: 绑定成功（实名一致）")
    void ut_bindSuccess() {
        when(accountMapper.selectById(1L)).thenReturn(account(1L, "REALNAMED", "张三"));
        when(walletBindingMapper.selectByAccountAndChannel(1L, "WECHAT")).thenReturn(null);
        when(idempotencyRecordMapper.insertIgnore(anyString(), anyString(), anyInt(), anyString())).thenReturn(1);
        when(idGenerator.nextId()).thenReturn(10L);

        String bindingId = flow.bind(1L, "WECHAT", "6222021234567890", "张三", "k1");

        assertThat(bindingId).isEqualTo("bnd_10");
        ArgumentCaptor<WalletBinding> captor = ArgumentCaptor.forClass(WalletBinding.class);
        verify(walletBindingMapper).insert(captor.capture());
        WalletBinding inserted = captor.getValue();
        assertThat(inserted.getBindingId()).isEqualTo("bnd_10");
        assertThat(inserted.getStatus()).isEqualTo("BOUND");
        assertThat(inserted.getPayeeAccount()).isEqualTo("6222021234567890");
        assertThat(inserted.getPayeeName()).isEqualTo("张三");
    }

    @Test
    @DisplayName("未实名 → 3001")
    void ut_notRealnamedRejected() {
        when(accountMapper.selectById(1L)).thenReturn(account(1L, "REALNAMING", "张三"));

        assertThatThrownBy(() -> flow.bind(1L, "WECHAT", "6222021234567890", "张三", "k1"))
                .isInstanceOfSatisfying(AccBusinessException.class,
                        e -> assertThat(e.code()).isEqualTo(3001));
        verify(walletBindingMapper, never()).insert(any());
    }

    @Test
    @DisplayName("UT-C03: 户名与实名不符 → 3002")
    void ut_payeeNameMismatchRejected() {
        when(accountMapper.selectById(1L)).thenReturn(account(1L, "REALNAMED", "张三"));

        assertThatThrownBy(() -> flow.bind(1L, "WECHAT", "6222021234567890", "李四", "k1"))
                .isInstanceOfSatisfying(AccBusinessException.class,
                        e -> assertThat(e.code()).isEqualTo(3002));
        verify(walletBindingMapper, never()).insert(any());
    }

    @Test
    @DisplayName("UT-C04: 通道失败 4002 可重试，不落脏数据")
    void ut_channelFailureRetryable() {
        when(accountMapper.selectById(1L)).thenReturn(account(1L, "REALNAMED", "张三"));
        when(walletBindingMapper.selectByAccountAndChannel(1L, "WECHAT")).thenReturn(null);
        when(idempotencyRecordMapper.insertIgnore(anyString(), anyString(), anyInt(), anyString())).thenReturn(1);
        paymentChannelPort.fail = true;

        assertThatThrownBy(() -> flow.bind(1L, "WECHAT", "6222021234567890", "张三", "k-fail"))
                .isInstanceOfSatisfying(AccBusinessException.class,
                        e -> assertThat(e.code()).isEqualTo(4002));
        verify(walletBindingMapper, never()).insert(any());

        // 通道恢复后可重试成功
        paymentChannelPort.fail = false;
        when(idGenerator.nextId()).thenReturn(20L);
        assertThat(flow.bind(1L, "WECHAT", "6222021234567890", "张三", "k-retry"))
                .isEqualTo("bnd_20");
        verify(walletBindingMapper).insert(any());
    }

    @Test
    @DisplayName("UT-C02: 重复绑定幂等返回原 bindingId 复用原行")
    void ut_duplicateBindReusesExistingRow() {
        when(accountMapper.selectById(1L)).thenReturn(account(1L, "REALNAMED", "张三"));
        WalletBinding existing = new WalletBinding();
        existing.setBindingId("bnd_existing");
        existing.setAccountId(1L);
        existing.setChannel("WECHAT");
        when(walletBindingMapper.selectByAccountAndChannel(1L, "WECHAT")).thenReturn(existing);
        when(idempotencyRecordMapper.insertIgnore(anyString(), anyString(), anyInt(), anyString())).thenReturn(1);

        String bindingId = flow.bind(1L, "WECHAT", "6222021234567890", "张三", "k-dup");

        assertThat(bindingId).isEqualTo("bnd_existing");
        verify(walletBindingMapper).markBound("bnd_existing");
        verify(walletBindingMapper, never()).insert(any());
    }

    @Test
    @DisplayName("UT-C05: 解绑置 UNBOUND（markUnbound）")
    void ut_unbindMarksUnbound() {
        WalletBinding binding = new WalletBinding();
        binding.setBindingId("bnd_1");
        binding.setAccountId(1L);
        when(walletBindingMapper.selectById("bnd_1")).thenReturn(binding);

        flow.unbind(1L, "bnd_1");

        verify(walletBindingMapper).markUnbound("bnd_1", NOW);
    }

    @Test
    @DisplayName("UT-C08: 越权解绑他人 binding → 2002")
    void ut_unbindOtherAccountForbidden() {
        WalletBinding binding = new WalletBinding();
        binding.setBindingId("bnd_1");
        binding.setAccountId(2L);
        when(walletBindingMapper.selectById("bnd_1")).thenReturn(binding);

        assertThatThrownBy(() -> flow.unbind(1L, "bnd_1"))
                .isInstanceOfSatisfying(AccBusinessException.class,
                        e -> assertThat(e.code()).isEqualTo(2002));
        verify(walletBindingMapper, never()).markUnbound(anyString(), any());
    }

    @Test
    @DisplayName("UT-C07: IdempotencyGuard 同 key 第二次返回首次结果")
    void ut_idempotencyKeyReturnsFirstResult() {
        when(accountMapper.selectById(1L)).thenReturn(account(1L, "REALNAMED", "张三"));
        when(walletBindingMapper.selectByAccountAndChannel(1L, "WECHAT")).thenReturn(null);
        when(idGenerator.nextId()).thenReturn(30L);
        when(idempotencyRecordMapper.insertIgnore(anyString(), anyString(), anyInt(), anyString()))
                .thenReturn(1, 0);
        IdempotencyRecord record = new IdempotencyRecord();
        record.setResponsePayload("bnd_30");
        when(idempotencyRecordMapper.selectByKey("k-idem")).thenReturn(record);

        String first = flow.bind(1L, "WECHAT", "6222021234567890", "张三", "k-idem");
        String second = flow.bind(1L, "WECHAT", "6222021234567890", "张三", "k-idem");

        assertThat(first).isEqualTo("bnd_30");
        assertThat(second).isEqualTo("bnd_30");
        verify(walletBindingMapper, times(1)).insert(any());
    }

    private static Account account(long id, String realNameStatus, String realName) {
        Account account = new Account();
        account.setAccountId(id);
        account.setRealNameStatus(realNameStatus);
        account.setRealName(realName);
        return account;
    }

    private static final class FakePaymentChannelPort implements PaymentChannelPort {
        private boolean fail;

        @Override
        public void verifyPayee(long accountId, String channel, String payeeAccount, String realName) {
            if (fail) {
                throw new AccBusinessException(4002, "通道失败 / 超时");
            }
        }
    }
}
