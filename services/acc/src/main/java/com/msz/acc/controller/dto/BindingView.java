package com.msz.acc.controller.dto;

import com.msz.acc.domain.model.WalletBinding;
import com.msz.acc.domain.service.MaskingPolicy;

import java.time.Instant;

/**
 * 收款账户绑定视图（openapi Binding schema）：payeeAccount/payeeName 脱敏输出。
 */
public record BindingView(String bindingId, String channel, String payeeAccount, String payeeName,
                          String status, Instant createdAt) {

    public static BindingView of(WalletBinding binding, MaskingPolicy maskingPolicy) {
        return new BindingView(binding.getBindingId(), binding.getChannel(),
                maskingPolicy.maskBankCard(binding.getPayeeAccount()),
                maskingPolicy.maskName(binding.getPayeeName()),
                binding.getStatus(), binding.getCreatedAt());
    }
}
