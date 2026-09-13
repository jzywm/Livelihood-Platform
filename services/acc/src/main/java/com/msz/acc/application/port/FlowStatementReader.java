package com.msz.acc.application.port;

import java.time.LocalDate;
import java.util.List;

/**
 * 平台流水读取器（从库读语义，S5 提供真实适配）：按日期范围读取平台记账流水。
 */
public interface FlowStatementReader {

    List<FlowStatement> read(LocalDate from, LocalDate to);
}
