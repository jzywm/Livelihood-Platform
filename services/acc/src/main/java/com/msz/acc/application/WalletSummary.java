package com.msz.acc.application;

import java.util.List;

/**
 * 钱包汇总（纯记账簿 R-01：无余额字段，仅 totalIn/totalOut/byType）。
 */
public record WalletSummary(String totalIn, String totalOut, List<TypeSummary> byType) {

    /** 按类型聚合：count 笔数 + amount 金额合计（字符串小数）。 */
    public record TypeSummary(String type, long count, String amount) {
    }
}
