package com.msz.acc.controller.dto;

import com.msz.acc.domain.model.WalletFlow;

import java.time.Instant;

/**
 * 钱包流水视图（openapi WalletFlow schema，流水无 PII 直接返回）。
 */
public record WalletFlowView(String flowId, String type, String direction, String amount, String status,
                             String channelOrderNo, String bizType, String hash, Instant occurredAt) {

    public static WalletFlowView of(WalletFlow flow) {
        return new WalletFlowView("flw_" + flow.getFlowId(), flow.getType(), flow.getDirection(),
                flow.getAmount(), flow.getStatus(), flow.getChannelOrderNo(), flow.getBizType(),
                flow.getHash(), flow.getOccurredAt());
    }
}
