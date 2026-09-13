package com.msz.acc.application.port;

import java.time.Instant;

/**
 * 第三方通道账单条目（对账核对对象：通道交易号 + 金额）。
 */
public record ChannelStatement(String channelOrderNo, String amount, Instant occurredAt) {
}
