package com.msz.acc.application;

import java.time.Instant;

/**
 * 记账请求：金额为字符串小数（decimal(18,2)）；occurredAt 即资金发生时间，同时作为分表键业务字段。
 */
public record RecordFlowRequest(long accountId, String type, String direction, String amount,
                                String channelOrderNo, String bizType, Instant occurredAt) {
}
