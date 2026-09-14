package com.msz.acc.controller;

import com.msz.acc.application.CloseFlow;
import com.msz.acc.controller.dto.AccountView;
import com.msz.acc.controller.support.ControllerSupport;
import com.msz.acc.domain.model.Account;
import com.msz.acc.domain.service.MaskingPolicy;
import com.msz.acc.domain.support.AccBusinessException;
import com.msz.acc.infrastructure.auth.AuthContext;
import com.msz.acc.infrastructure.web.TraceIds;
import com.msz.acc.repository.AccountMapper;
import com.msz.common.api.Envelope;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

import java.time.Instant;

/**
 * 账号与安全接口（openapi /acc/me、/acc/account/close）：当前用户信息（脱敏）+ 注销留痕。
 */
@RestController
public class AccountController {

    private final AccountMapper accountMapper;
    private final CloseFlow closeFlow;
    private final MaskingPolicy maskingPolicy;

    public AccountController(AccountMapper accountMapper, CloseFlow closeFlow, MaskingPolicy maskingPolicy) {
        this.accountMapper = accountMapper;
        this.closeFlow = closeFlow;
        this.maskingPolicy = maskingPolicy;
    }

    @GetMapping("/acc/me")
    public Envelope<AccountView> me(HttpServletRequest request) {
        AuthContext ctx = ControllerSupport.requireAuth(request);
        Account account = accountMapper.selectById(ControllerSupport.accountIdOf(ctx));
        if (account == null) {
            throw new AccBusinessException(3006, "账户不存在");
        }
        return Envelope.ok(accountViewOf(account), TraceIds.of(request));
    }

    @PostMapping("/acc/account/close")
    public Envelope<CloseView> close(@RequestBody CloseBody body, HttpServletRequest request) {
        AuthContext ctx = ControllerSupport.requireAuth(request);
        long accountId = ControllerSupport.accountIdOf(ctx);
        Instant closedAt = closeFlow.close(accountId, body.reason());
        return Envelope.ok(new CloseView("acc_" + accountId, closedAt.toString()), TraceIds.of(request));
    }

    private AccountView accountViewOf(Account account) {
        return new AccountView("acc_" + account.getAccountId(), account.getRole(),
                account.getRealNameStatus(), account.getWalletStatus(),
                maskingPolicy.maskMobile(account.getMobile()),
                maskingPolicy.maskName(account.getRealName()),
                account.getCreatedAt());
    }

    /** openapi AccountCloseRequest。 */
    public record CloseBody(String reason) {
    }

    /** openapi /acc/account/close 响应。 */
    public record CloseView(String accountId, String closedAt) {
    }
}
