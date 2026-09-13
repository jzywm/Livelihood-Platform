package com.msz.acc.application;

import com.msz.acc.application.port.CaptchaPort;
import com.msz.acc.application.port.RealnameChannelPort;
import com.msz.acc.application.support.HmacFingerprint;
import com.msz.acc.domain.model.Account;
import com.msz.acc.domain.model.RealNameStatus;
import com.msz.acc.domain.model.RealnameRecord;
import com.msz.acc.domain.support.AccBusinessException;
import com.msz.acc.repository.AccountMapper;
import com.msz.acc.repository.RealnameRecordMapper;
import com.msz.common.idgen.IdGenerator;

import java.time.Clock;
import java.util.regex.Pattern;

/**
 * 注册发起流程（4.1）：captcha 一次性消费 + mobile_hash 判重（幂等命中）+ 建实名业务单 + 调通道授权。
 */
public final class RegisterFlow {

    private static final Pattern MOBILE_PATTERN = Pattern.compile("^1[3-9]\\d{9}$");
    private static final String DEFAULT_CHANNEL = "WECHAT";

    private final CaptchaPort captchaPort;
    private final RealnameChannelPort realnameChannelPort;
    private final AccountMapper accountMapper;
    private final RealnameRecordMapper realnameRecordMapper;
    private final IdGenerator idGenerator;
    private final Clock clock;

    public RegisterFlow(CaptchaPort captchaPort, RealnameChannelPort realnameChannelPort,
                        AccountMapper accountMapper, RealnameRecordMapper realnameRecordMapper,
                        IdGenerator idGenerator, Clock clock) {
        this.captchaPort = captchaPort;
        this.realnameChannelPort = realnameChannelPort;
        this.accountMapper = accountMapper;
        this.realnameRecordMapper = realnameRecordMapper;
        this.idGenerator = idGenerator;
        this.clock = clock;
    }

    public RegisterResult register(String mobile, String role, String captchaToken) {
        if (mobile == null || !MOBILE_PATTERN.matcher(mobile).matches()) {
            throw new AccBusinessException(1002, "手机号格式非法");
        }
        if (captchaToken != null && !captchaToken.isEmpty()) {
            captchaPort.consumeToken(captchaToken);
        }
        Account existing = accountMapper.selectByMobileHash(HmacFingerprint.sha256Hex(mobile));
        if (existing != null && RealNameStatus.REALNAMED.name().equals(existing.getRealNameStatus())) {
            return new RegisterResult(existing.getAccountId(), null, null, RealNameStatus.REALNAMED.name(), true);
        }

        String bizId = "rz_" + idGenerator.nextId();
        RealnameRecord record = new RealnameRecord();
        record.setBizId(bizId);
        record.setChannel(DEFAULT_CHANNEL);
        record.setStatus(RealNameStatus.REALNAMING.name());
        record.setLevel("BASE");
        record.setCreatedAt(clock.instant());
        realnameRecordMapper.insert(record);

        String authorizeUrl = realnameChannelPort.requestAuthorization(bizId, mobile, role);
        return new RegisterResult(null, bizId, authorizeUrl, RealNameStatus.REALNAMING.name(), false);
    }
}
