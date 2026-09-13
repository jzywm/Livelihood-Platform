package com.msz.acc.application;

import com.msz.acc.application.port.SignatureVerifier;
import com.msz.acc.domain.model.Account;
import com.msz.acc.domain.model.RealNameStatus;
import com.msz.acc.domain.model.RealnameRecord;
import com.msz.acc.domain.service.RealnameStatusMachine;
import com.msz.acc.domain.support.AccBusinessException;
import com.msz.acc.repository.AccountMapper;
import com.msz.acc.repository.RealnameRecordMapper;
import com.msz.common.idgen.IdGenerator;

import java.time.Clock;

/**
 * 实名回调流程（4.2）：验签 + 时间戳窗口 + nonce、bizId 幂等、uk_open_id 判重、状态机迁移、
 * pass=false 失败路径、建户回填 account_id/callback_at/open_id/name/id_no。
 *
 * <p>建户 mobile 口径：er.md account.mobile NOT NULL 与 openapi 回调报文无 mobile 存在既定张力，
 * M1 最小处理为 account.mobile 置空串、mobileHash 置 NULL（列可空）；后续补全路径不属本变更。</p>
 */
public final class RealnameCallbackFlow {

    private static final long TIMESTAMP_WINDOW_SECONDS = 300L;
    private static final int NONCE_MIN_LENGTH = 8;
    private static final int NONCE_MAX_LENGTH = 64;
    private static final String DEFAULT_ROLE = "CONSUMER";

    private final SignatureVerifier signatureVerifier;
    private final RealnameRecordMapper realnameRecordMapper;
    private final AccountMapper accountMapper;
    private final IdGenerator idGenerator;
    private final RealnameStatusMachine statusMachine;
    private final Clock clock;

    public RealnameCallbackFlow(SignatureVerifier signatureVerifier, RealnameRecordMapper realnameRecordMapper,
                                AccountMapper accountMapper, IdGenerator idGenerator,
                                RealnameStatusMachine statusMachine, Clock clock) {
        this.signatureVerifier = signatureVerifier;
        this.realnameRecordMapper = realnameRecordMapper;
        this.accountMapper = accountMapper;
        this.idGenerator = idGenerator;
        this.statusMachine = statusMachine;
        this.clock = clock;
    }

    public CallbackResult handle(RealnameCallbackRequest req) {
        // ① 时间戳窗口 ±300s
        if (Math.abs(clock.instant().getEpochSecond() - req.timestamp()) > TIMESTAMP_WINDOW_SECONDS) {
            throw new AccBusinessException(1003, "回调时间戳超窗");
        }
        // ② nonce 长度 8~64
        if (req.nonce() == null || req.nonce().length() < NONCE_MIN_LENGTH
                || req.nonce().length() > NONCE_MAX_LENGTH) {
            throw new AccBusinessException(1003, "回调 nonce 长度非法");
        }
        // ③ 验签失败 → 拒收，状态不变
        if (!signatureVerifier.verify(canonicalPayload(req), req.sign())) {
            throw new AccBusinessException(4001, "验签失败");
        }
        // ④ 按 bizId 查 record
        RealnameRecord record = realnameRecordMapper.selectByBizId(req.bizId());
        if (record == null) {
            throw new AccBusinessException(3006, "实名业务单不存在");
        }
        if (RealNameStatus.REALNAMED.name().equals(record.getStatus())) {
            return new CallbackResult(req.bizId(), RealNameStatus.REALNAMED.name(), record.getAccountId());
        }
        // ⑤ openId 判重：命中其他 bizId 且已 REALNAMED → 幂等返回原账户
        RealnameRecord byOpenId = realnameRecordMapper.selectByOpenId(req.openId());
        if (byOpenId != null && !byOpenId.getBizId().equals(req.bizId())
                && RealNameStatus.REALNAMED.name().equals(byOpenId.getStatus())) {
            return new CallbackResult(byOpenId.getBizId(), RealNameStatus.REALNAMED.name(), byOpenId.getAccountId());
        }
        // ⑥ pass=false：callback_at 回填、状态保持 REALNAMING（可重试），open_id/name/id_no 保持原值
        if (!req.pass()) {
            realnameRecordMapper.updateCallback(req.bizId(), RealNameStatus.REALNAMING.name(), null, clock.instant(),
                    record.getOpenId(), record.getName(), record.getIdNo());
            return new CallbackResult(req.bizId(), RealNameStatus.REALNAMING.name(), null);
        }
        // ⑦ pass=true：状态机迁移 → 建户（name/id_no 明文透传，落库加密由 typeHandler 承担）→ 回填
        RealNameStatus newStatus = statusMachine.onCallbackPass(statusOf(record.getStatus()));
        long accountId = idGenerator.nextId();
        Account account = new Account();
        account.setAccountId(accountId);
        account.setRole(DEFAULT_ROLE);
        account.setMobile("");
        account.setRealNameStatus(newStatus.name());
        account.setWalletStatus("ACTIVE");
        account.setRealName(req.name());
        account.setIdNo(req.idNo());
        account.setCreatedAt(clock.instant());
        accountMapper.insert(account);
        realnameRecordMapper.updateCallback(req.bizId(), newStatus.name(), accountId, clock.instant(),
                req.openId(), req.name(), req.idNo());
        return new CallbackResult(req.bizId(), newStatus.name(), accountId);
    }

    /** 通道不可用（红线 R-02 不降级）：REALNAMING → SUSPENDED，供 5.x 通道故障处理复用。 */
    public CallbackResult suspendOnChannelUnavailable(String bizId) {
        RealnameRecord record = realnameRecordMapper.selectByBizId(bizId);
        if (record == null) {
            throw new AccBusinessException(3006, "实名业务单不存在");
        }
        RealNameStatus newStatus = statusMachine.suspend(statusOf(record.getStatus()));
        realnameRecordMapper.updateCallback(bizId, newStatus.name(), record.getAccountId(), clock.instant(),
                record.getOpenId(), record.getName(), record.getIdNo());
        return new CallbackResult(bizId, newStatus.name(), record.getAccountId());
    }

    private String canonicalPayload(RealnameCallbackRequest req) {
        return req.bizId() + "|" + req.openId() + "|" + req.name() + "|" + req.idNo() + "|"
                + req.pass() + "|" + req.timestamp() + "|" + req.nonce();
    }

    private static RealNameStatus statusOf(String status) {
        if (status == null) {
            return null;
        }
        try {
            return RealNameStatus.valueOf(status);
        } catch (IllegalArgumentException e) {
            return null;
        }
    }
}
