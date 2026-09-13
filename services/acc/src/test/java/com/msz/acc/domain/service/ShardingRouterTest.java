package com.msz.acc.domain.service;

import com.msz.acc.domain.support.AccBusinessException;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.time.Instant;
import java.time.LocalDate;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * 分表路由单元测试 · 对应 test-plan.md UT-B05/B06/B07：
 * 按月路由以业务字段 created_at 为准（UTC），跨月命中多表升序，无日期默认近 12 个月热表。
 */
class ShardingRouterTest {

    private final ShardingRouter router = new ShardingRouter();

    @Test
    @DisplayName("UT-B05: 月末边界 2026-01-31T23:59:59.999Z 落 wallet_flow_202601")
    void ut_b05_januaryLastMillisRoutesToJanuary() {
        assertThat(router.table(Instant.parse("2026-01-31T23:59:59.999Z")))
                .isEqualTo("wallet_flow_202601");
    }

    @Test
    @DisplayName("UT-B05: 月初边界 2026-02-01T00:00:00Z 落 wallet_flow_202602")
    void ut_b05_februaryFirstMillisRoutesToFebruary() {
        assertThat(router.table(Instant.parse("2026-02-01T00:00:00Z")))
                .isEqualTo("wallet_flow_202602");
    }

    @Test
    @DisplayName("UT-B06: 跨月查询 2025-11-01~2026-01-31 命中 3 张表升序")
    void ut_b06_crossMonthRangeHitsThreeTables() {
        assertThat(router.tables(LocalDate.parse("2025-11-01"), LocalDate.parse("2026-01-31")))
                .containsExactly("wallet_flow_202511", "wallet_flow_202512", "wallet_flow_202601");
    }

    @Test
    @DisplayName("UT-B06: 跨年查询 2025-12-20~2026-02-10 命中 3 张表升序")
    void ut_b06_crossYearRangeHitsThreeTables() {
        assertThat(router.tables(LocalDate.parse("2025-12-20"), LocalDate.parse("2026-02-10")))
                .containsExactly("wallet_flow_202512", "wallet_flow_202601", "wallet_flow_202602");
    }

    @Test
    @DisplayName("UT-B06: 同月查询仅命中 1 张表")
    void ut_b06_sameMonthRangeHitsSingleTable() {
        assertThat(router.tables(LocalDate.parse("2026-01-05"), LocalDate.parse("2026-01-20")))
                .containsExactly("wallet_flow_202601");
    }

    @Test
    @DisplayName("UT-B06: from>to 报 1003")
    void ut_b06_fromAfterToIsRejected() {
        assertThatThrownBy(() -> router.tables(LocalDate.parse("2026-02-01"), LocalDate.parse("2026-01-01")))
                .isInstanceOfSatisfying(AccBusinessException.class,
                        e -> assertThat(e.code()).isEqualTo(1003));
    }

    @Test
    @DisplayName("UT-B07: 无日期查询默认近 12 个月热表（含当月），升序")
    void ut_b07_defaultTablesCoverLastTwelveMonths() {
        List<String> tables = router.defaultTables(LocalDate.parse("2026-01-15"));
        assertThat(tables).hasSize(12);
        assertThat(tables.get(0)).isEqualTo("wallet_flow_202502");
        assertThat(tables.get(11)).isEqualTo("wallet_flow_202601");
    }
}
