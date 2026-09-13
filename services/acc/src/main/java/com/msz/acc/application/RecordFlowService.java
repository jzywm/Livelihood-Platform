package com.msz.acc.application;

import com.msz.acc.domain.model.WalletFlow;
import com.msz.acc.domain.service.AmountPolicy;
import com.msz.acc.domain.service.HashChainService;
import com.msz.acc.domain.service.ShardingRouter;
import com.msz.acc.infrastructure.redis.HashTailStore;
import com.msz.acc.repository.WalletFlowMapper;
import com.msz.common.idgen.IdGenerator;

import java.time.Instant;
import java.time.LocalDate;
import java.time.ZoneOffset;
import java.util.List;

/**
 * 记账流程（4.4）：amount 校验、channelOrderNo 当月+前月查重（幂等）、哈希链 + 写链尾、落库。
 * createdAt 用 occurredAt（资金发生时间即分表键业务字段）。
 */
public final class RecordFlowService {

    private static final int FULL_LIMIT = Integer.MAX_VALUE;

    private final WalletFlowMapper walletFlowMapper;
    private final HashChainService hashChainService;
    private final HashTailStore hashTailStore;
    private final AmountPolicy amountPolicy;
    private final IdGenerator idGenerator;
    private final ShardingRouter shardingRouter;

    public RecordFlowService(WalletFlowMapper walletFlowMapper, HashChainService hashChainService,
                             HashTailStore hashTailStore, AmountPolicy amountPolicy,
                             IdGenerator idGenerator, ShardingRouter shardingRouter) {
        this.walletFlowMapper = walletFlowMapper;
        this.hashChainService = hashChainService;
        this.hashTailStore = hashTailStore;
        this.amountPolicy = amountPolicy;
        this.idGenerator = idGenerator;
        this.shardingRouter = shardingRouter;
    }

    public WalletFlow recordFlow(RecordFlowRequest req) {
        amountPolicy.validate(req.amount());

        if (req.channelOrderNo() != null && !req.channelOrderNo().isEmpty()) {
            WalletFlow existing = findExistingByChannelOrderNo(req.accountId(), req.channelOrderNo(), req.occurredAt());
            if (existing != null) {
                return existing;
            }
        }

        String rowData = String.join("|", req.type(), req.direction(), req.amount(),
                req.channelOrderNo() == null ? "" : req.channelOrderNo());
        String hash = hashTailStore.writeTail(req.accountId(), rowData, req.occurredAt(),
                prev -> hashChainService.compute(prev, rowData, req.occurredAt()));

        WalletFlow flow = new WalletFlow();
        flow.setFlowId(idGenerator.nextId());
        flow.setAccountId(req.accountId());
        flow.setType(req.type());
        flow.setDirection(req.direction());
        flow.setAmount(req.amount());
        flow.setStatus("SUCCEEDED");
        flow.setChannelOrderNo(req.channelOrderNo());
        flow.setBizType(req.bizType());
        flow.setHash(hash);
        flow.setOccurredAt(req.occurredAt());
        flow.setCreatedAt(req.occurredAt());
        walletFlowMapper.insert(flow);
        return flow;
    }

    private WalletFlow findExistingByChannelOrderNo(long accountId, String channelOrderNo, Instant occurredAt) {
        LocalDate occurredDate = occurredAt.atZone(ZoneOffset.UTC).toLocalDate();
        LocalDate fromDate = occurredDate.minusMonths(1).withDayOfMonth(1);
        LocalDate toDate = occurredDate.withDayOfMonth(occurredDate.lengthOfMonth());
        List<String> tables = shardingRouter.tables(fromDate, occurredDate);
        Instant fromInstant = fromDate.atStartOfDay(ZoneOffset.UTC).toInstant();
        Instant toInstant = toDate.plusDays(1).atStartOfDay(ZoneOffset.UTC).toInstant();
        for (String table : tables) {
            for (WalletFlow flow : walletFlowMapper.selectByAccountAndRange(
                    table, accountId, fromInstant, toInstant, 0, FULL_LIMIT, null)) {
                if (channelOrderNo.equals(flow.getChannelOrderNo())) {
                    return flow;
                }
            }
        }
        return null;
    }
}
