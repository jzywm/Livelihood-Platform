package com.msz.acc.application;

import com.msz.acc.application.port.PaymentChannelPort;
import com.msz.acc.domain.model.Account;
import com.msz.acc.domain.model.BindingStatus;
import com.msz.acc.domain.model.RealNameStatus;
import com.msz.acc.domain.model.WalletBinding;
import com.msz.acc.domain.support.AccBusinessException;
import com.msz.acc.infrastructure.crypto.AesGcmCipher;
import com.msz.acc.repository.AccountMapper;
import com.msz.acc.repository.IdempotencyGuard;
import com.msz.acc.repository.IdempotencyRecordMapper;
import com.msz.acc.repository.WalletBindingMapper;
import com.msz.common.idgen.IdGenerator;

import java.time.Clock;
import java.util.Objects;

/**
 * 收款账户绑定流程（4.5）：实名校验 3001/3002、通道校验 4002 可重试、复用原行幂等、解绑置 UNBOUND。
 */
public final class BindFlow {

    private static final String PII_KEY_ID = "pii";
    private static final String SCENE = "bind";

    private final AccountMapper accountMapper;
    private final WalletBindingMapper walletBindingMapper;
    private final PaymentChannelPort paymentChannelPort;
    private final AesGcmCipher cipher;
    private final IdempotencyGuard idempotencyGuard;
    private final IdGenerator idGenerator;
    private final Clock clock;

    public BindFlow(AccountMapper accountMapper, WalletBindingMapper walletBindingMapper,
                    PaymentChannelPort paymentChannelPort, AesGcmCipher cipher,
                    IdempotencyRecordMapper idempotencyRecordMapper, IdGenerator idGenerator, Clock clock) {
        this.accountMapper = accountMapper;
        this.walletBindingMapper = walletBindingMapper;
        this.paymentChannelPort = paymentChannelPort;
        this.cipher = cipher;
        this.idempotencyGuard = new IdempotencyGuard(idempotencyRecordMapper, () -> "");
        this.idGenerator = idGenerator;
        this.clock = clock;
    }

    public String bind(long accountId, String channel, String payeeAccount, String payeeName, String idempotencyKey) {
        Account account = requireRealnamedAccount(accountId);
        validatePayeeName(account.getRealName(), payeeName);
        return idempotencyGuard.execute(SCENE, idempotencyKey,
                () -> doBind(account, channel, payeeAccount, payeeName));
    }

    public void unbind(long accountId, String bindingId) {
        WalletBinding binding = walletBindingMapper.selectById(bindingId);
        if (binding == null) {
            throw new AccBusinessException(3006, "绑定不存在");
        }
        if (binding.getAccountId() != accountId) {
            throw new AccBusinessException(2002, "越权操作他人绑定");
        }
        walletBindingMapper.markUnbound(bindingId, clock.instant());
    }

    public String replace(long accountId, String bindingId, String channel, String payeeAccount,
                          String payeeName, String idempotencyKey) {
        Account account = requireRealnamedAccount(accountId);
        validatePayeeName(account.getRealName(), payeeName);
        // 先校验新通道（失败/超时 4002 可重试）
        paymentChannelPort.verifyPayee(accountId, channel, payeeAccount, account.getRealName());
        return idempotencyGuard.execute(SCENE, idempotencyKey, () -> {
            WalletBinding existing = walletBindingMapper.selectByAccountAndChannel(accountId, channel);
            if (existing != null) {
                walletBindingMapper.markBound(existing.getBindingId());
                return existing.getBindingId();
            }
            return insertBinding(accountId, channel, payeeAccount, payeeName);
        });
    }

    /** 平台侧实名与户名比对：一致 true，否则抛 3002（实名不匹配）。 */
    public static boolean validatePayeeName(String realName, String payeeName) {
        if (Objects.equals(realName, payeeName)) {
            return true;
        }
        throw new AccBusinessException(3002, "实名不匹配");
    }

    private String doBind(Account account, String channel, String payeeAccount, String payeeName) {
        WalletBinding existing = walletBindingMapper.selectByAccountAndChannel(account.getAccountId(), channel);
        if (existing != null) {
            walletBindingMapper.markBound(existing.getBindingId());
            return existing.getBindingId();
        }
        paymentChannelPort.verifyPayee(account.getAccountId(), channel, payeeAccount, account.getRealName());
        return insertBinding(account.getAccountId(), channel, payeeAccount, payeeName);
    }

    private String insertBinding(long accountId, String channel, String payeeAccount, String payeeName) {
        WalletBinding binding = new WalletBinding();
        binding.setBindingId("bnd_" + idGenerator.nextId());
        binding.setAccountId(accountId);
        binding.setChannel(channel);
        binding.setPayeeAccount(cipher.encrypt(PII_KEY_ID, payeeAccount));
        binding.setPayeeName(cipher.encrypt(PII_KEY_ID, payeeName));
        binding.setStatus(BindingStatus.BOUND.name());
        binding.setCreatedAt(clock.instant());
        walletBindingMapper.insert(binding);
        return binding.getBindingId();
    }

    private Account requireRealnamedAccount(long accountId) {
        Account account = accountMapper.selectById(accountId);
        if (account == null) {
            throw new AccBusinessException(3006, "账户不存在");
        }
        if (!RealNameStatus.REALNAMED.name().equals(account.getRealNameStatus())) {
            throw new AccBusinessException(3001, "实名未完成");
        }
        return account;
    }
}
