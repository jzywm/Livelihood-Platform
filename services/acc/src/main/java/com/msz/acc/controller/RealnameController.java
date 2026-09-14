package com.msz.acc.controller;

import com.msz.acc.application.CallbackResult;
import com.msz.acc.application.RealnameCallbackFlow;
import com.msz.acc.application.RealnameCallbackRequest;
import com.msz.acc.application.RegisterFlow;
import com.msz.acc.application.RegisterResult;
import com.msz.acc.config.AccProperties;
import com.msz.acc.controller.support.ControllerSupport;
import com.msz.acc.domain.model.Account;
import com.msz.acc.domain.model.RealnameRecord;
import com.msz.acc.domain.service.MaskingPolicy;
import com.msz.acc.domain.support.AccBusinessException;
import com.msz.acc.infrastructure.auth.AuthContext;
import com.msz.acc.infrastructure.web.TraceIds;
import com.msz.acc.repository.AccountMapper;
import com.msz.acc.repository.RealnameRecordMapper;
import com.msz.common.api.Envelope;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/**
 * 实名接口（openapi /acc/register、/acc/realname/status、/acc/realname/nfc + x-external 回调
 * POST /acc/realname/callback——仅内网 + 验签 + 幂等，受理即返 200）。
 */
@RestController
public class RealnameController {

    private final RegisterFlow registerFlow;
    private final RealnameCallbackFlow realnameCallbackFlow;
    private final RealnameRecordMapper realnameRecordMapper;
    private final AccountMapper accountMapper;
    private final MaskingPolicy maskingPolicy;
    private final AccProperties properties;

    public RealnameController(RegisterFlow registerFlow, RealnameCallbackFlow realnameCallbackFlow,
                              RealnameRecordMapper realnameRecordMapper, AccountMapper accountMapper,
                              MaskingPolicy maskingPolicy, AccProperties properties) {
        this.registerFlow = registerFlow;
        this.realnameCallbackFlow = realnameCallbackFlow;
        this.realnameRecordMapper = realnameRecordMapper;
        this.accountMapper = accountMapper;
        this.maskingPolicy = maskingPolicy;
        this.properties = properties;
    }

    @PostMapping("/acc/register")
    public Envelope<RegisterView> register(@RequestBody RegisterBody body, HttpServletRequest request) {
        if (body.mobile() == null || body.mobile().isBlank()) {
            throw new AccBusinessException(1001, "mobile 缺失");
        }
        if (body.role() == null || body.role().isBlank()) {
            throw new AccBusinessException(1001, "role 缺失");
        }
        if (!ControllerSupport.ROLES.contains(body.role())) {
            throw new AccBusinessException(1003, "role 枚举非法");
        }
        RegisterResult result = registerFlow.register(body.mobile(), body.role(),
                body.captchaToken() == null || body.captchaToken().isBlank() ? null : body.captchaToken());
        RegisterView data = new RegisterView(result.bizId(), result.authorizeUrl(), result.realNameStatus(),
                result.accountId() == null ? null : "acc_" + result.accountId());
        return Envelope.ok(data, TraceIds.of(request));
    }

    @GetMapping("/acc/realname/status")
    public Envelope<RealnameStatusView> status(@RequestParam("bizId") String bizId, HttpServletRequest request) {
        RealnameRecord record = realnameRecordMapper.selectByBizId(bizId);
        if (record == null) {
            throw new AccBusinessException(3006, "实名业务单不存在");
        }
        RealnameStatusView data = new RealnameStatusView(
                record.getAccountId() == null ? null : "acc_" + record.getAccountId(),
                record.getStatus(),
                maskingPolicy.maskName(record.getName()),
                maskingPolicy.maskIdNo(record.getIdNo()));
        return Envelope.ok(data, TraceIds.of(request));
    }

    /** NFC 为 M2 占位（裁决）：契约符合（200 Envelope）；未基础实名 → 3001；否则返回 BASE（M2 前不真正增强）。 */
    @PostMapping("/acc/realname/nfc")
    public Envelope<NfcResultView> nfc(@RequestBody NfcBody body, HttpServletRequest request) {
        if (body.idCard() == null || body.idCard().isBlank()) {
            throw new AccBusinessException(1001, "idCard 缺失");
        }
        if (body.faceToken() == null || body.faceToken().isBlank()) {
            throw new AccBusinessException(1001, "faceToken 缺失");
        }
        AuthContext ctx = ControllerSupport.requireAuth(request);
        Account account = accountMapper.selectById(ControllerSupport.accountIdOf(ctx));
        if (account == null) {
            throw new AccBusinessException(3006, "账户不存在");
        }
        if (!"REALNAMED".equals(account.getRealNameStatus())) {
            throw new AccBusinessException(3001, "实名未完成");
        }
        return Envelope.ok(new NfcResultView("BASE"), TraceIds.of(request));
    }

    /** 第三方实名回调：内部 Token → 报文必填 → 验签 + 时间戳窗口 + 幂等（受理即返 200）。 */
    @PostMapping("/acc/realname/callback")
    public Envelope<CallbackView> callback(@RequestBody CallbackBody body, HttpServletRequest request) {
        ControllerSupport.requireInternalToken(request, properties.getInternalToken());
        if (body.bizId() == null || body.bizId().isBlank()) {
            throw new AccBusinessException(1001, "bizId 缺失");
        }
        if (body.openId() == null || body.openId().isBlank()) {
            throw new AccBusinessException(1001, "openId 缺失");
        }
        if (body.name() == null || body.name().isBlank()) {
            throw new AccBusinessException(1001, "name 缺失");
        }
        if (body.idNo() == null || body.idNo().isBlank()) {
            throw new AccBusinessException(1001, "idNo 缺失");
        }
        if (body.pass() == null) {
            throw new AccBusinessException(1001, "pass 缺失");
        }
        if (body.sign() == null || body.sign().isBlank()) {
            throw new AccBusinessException(1001, "sign 缺失");
        }
        if (body.timestamp() == null) {
            throw new AccBusinessException(1001, "timestamp 缺失");
        }
        if (body.nonce() == null || body.nonce().isBlank()) {
            throw new AccBusinessException(1001, "nonce 缺失");
        }
        CallbackResult result = realnameCallbackFlow.handle(new RealnameCallbackRequest(
                body.bizId(), body.openId(), body.name(), body.idNo(), body.pass(), body.sign(),
                body.timestamp(), body.nonce()));
        CallbackView data = new CallbackView(result.bizId(), result.status(),
                result.accountId() == null ? null : "acc_" + result.accountId());
        return Envelope.ok(data, TraceIds.of(request));
    }

    /** openapi RegisterRequest。 */
    public record RegisterBody(String mobile, String role, String captchaToken) {
    }

    /** openapi RegisterResult。 */
    public record RegisterView(String bizId, String authorizeUrl, String realNameStatus, String accountId) {
    }

    /** openapi RealnameStatusResult（realName/idNo 脱敏）。 */
    public record RealnameStatusView(String accountId, String realNameStatus, String realName, String idNo) {
    }

    /** openapi NfcRealnameRequest。 */
    public record NfcBody(String idCard, String faceToken) {
    }

    /** openapi NfcRealnameResult（M2 占位恒 BASE）。 */
    public record NfcResultView(String realNameLevel) {
    }

    /** 回调受理结果。 */
    public record CallbackView(String bizId, String status, String accountId) {
    }

    /** 第三方回调报文（timestamp epoch 秒 + nonce，验签规范化 payload 必需）。 */
    public record CallbackBody(String bizId, String openId, String name, String idNo, Boolean pass,
                               String sign, Long timestamp, String nonce) {
    }
}
