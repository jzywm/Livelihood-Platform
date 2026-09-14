package com.msz.acc.controller;

import com.msz.acc.application.BindFlow;
import com.msz.acc.controller.dto.BindingView;
import com.msz.acc.controller.support.ControllerSupport;
import com.msz.acc.domain.model.Account;
import com.msz.acc.domain.model.WalletBinding;
import com.msz.acc.domain.service.MaskingPolicy;
import com.msz.acc.domain.support.AccBusinessException;
import com.msz.acc.infrastructure.auth.AuthContext;
import com.msz.acc.infrastructure.web.TraceIds;
import com.msz.acc.repository.AccountMapper;
import com.msz.acc.repository.WalletBindingMapper;
import com.msz.common.api.ApiConventions;
import com.msz.common.api.Envelope;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

/**
 * 收款账户绑定接口（openapi /acc/wallet/bind、/bindings、/bindings/{bindingId} PUT/DELETE）：
 * payeeAccount/payeeName 输出脱敏；资金类写操作 Idempotency-Key 强制。
 */
@RestController
public class BindingController {

    private final BindFlow bindFlow;
    private final AccountMapper accountMapper;
    private final WalletBindingMapper walletBindingMapper;
    private final MaskingPolicy maskingPolicy;

    public BindingController(BindFlow bindFlow, AccountMapper accountMapper,
                             WalletBindingMapper walletBindingMapper, MaskingPolicy maskingPolicy) {
        this.bindFlow = bindFlow;
        this.accountMapper = accountMapper;
        this.walletBindingMapper = walletBindingMapper;
        this.maskingPolicy = maskingPolicy;
    }

    @PostMapping("/acc/wallet/bind")
    public Envelope<BindingView> bind(@RequestBody BindBody body,
                                      @RequestHeader(value = ApiConventions.IDEMPOTENCY_KEY_HEADER, required = false)
                                      String idempotencyKey,
                                      HttpServletRequest request) {
        AuthContext ctx = ControllerSupport.requireAuth(request);
        long accountId = ControllerSupport.accountIdOf(ctx);
        validateBindBody(body);
        requireIdempotencyKey(idempotencyKey);

        String bindingId = bindFlow.bind(accountId, body.channel(), body.payeeAccount(),
                payeeNameOf(accountId), idempotencyKey);
        return Envelope.ok(bindingViewOf(bindingId), TraceIds.of(request));
    }

    @GetMapping("/acc/wallet/bindings")
    public Envelope<List<BindingView>> bindings(HttpServletRequest request) {
        AuthContext ctx = ControllerSupport.requireAuth(request);
        List<BindingView> views = walletBindingMapper.listByAccount(ControllerSupport.accountIdOf(ctx)).stream()
                .map(binding -> BindingView.of(binding, maskingPolicy))
                .toList();
        return Envelope.ok(views, TraceIds.of(request));
    }

    @PutMapping("/acc/wallet/bindings/{bindingId}")
    public Envelope<BindingView> replace(@PathVariable String bindingId,
                                         @RequestBody BindBody body,
                                         @RequestHeader(value = ApiConventions.IDEMPOTENCY_KEY_HEADER, required = false)
                                         String idempotencyKey,
                                         HttpServletRequest request) {
        AuthContext ctx = ControllerSupport.requireAuth(request);
        long accountId = ControllerSupport.accountIdOf(ctx);
        validateBindBody(body);
        requireIdempotencyKey(idempotencyKey);

        String newBindingId = bindFlow.replace(accountId, bindingId, body.channel(), body.payeeAccount(),
                payeeNameOf(accountId), idempotencyKey);
        return Envelope.ok(bindingViewOf(newBindingId), TraceIds.of(request));
    }

    @DeleteMapping("/acc/wallet/bindings/{bindingId}")
    public Envelope<UnbindView> unbind(@PathVariable String bindingId, HttpServletRequest request) {
        AuthContext ctx = ControllerSupport.requireAuth(request);
        bindFlow.unbind(ControllerSupport.accountIdOf(ctx), bindingId);
        return Envelope.ok(new UnbindView(bindingId, "UNBOUND"), TraceIds.of(request));
    }

    private void validateBindBody(BindBody body) {
        if (body.channel() == null || body.channel().isBlank()) {
            throw new AccBusinessException(1001, "channel 缺失");
        }
        if (!ControllerSupport.CHANNELS.contains(body.channel())) {
            throw new AccBusinessException(1003, "channel 枚举非法（仅 WECHAT/ALIPAY）");
        }
        if (body.payeeAccount() == null || body.payeeAccount().isBlank()) {
            throw new AccBusinessException(1001, "payeeAccount 缺失");
        }
    }

    private void requireIdempotencyKey(String idempotencyKey) {
        if (idempotencyKey == null || idempotencyKey.isBlank()) {
            throw new AccBusinessException(1001, "Idempotency-Key 缺失（资金类写操作强制）");
        }
    }

    /** BindRequest 无 payeeName：户名取平台实名，一致性由通道校验（3002）。 */
    private String payeeNameOf(long accountId) {
        Account account = accountMapper.selectById(accountId);
        return account == null ? null : account.getRealName();
    }

    private BindingView bindingViewOf(String bindingId) {
        WalletBinding binding = walletBindingMapper.selectById(bindingId);
        if (binding == null) {
            throw new AccBusinessException(3006, "绑定不存在");
        }
        return BindingView.of(binding, maskingPolicy);
    }

    /** openapi BindRequest。 */
    public record BindBody(String channel, String payeeAccount) {
    }

    /** openapi DELETE 响应 {bindingId, status}。 */
    public record UnbindView(String bindingId, String status) {
    }
}
