package com.msz.acc.application;

import com.msz.acc.domain.model.WalletFlow;
import com.msz.acc.domain.service.ShardingRouter;
import com.msz.acc.domain.support.AccBusinessException;
import com.msz.acc.repository.WalletFlowMapper;
import com.msz.common.api.PageResult;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.RecordComponent;
import java.time.Clock;
import java.time.Instant;
import java.time.LocalDate;
import java.time.ZoneOffset;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * WalletFlowQueryServiceTest（UT-B06/B07/B09 口径）：跨月命中 3 表且合并排序不重不漏；
 * 无日期默认 12 热表；summary 聚合正确且返回类型无 balance 字段；pageSize 超 100 截断。
 */
class WalletFlowQueryServiceTest {

    private static final Instant NOW = Instant.parse("2026-01-15T00:00:00Z");

    private WalletFlowMapper mapper;
    private WalletFlowQueryService service;

    @BeforeEach
    void setUp() {
        mapper = mock(WalletFlowMapper.class);
        Clock clock = Clock.fixed(NOW, ZoneOffset.UTC);
        service = new WalletFlowQueryService(mapper, new ShardingRouter(), clock);
    }

    @Test
    @DisplayName("UT-B06: 跨月 2025-11~2026-01 命中 3 表且合并排序不重不漏")
    void ut_crossMonthMergesThreeTables() {
        WalletFlow a = flow(1L, "PAYROLL", Instant.parse("2025-11-10T10:00:00Z"));
        WalletFlow b = flow(2L, "REFUND", Instant.parse("2025-12-15T10:00:00Z"));
        WalletFlow c = flow(3L, "SPLIT", Instant.parse("2026-01-05T10:00:00Z"));
        WalletFlow d = flow(4L, "PAYROLL", Instant.parse("2026-01-20T10:00:00Z"));

        when(mapper.countByAccountAndRange(eq("wallet_flow_202511"), eq(1L), any(), any())).thenReturn(1L);
        when(mapper.countByAccountAndRange(eq("wallet_flow_202512"), eq(1L), any(), any())).thenReturn(1L);
        when(mapper.countByAccountAndRange(eq("wallet_flow_202601"), eq(1L), any(), any())).thenReturn(2L);
        when(mapper.selectByAccountAndRange(eq("wallet_flow_202511"), eq(1L), any(), any(), anyInt(), anyInt()))
                .thenReturn(List.of(a));
        when(mapper.selectByAccountAndRange(eq("wallet_flow_202512"), eq(1L), any(), any(), anyInt(), anyInt()))
                .thenReturn(List.of(b));
        when(mapper.selectByAccountAndRange(eq("wallet_flow_202601"), eq(1L), any(), any(), anyInt(), anyInt()))
                .thenReturn(List.of(d, c));

        PageResult<WalletFlow> result = service.query(1L, null,
                LocalDate.parse("2025-11-01"), LocalDate.parse("2026-01-31"), 1, 20);

        assertThat(result.total()).isEqualTo(4L);
        assertThat(result.list()).extracting(WalletFlow::getFlowId)
                .containsExactly(4L, 3L, 2L, 1L);
        verify(mapper, times(3)).countByAccountAndRange(anyString(), eq(1L), any(), any());
        verify(mapper, times(3)).selectByAccountAndRange(anyString(), eq(1L), any(), any(), anyInt(), anyInt());
    }

    @Test
    @DisplayName("UT-B07: 无日期查询默认近 12 个月热表")
    void ut_noDateQueriesTwelveHotTables() {
        when(mapper.countByAccountAndRange(anyString(), eq(1L), any(), any())).thenReturn(0L);
        when(mapper.selectByAccountAndRange(anyString(), eq(1L), any(), any(), anyInt(), anyInt()))
                .thenReturn(List.of());

        PageResult<WalletFlow> result = service.query(1L, null, null, null, 1, 20);

        assertThat(result.total()).isZero();
        assertThat(result.list()).isEmpty();
        verify(mapper, times(12)).countByAccountAndRange(anyString(), eq(1L), any(), any());
        verify(mapper, times(12)).selectByAccountAndRange(anyString(), eq(1L), any(), any(), anyInt(), anyInt());
    }

    @Test
    @DisplayName("UT-B09: summary 聚合正确且返回类型无 balance 字段")
    void ut_summaryAggregatesWithoutBalance() {
        List<WalletFlow> flows = List.of(
                flow(1L, "PAYROLL", "IN", "1000.00", Instant.parse("2026-01-05T10:00:00Z")),
                flow(2L, "REFUND", "OUT", "50.00", Instant.parse("2026-01-06T10:00:00Z")),
                flow(3L, "PAYROLL", "IN", "200.00", Instant.parse("2026-01-07T10:00:00Z")));
        when(mapper.selectByAccountAndRange(eq("wallet_flow_202601"), eq(1L), any(), any(), anyInt(), anyInt()))
                .thenReturn(flows);

        WalletSummary summary = service.summary(1L);

        assertThat(summary.totalIn()).isEqualTo("1200.00");
        assertThat(summary.totalOut()).isEqualTo("50.00");
        assertThat(summary.byType()).extracting(WalletSummary.TypeSummary::type)
                .containsExactly("PAYROLL", "REFUND");
        assertThat(summary.byType()).extracting(WalletSummary.TypeSummary::count)
                .containsExactly(2L, 1L);
        assertThat(summary.byType()).extracting(WalletSummary.TypeSummary::amount)
                .containsExactly("1200.00", "50.00");

        assertThat(WalletSummary.class.getRecordComponents())
                .extracting(RecordComponent::getName)
                .doesNotContain("balance");
    }

    @Test
    @DisplayName("pageSize 超 100 → 截断为 100")
    void ut_pageSizeCappedAtHundred() {
        when(mapper.countByAccountAndRange(anyString(), eq(1L), any(), any())).thenReturn(0L);
        when(mapper.selectByAccountAndRange(anyString(), eq(1L), any(), any(), anyInt(), anyInt()))
                .thenReturn(List.of());

        PageResult<WalletFlow> result = service.query(1L, null, null, null, 1, 500);

        assertThat(result.page()).isEqualTo(1);
        assertThat(result.pageSize()).isEqualTo(100);
        verify(mapper, times(12)).selectByAccountAndRange(anyString(), eq(1L), any(), any(), eq(0), eq(100));
    }

    @Test
    @DisplayName("type 枚举非法 → 1003")
    void ut_invalidTypeRejected() {
        assertThatThrownBy(() -> service.query(1L, "UNKNOWN", null, null, 1, 20))
                .isInstanceOfSatisfying(AccBusinessException.class,
                        e -> assertThat(e.code()).isEqualTo(1003));
    }

    private static WalletFlow flow(long id, String type, Instant occurredAt) {
        return flow(id, type, "IN", "10.00", occurredAt);
    }

    private static WalletFlow flow(long id, String type, String direction, String amount, Instant occurredAt) {
        WalletFlow flow = new WalletFlow();
        flow.setFlowId(id);
        flow.setAccountId(1L);
        flow.setType(type);
        flow.setDirection(direction);
        flow.setAmount(amount);
        flow.setOccurredAt(occurredAt);
        flow.setCreatedAt(occurredAt);
        return flow;
    }
}
