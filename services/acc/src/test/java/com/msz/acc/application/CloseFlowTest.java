package com.msz.acc.application;

import com.msz.acc.domain.model.Account;
import com.msz.acc.domain.model.RealnameRecord;
import com.msz.acc.domain.support.AccBusinessException;
import com.msz.acc.repository.AccountMapper;
import com.msz.acc.repository.RealnameRecordMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * CloseFlowTest（UT-F08 口径）：软关闭留痕、行不删；有 REALNAMING 记录 → 3007；不存在 3006。
 */
class CloseFlowTest {

    private static final Instant NOW = Instant.parse("2026-01-15T00:00:00Z");

    private AccountMapper accountMapper;
    private RealnameRecordMapper realnameRecordMapper;
    private CloseFlow flow;

    @BeforeEach
    void setUp() {
        accountMapper = mock(AccountMapper.class);
        realnameRecordMapper = mock(RealnameRecordMapper.class);
        Clock clock = Clock.fixed(NOW, ZoneOffset.UTC);
        flow = new CloseFlow(accountMapper, realnameRecordMapper, clock);
    }

    @Test
    @DisplayName("UT-F08: 软关闭留痕（closed_at/close_reason），行不物理删除")
    void ut_closeSoftClosesAndKeepsTrace() {
        when(accountMapper.selectById(1L)).thenReturn(account(1L));
        when(realnameRecordMapper.selectByAccountIdAndStatus(1L, "REALNAMING")).thenReturn(List.of());

        Instant closedAt = flow.close(1L, "用户主动注销");

        assertThat(closedAt).isEqualTo(NOW);
        verify(accountMapper).softClose(1L, "用户主动注销", NOW);
    }

    @Test
    @DisplayName("存在 REALNAMING 进行中实名记录 → 3007")
    void ut_closeRejectedWhenRealnamingInProgress() {
        when(accountMapper.selectById(1L)).thenReturn(account(1L));
        when(realnameRecordMapper.selectByAccountIdAndStatus(1L, "REALNAMING"))
                .thenReturn(List.of(new RealnameRecord()));

        assertThatThrownBy(() -> flow.close(1L, "x"))
                .isInstanceOfSatisfying(AccBusinessException.class,
                        e -> assertThat(e.code()).isEqualTo(3007));
        verify(accountMapper, never()).softClose(anyLong(), anyString(), any());
    }

    @Test
    @DisplayName("账户不存在 → 3006")
    void ut_closeMissingAccountRejected() {
        when(accountMapper.selectById(99L)).thenReturn(null);

        assertThatThrownBy(() -> flow.close(99L, "x"))
                .isInstanceOfSatisfying(AccBusinessException.class,
                        e -> assertThat(e.code()).isEqualTo(3006));
        verify(accountMapper, never()).softClose(anyLong(), anyString(), any());
    }

    private static Account account(long id) {
        Account account = new Account();
        account.setAccountId(id);
        account.setRealNameStatus("REALNAMED");
        return account;
    }
}
