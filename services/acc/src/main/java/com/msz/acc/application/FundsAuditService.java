package com.msz.acc.application;

import com.msz.acc.domain.model.ReconcileTask;
import com.msz.acc.domain.model.WalletFlow;
import com.msz.acc.domain.service.ShardingRouter;
import com.msz.acc.repository.ReconcileTaskMapper;
import com.msz.acc.repository.WalletFlowMapper;
import com.msz.common.api.ApiConventions;
import com.msz.common.api.PageResult;

import java.time.Clock;
import java.time.Instant;
import java.time.LocalDate;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;

/**
 * 监管资金流水审计查询（S5）：跨月全量流水 + 对账视图。
 *
 * <p>reconcileStatus 口径：流水发生日落在某对账任务 [from_date, to_date] 内 → 按任务状态映射
 * （DONE→RECONCILED / DIFF→DIFF / RUNNING→PENDING）；无覆盖任务 → PENDING。
 * 多任务重叠时取最近创建的任务。</p>
 */
public final class FundsAuditService {

    private static final int FULL_LIMIT = Integer.MAX_VALUE;

    private final WalletFlowMapper walletFlowMapper;
    private final ReconcileTaskMapper reconcileTaskMapper;
    private final ShardingRouter shardingRouter;
    private final Clock clock;

    public FundsAuditService(WalletFlowMapper walletFlowMapper, ReconcileTaskMapper reconcileTaskMapper,
                             ShardingRouter shardingRouter, Clock clock) {
        this.walletFlowMapper = walletFlowMapper;
        this.reconcileTaskMapper = reconcileTaskMapper;
        this.shardingRouter = shardingRouter;
        this.clock = clock;
    }

    /** 审计流水条目：平台流水 + 对账状态（PENDING/RECONCILED/DIFF）。 */
    public record AuditItem(WalletFlow flow, String reconcileStatus) {
    }

    public PageResult<AuditItem> audit(int page, int pageSize, LocalDate from, LocalDate to,
                                       String reconcileStatusFilter) {
        int p = page < 1 ? ApiConventions.DEFAULT_PAGE : page;
        int ps = pageSize > ApiConventions.MAX_PAGE_SIZE ? ApiConventions.MAX_PAGE_SIZE
                : (pageSize < 1 ? ApiConventions.DEFAULT_PAGE_SIZE : pageSize);

        LocalDate fromDate = from;
        LocalDate toDate = to;
        if (fromDate == null || toDate == null) {
            LocalDate today = LocalDate.now(clock);
            fromDate = today.minusMonths(ShardingRouter.DEFAULT_HOT_MONTHS - 1L).withDayOfMonth(1);
            toDate = today;
        }

        List<ReconcileTask> tasks = reconcileTaskMapper.selectAllByRange(fromDate, toDate);
        List<AuditItem> matched = new ArrayList<>();
        for (String table : shardingRouter.tables(fromDate, toDate)) {
            for (WalletFlow flow : walletFlowMapper.selectAllByRange(table,
                    fromDate.atStartOfDay(ZoneOffset.UTC).toInstant(),
                    toDate.plusDays(1).atStartOfDay(ZoneOffset.UTC).toInstant(),
                    0, FULL_LIMIT)) {
                String reconcileStatus = reconcileStatusOf(flow, tasks);
                if (reconcileStatusFilter == null || reconcileStatusFilter.equals(reconcileStatus)) {
                    matched.add(new AuditItem(flow, reconcileStatus));
                }
            }
        }
        matched.sort(Comparator.comparing((AuditItem i) -> i.flow().getOccurredAt()).reversed());

        int start = Math.min((p - 1) * ps, matched.size());
        int end = Math.min(start + ps, matched.size());
        return new PageResult<>(matched.subList(start, end), matched.size(), p, ps);
    }

    private static String reconcileStatusOf(WalletFlow flow, List<ReconcileTask> tasks) {
        LocalDate occurredDate = flow.getOccurredAt().atZone(ZoneOffset.UTC).toLocalDate();
        for (ReconcileTask task : tasks) { // tasks 已按 created_at DESC，首个覆盖者生效
            if (!occurredDate.isBefore(task.getFromDate()) && !occurredDate.isAfter(task.getToDate())) {
                return switch (task.getStatus()) {
                    case "DONE" -> "RECONCILED";
                    case "DIFF" -> "DIFF";
                    default -> "PENDING";
                };
            }
        }
        return "PENDING";
    }
}
