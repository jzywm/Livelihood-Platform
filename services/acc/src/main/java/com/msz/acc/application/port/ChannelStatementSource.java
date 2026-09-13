package com.msz.acc.application.port;

import java.time.LocalDate;
import java.util.List;

/**
 * 第三方通道账单源（S5 提供真实适配）：按日期范围拉取通道账单。
 */
public interface ChannelStatementSource {

    List<ChannelStatement> statements(LocalDate from, LocalDate to);
}
