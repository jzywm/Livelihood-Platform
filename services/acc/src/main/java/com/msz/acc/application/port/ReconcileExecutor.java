package com.msz.acc.application.port;

import java.time.LocalDate;

/**
 * 对账执行器抽象：S4 用 {@code InlineReconcileExecutor} 同步实现，预留异步（从库核对、不压 OLTP）。
 */
public interface ReconcileExecutor {

    /** 按日期范围核对通道账单与平台流水，返回不一致笔数 diffCount。 */
    long compare(LocalDate from, LocalDate to);
}
