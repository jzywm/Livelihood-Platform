package com.msz.acc.controller;

import com.msz.acc.application.RecordFlowRequest;
import com.msz.acc.application.RecordFlowService;
import com.msz.acc.config.AccProperties;
import com.msz.acc.controller.dto.AccountView;
import com.msz.acc.controller.dto.WalletFlowView;
import com.msz.acc.controller.support.ControllerSupport;
import com.msz.acc.domain.model.Account;
import com.msz.acc.domain.model.WalletFlow;
import com.msz.acc.domain.service.MaskingPolicy;
import com.msz.acc.domain.support.AccBusinessException;
import com.msz.acc.infrastructure.web.TraceIds;
import com.msz.acc.repository.AccountMapper;
import com.msz.common.api.Envelope;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.time.Instant;

/**
 * 服务端间 internal 接口（/acc/internal/**）：统一 X-Internal-Token 鉴权（不匹配 → 403），
 * 网关不暴露。getRealname/getAccount（脱敏）+ recordFlow（幂等按 channelOrderNo）。
 */
@RestController
@RequestMapping("/acc/internal")
public class InternalController {

    private final AccountMapper accountMapper;
    private final RecordFlowService recordFlowService;
    private final MaskingPolicy maskingPolicy;
    private final AccProperties properties;

    public InternalController(AccountMapper accountMapper, RecordFlowService recordFlowService,
                              MaskingPolicy maskingPolicy, AccProperties properties) {
        this.accountMapper = accountMapper;
        this.recordFlowService = recordFlowService;
        this.maskingPolicy = maskingPolicy;
        this.properties = properties;
    }

    @GetMapping("/realname/{accountId}")
    public Envelope<RealnameView> getRealname(@PathVariable long accountId, HttpServletRequest request) {
        ControllerSupport.requireInternalToken(request, properties.getInternalToken());
        Account account = requireAccount(accountId);
        RealnameView data = new RealnameView("acc_" + account.getAccountId(), account.getRealNameStatus(),
                maskingPolicy.maskName(account.getRealName()), maskingPolicy.maskIdNo(account.getIdNo()));
        return Envelope.ok(data, TraceIds.of(request));
    }

    @GetMapping("/account/{accountId}")
    public Envelope<AccountView> getAccount(@PathVariable long accountId, HttpServletRequest request) {
        ControllerSupport.requireInternalToken(request, properties.getInternalToken());
        Account account = requireAccount(accountId);
        AccountView data = new AccountView("acc_" + account.getAccountId(), account.getRole(),
                account.getRealNameStatus(), account.getWalletStatus(),
                maskingPolicy.maskMobile(account.getMobile()),
                maskingPolicy.maskName(account.getRealName()),
                account.getCreatedAt());
        return Envelope.ok(data, TraceIds.of(request));
    }

    @PostMapping("/wallet/flows")
    public Envelope<WalletFlowView> recordFlow(@RequestBody RecordFlowBody body, HttpServletRequest request) {
        ControllerSupport.requireInternalToken(request, properties.getInternalToken());
        if (body.accountId() == null) {
            throw new AccBusinessException(1001, "accountId 缺失");
        }
        if (body.type() == null || !ControllerSupport.FLOW_TYPES.contains(body.type())) {
            throw new AccBusinessException(1003, "type 枚举非法");
        }
        if (body.direction() == null || !ControllerSupport.DIRECTIONS.contains(body.direction())) {
            throw new AccBusinessException(1003, "direction 枚举非法（IN/OUT）");
        }
        if (body.occurredAt() == null) {
            throw new AccBusinessException(1001, "occurredAt 缺失");
        }
        WalletFlow flow = recordFlowService.recordFlow(new RecordFlowRequest(
                body.accountId(), body.type(), body.direction(), body.amount(),
                body.channelOrderNo(), body.bizType(), body.occurredAt()));
        return Envelope.ok(WalletFlowView.of(flow), TraceIds.of(request));
    }

    private Account requireAccount(long accountId) {
        Account account = accountMapper.selectById(accountId);
        if (account == null) {
            throw new AccBusinessException(3006, "账户不存在");
        }
        return account;
    }

    /** internal 实名查询结果（脱敏）。 */
    public record RealnameView(String accountId, String realNameStatus, String realName, String idNo) {
    }

    /** internal 记账请求（RecordFlowRequest，幂等按 channelOrderNo）。 */
    public record RecordFlowBody(Long accountId, String type, String direction, String amount,
                                 String channelOrderNo, String bizType, Instant occurredAt) {
    }
}
