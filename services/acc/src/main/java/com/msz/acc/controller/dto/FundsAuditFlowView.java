package com.msz.acc.controller.dto;

import java.time.Instant;

/**
 * 监管资金审计流水视图（openapi FundsAuditFlow schema = WalletFlow + payerId/payeeId/merchantName/reconcileStatus）。
 */
public record FundsAuditFlowView(String flowId, String type, String direction, String amount, String status,
                                 String channelOrderNo, String bizType, String hash, Instant occurredAt,
                                 String payerId, String payeeId, String merchantName, String reconcileStatus) {
}
