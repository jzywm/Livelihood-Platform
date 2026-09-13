package com.msz.acc.application;

import com.msz.acc.domain.model.WalletFlow;
import com.msz.acc.domain.service.ShardingRouter;
import com.msz.acc.domain.support.AccBusinessException;
import com.msz.acc.repository.WalletFlowMapper;
import com.msz.common.api.ApiConventions;
import com.msz.common.api.PageResult;

import java.math.BigDecimal;
import java.time.Clock;
import java.time.Instant;
import java.time.LocalDate;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * 钱包流水查询服务（4.3）：跨月逐表分页合并排序、无日期默认 12 月热表、summary 聚合（无余额字段）。
 */
public final class WalletFlowQueryService {

    private static final Set<String> FLOW_TYPES = Set.of("PAYROLL", "SERVICE_FEE", "SPLIT", "REFUND", "OTHER");
    private static final int FULL_LIMIT = Integer.MAX_VALUE;

    private final WalletFlowMapper walletFlowMapper;
    private final ShardingRouter shardingRouter;
    private final Clock clock;

    public WalletFlowQueryService(WalletFlowMapper walletFlowMapper, ShardingRouter shardingRouter, Clock clock) {
        this.walletFlowMapper = walletFlowMapper;
        this.shardingRouter = shardingRouter;
        this.clock = clock;
    }

    public PageResult<WalletFlow> query(long accountId, String type, LocalDate from, LocalDate to,
                                        int page, int pageSize) {
        int p = page < 1 ? ApiConventions.DEFAULT_PAGE : page;
        int ps = pageSize > ApiConventions.MAX_PAGE_SIZE ? ApiConventions.MAX_PAGE_SIZE
                : (pageSize < 1 ? ApiConventions.DEFAULT_PAGE_SIZE : pageSize);
        String typeFilter = normalizeType(type);

        Range range = resolveRange(from, to);
        long total = 0L;
        List<WalletFlow> merged = new ArrayList<>();
        for (String table : range.tables()) {
            total += walletFlowMapper.countByAccountAndRange(table, accountId, range.fromInstant(), range.toInstant());
            merged.addAll(walletFlowMapper.selectByAccountAndRange(
                    table, accountId, range.fromInstant(), range.toInstant(), 0, p * ps));
        }
        if (typeFilter != null) {
            merged.removeIf(flow -> !typeFilter.equals(flow.getType()));
        }
        merged.sort(Comparator.comparing(WalletFlow::getOccurredAt).reversed());

        int start = Math.min((p - 1) * ps, merged.size());
        int end = Math.min(start + ps, merged.size());
        return new PageResult<>(merged.subList(start, end), total, p, ps);
    }

    public WalletSummary summary(long accountId) {
        LocalDate today = LocalDate.now(clock);
        List<String> tables = shardingRouter.defaultTables(today);
        Instant fromInstant = today.minusMonths(ShardingRouter.DEFAULT_HOT_MONTHS - 1L)
                .withDayOfMonth(1).atStartOfDay(ZoneOffset.UTC).toInstant();
        Instant toInstant = today.plusDays(1).atStartOfDay(ZoneOffset.UTC).toInstant();

        BigDecimal totalIn = BigDecimal.ZERO;
        BigDecimal totalOut = BigDecimal.ZERO;
        Map<String, TypeAccumulator> byType = new LinkedHashMap<>();
        for (String table : tables) {
            for (WalletFlow flow : walletFlowMapper.selectByAccountAndRange(
                    table, accountId, fromInstant, toInstant, 0, FULL_LIMIT)) {
                BigDecimal amount = new BigDecimal(flow.getAmount());
                if ("IN".equals(flow.getDirection())) {
                    totalIn = totalIn.add(amount);
                } else if ("OUT".equals(flow.getDirection())) {
                    totalOut = totalOut.add(amount);
                }
                byType.computeIfAbsent(flow.getType(), TypeAccumulator::new).add(amount);
            }
        }
        List<WalletSummary.TypeSummary> typeSummaries = byType.values().stream()
                .map(a -> new WalletSummary.TypeSummary(a.type, a.count, a.amount.toPlainString()))
                .toList();
        return new WalletSummary(totalIn.toPlainString(), totalOut.toPlainString(), typeSummaries);
    }

    private Range resolveRange(LocalDate from, LocalDate to) {
        if (from != null && to != null) {
            List<String> tables = shardingRouter.tables(from, to);
            Instant fromInstant = from.atStartOfDay(ZoneOffset.UTC).toInstant();
            Instant toInstant = to.plusDays(1).atStartOfDay(ZoneOffset.UTC).toInstant();
            return new Range(tables, fromInstant, toInstant);
        }
        LocalDate today = LocalDate.now(clock);
        List<String> tables = shardingRouter.defaultTables(today);
        Instant fromInstant = today.minusMonths(ShardingRouter.DEFAULT_HOT_MONTHS - 1L)
                .withDayOfMonth(1).atStartOfDay(ZoneOffset.UTC).toInstant();
        Instant toInstant = today.plusDays(1).atStartOfDay(ZoneOffset.UTC).toInstant();
        return new Range(tables, fromInstant, toInstant);
    }

    private static String normalizeType(String type) {
        if (type == null || type.isEmpty()) {
            return null;
        }
        if (!FLOW_TYPES.contains(type)) {
            throw new AccBusinessException(1003, "流水类型非法");
        }
        return type;
    }

    private record Range(List<String> tables, Instant fromInstant, Instant toInstant) {
    }

    private static final class TypeAccumulator {
        private final String type;
        private long count;
        private BigDecimal amount = BigDecimal.ZERO;

        private TypeAccumulator(String type) {
            this.type = type;
        }

        private void add(BigDecimal value) {
            count++;
            amount = amount.add(value);
        }
    }
}
