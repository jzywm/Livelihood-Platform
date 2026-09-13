package com.msz.acc.application;

import com.msz.acc.domain.model.Account;
import com.msz.acc.domain.model.RealNameStatus;
import com.msz.acc.domain.model.RealnameRecord;
import com.msz.acc.domain.support.AccBusinessException;
import com.msz.acc.repository.AccountMapper;
import com.msz.acc.repository.RealnameRecordMapper;

import java.time.Clock;
import java.time.Instant;
import java.util.List;

/**
 * 注销流程（4.6）：无进行中业务校验、closed_at/close_reason 软关闭留痕（不物理删除）。
 */
public final class CloseFlow {

    private final AccountMapper accountMapper;
    private final RealnameRecordMapper realnameRecordMapper;
    private final Clock clock;

    public CloseFlow(AccountMapper accountMapper, RealnameRecordMapper realnameRecordMapper, Clock clock) {
        this.accountMapper = accountMapper;
        this.realnameRecordMapper = realnameRecordMapper;
        this.clock = clock;
    }

    public Instant close(long accountId, String reason) {
        Account account = accountMapper.selectById(accountId);
        if (account == null) {
            throw new AccBusinessException(3006, "账户不存在");
        }
        List<RealnameRecord> pending = realnameRecordMapper.selectByAccountIdAndStatus(
                accountId, RealNameStatus.REALNAMING.name());
        if (pending != null && !pending.isEmpty()) {
            throw new AccBusinessException(3007, "存在进行中的实名业务，禁止注销");
        }
        Instant closedAt = clock.instant();
        accountMapper.softClose(accountId, reason, closedAt);
        return closedAt;
    }
}
