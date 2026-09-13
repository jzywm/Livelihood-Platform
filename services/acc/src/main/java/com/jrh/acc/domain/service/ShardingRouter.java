package com.msz.acc.domain.service;

import com.msz.acc.domain.support.AccBusinessException;

import java.time.Instant;
import java.time.LocalDate;
import java.time.YearMonth;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.List;

/**
 * wallet_flow 按月分表路由。
 * 口径：er.md §5.3（路由以业务字段 created_at 为准，UTC 存储，禁止依赖 ID 内嵌时间戳）
 * + test-plan.md UT-B05/B06/B07。
 */
public final class ShardingRouter {

    public static final String TABLE_PREFIX = "wallet_flow_";
    public static final int DEFAULT_HOT_MONTHS = 12;
    private static final DateTimeFormatter MONTH_FORMAT = DateTimeFormatter.ofPattern("yyyyMM");

    /** 单条写入路由：按 created_at（UTC）月份 → wallet_flow_YYYYMM。 */
    public String table(Instant createdAt) {
        YearMonth month = YearMonth.from(createdAt.atZone(ZoneOffset.UTC));
        return TABLE_PREFIX + month.format(MONTH_FORMAT);
    }

    /** 跨月查询路由：from/to（含）覆盖的全部月表，升序。from>to 报 1003。 */
    public List<String> tables(LocalDate from, LocalDate to) {
        if (from.isAfter(to)) {
            throw new AccBusinessException(1003, "查询起始日期不得晚于截止日期");
        }
        List<String> result = new ArrayList<>();
        YearMonth cursor = YearMonth.from(from);
        YearMonth end = YearMonth.from(to);
        while (!cursor.isAfter(end)) {
            result.add(TABLE_PREFIX + cursor.format(MONTH_FORMAT));
            cursor = cursor.plusMonths(1);
        }
        return result;
    }

    /** 不带日期查询：默认近 12 个月热表（含当月），升序。 */
    public List<String> defaultTables(LocalDate today) {
        YearMonth current = YearMonth.from(today);
        List<String> result = new ArrayList<>();
        for (int i = DEFAULT_HOT_MONTHS - 1; i >= 0; i--) {
            YearMonth month = current.minusMonths(i);
            result.add(TABLE_PREFIX + month.format(MONTH_FORMAT));
        }
        return result;
    }
}
