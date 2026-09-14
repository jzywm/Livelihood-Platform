package com.msz.acc.application;

import com.msz.acc.domain.model.ReconcileTask;
import com.msz.acc.domain.model.WalletFlow;
import com.msz.acc.domain.service.ShardingRouter;
import com.msz.acc.repository.ReconcileTaskMapper;
import com.msz.acc.repository.WalletFlowMapper;
import com.msz.common.api.PageResult;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.time.Clock;
import java.time.Instant;
import java.time.LocalDate;
import java.time.ZoneOffset;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * FundsAuditService（S5）：监管审计查询——跨月全量读取、按对账任务覆盖映射
 * reconcileStatus（无任务 PENDING / DONE→RECONCILED / DIFF→DIFF / RUNNING→PENDING）、
 * reconcileStatus 筛选、按 occurredAt 倒序分页。
 */
class FundsAuditServiceTest {

    private static final Instant NOW = Instant.parse("2026-03-01T00:00:00Z");
    private static final LocalDate FROM = LocalDate.parse("2026-01-01");
    private static final LocalDate TO = LocalDate.parse("2026-02-28");

    private WalletFlowMapper walletFlowMapper;
    private ReconcileTaskMapper reconcileTaskMapper;
    private FundsAuditService service;

    @BeforeEach
    void setUp() {
        walletFlowMapper = mock(WalletFlowMapper.class);
        reconcileTaskMapper = mock(ReconcileTaskMapper.class);
        Clock clock = Clock.fixed(NOW, ZoneOffset.UTC);
        service = new FundsAuditService(walletFlowMapper, reconcileTaskMapper, new ShardingRouter(), clock);
    }

    @Test
    @DisplayName("无覆盖任务 → PENDING；DONE → RECONCILED；DIFF → DIFF；按 occurredAt 倒序")
    void ut_reconcileStatusMappingAndOrder() {
        WalletFlow jan = flow(1L, 11L, Instant.parse("2026-01-15T00:00:00Z"));
        WalletFlow feb = flow(2L, 22L, Instant.parse("2026-02-10T00:00:00Z"));
        when(walletFlowMapper.selectAllByRange(eq("wallet_flow_202601"), any(), any(), anyInt(), anyInt()))
                .thenReturn(List.of(jan));
        when(walletFlowMapper.selectAllByRange(eq("wallet_flow_202602"), any(), any(), anyInt(), anyInt()))
                .thenReturn(List.of(feb));
        when(reconcileTaskMapper.selectAllByRange(FROM, TO)).thenReturn(List.of(
                task("rec_diff", "DIFF", LocalDate.parse("2026-02-01"), LocalDate.parse("2026-02-28")),
                task("rec_done", "DONE", LocalDate.parse("2026-01-01"), LocalDate.parse("2026-01-31"))));

        PageResult<FundsAuditService.AuditItem> page = service.audit(1, 20, FROM, TO, null);

        assertThat(page.total()).isEqualTo(2);
        assertThat(page.list())
                .extracting(i -> i.reconcileStatus())
                .containsExactly("DIFF", "RECONCILED");
        assertThat(page.list())
                .extracting(i -> i.flow().getFlowId())
                .containsExactly(2L, 1L);
    }

    @Test
    @DisplayName("reconcileStatus 筛选：仅返回匹配条目（PENDING 含无任务与 RUNNING 任务）")
    void ut_filterByReconcileStatus() {
        WalletFlow pending = flow(1L, 11L, Instant.parse("2026-01-15T00:00:00Z"));
        WalletFlow running = flow(2L, 22L, Instant.parse("2026-01-16T00:00:00Z"));
        when(walletFlowMapper.selectAllByRange(eq("wallet_flow_202601"), any(), any(), anyInt(), anyInt()))
                .thenReturn(List.of(pending, running));
        when(walletFlowMapper.selectAllByRange(eq("wallet_flow_202602"), any(), any(), anyInt(), anyInt()))
                .thenReturn(List.of());
        when(reconcileTaskMapper.selectAllByRange(FROM, TO)).thenReturn(List.of(
                task("rec_running", "RUNNING", FROM, TO)));

        PageResult<FundsAuditService.AuditItem> page = service.audit(1, 20, FROM, TO, "PENDING");

        assertThat(page.total()).isEqualTo(2);
        assertThat(page.list()).allSatisfy(i -> assertThat(i.reconcileStatus()).isEqualTo("PENDING"));
    }

    @Test
    @DisplayName("分页口径：pageSize 上限 100、超出页码返回空列表且 total 不变")
    void ut_paginationClamp() {
        WalletFlow flow = flow(1L, 11L, Instant.parse("2026-01-15T00:00:00Z"));
        when(walletFlowMapper.selectAllByRange(eq("wallet_flow_202601"), any(), any(), anyInt(), anyInt()))
                .thenReturn(List.of(flow));
        when(walletFlowMapper.selectAllByRange(eq("wallet_flow_202602"), any(), any(), anyInt(), anyInt()))
                .thenReturn(List.of());
        when(reconcileTaskMapper.selectAllByRange(any(), any())).thenReturn(List.of());

        PageResult<FundsAuditService.AuditItem> page = service.audit(1, 999, FROM, TO, null);
        assertThat(page.pageSize()).isEqualTo(100);
        assertThat(page.total()).isEqualTo(1);

        PageResult<FundsAuditService.AuditItem> beyond = service.audit(99, 20, FROM, TO, null);
        assertThat(beyond.list()).isEmpty();
        assertThat(beyond.total()).isEqualTo(1);
    }

    @Test
    @DisplayName("无日期参数：走 12 个月热表路由不抛异常")
    void ut_defaultRangeUsesHotTables() {
        when(walletFlowMapper.selectAllByRange(any(), any(), any(), anyInt(), anyInt()))
                .thenReturn(List.of());
        when(reconcileTaskMapper.selectAllByRange(any(), any())).thenReturn(List.of());

        assertThat(service.audit(1, 20, null, null, null).total()).isZero();
    }

    private static WalletFlow flow(long flowId, long accountId, Instant occurredAt) {
        WalletFlow flow = new WalletFlow();
        flow.setFlowId(flowId);
        flow.setAccountId(accountId);
        flow.setType("PAYROLL");
        flow.setDirection("IN");
        flow.setAmount("100.00");
        flow.setStatus("SUCCEEDED");
        flow.setChannelOrderNo("CH-" + flowId);
        flow.setOccurredAt(occurredAt);
        return flow;
    }

    private static ReconcileTask task(String reconcileId, String status, LocalDate from, LocalDate to) {
        ReconcileTask task = new ReconcileTask();
        task.setReconcileId(reconcileId);
        task.setStatus(status);
        task.setFromDate(from);
        task.setToDate(to);
        return task;
    }
}
