package com.msz.acc.application.port;

import java.time.Instant;

/**
 * 平台流水条目（对账核对对象：通道交易号 + 金额）。
 */
public record FlowStatement(String channelOrderNo, String amount, Instant occurredAt) {
}
