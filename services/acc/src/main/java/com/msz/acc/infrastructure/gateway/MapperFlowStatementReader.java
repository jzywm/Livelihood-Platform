package com.msz.acc.infrastructure.gateway;

import com.msz.acc.application.port.FlowStatement;
import com.msz.acc.application.port.FlowStatementReader;
import com.msz.acc.domain.service.ShardingRouter;
import com.msz.acc.repository.WalletFlowMapper;

import java.time.LocalDate;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.List;

/**
 * 平台流水读取器（S5 端口适配）：按日期范围逐月表读取全量流水（对账核对对象）。
 */
public final class MapperFlowStatementReader implements FlowStatementReader {

    private static final int FULL_LIMIT = Integer.MAX_VALUE;

    private final WalletFlowMapper walletFlowMapper;
    private final ShardingRouter shardingRouter;

    public MapperFlowStatementReader(WalletFlowMapper walletFlowMapper, ShardingRouter shardingRouter) {
        this.walletFlowMapper = walletFlowMapper;
        this.shardingRouter = shardingRouter;
    }

    @Override
    public List<FlowStatement> read(LocalDate from, LocalDate to) {
        List<FlowStatement> result = new ArrayList<>();
        for (String table : shardingRouter.tables(from, to)) {
            walletFlowMapper.selectAllByRange(table,
                            from.atStartOfDay(ZoneOffset.UTC).toInstant(),
                            to.plusDays(1).atStartOfDay(ZoneOffset.UTC).toInstant(),
                            0, FULL_LIMIT)
                    .forEach(flow -> result.add(new FlowStatement(
                            flow.getChannelOrderNo(), flow.getAmount(), flow.getOccurredAt())));
        }
        return result;
    }
}
