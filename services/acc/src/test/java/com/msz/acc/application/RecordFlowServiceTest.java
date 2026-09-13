package com.msz.acc.application;

import com.msz.acc.domain.model.WalletFlow;
import com.msz.acc.domain.service.AmountPolicy;
import com.msz.acc.domain.service.HashChainService;
import com.msz.acc.domain.service.ShardingRouter;
import com.msz.acc.domain.support.AccBusinessException;
import com.msz.acc.infrastructure.redis.HashTailStore;
import com.msz.acc.repository.WalletFlowMapper;
import com.msz.common.idgen.IdGenerator;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.time.Instant;
import java.util.List;
import java.util.function.Function;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * RecordFlowServiceTest（IT-03 口径）：记账成功且 hash=HashChainService.compute(链尾,…)；
 * 同 channelOrderNo 重复 → 幂等返回原 flow 不重复插入；金额非法 1003。
 */
class RecordFlowServiceTest {

    private static final Instant OCCURRED_AT = Instant.parse("2026-01-15T10:00:00Z");

    private WalletFlowMapper mapper;
    private IdGenerator idGenerator;
    private HashChainService hashChainService;
    private String[] tail;
    private RecordFlowService service;

    @BeforeEach
    void setUp() {
        mapper = mock(WalletFlowMapper.class);
        idGenerator = mock(IdGenerator.class);
        hashChainService = new HashChainService();
        tail = new String[1];
        HashTailStore tailStore = new HashTailStore() {
            @Override
            public String writeTail(long accountId, String rowData, Instant occurredAt, Function<String, String> hashFn) {
                String prev = tail[0] == null ? hashChainService.genesisHash() : tail[0];
                tail[0] = hashFn.apply(prev);
                return tail[0];
            }

            @Override
            public String readTail(long accountId) {
                return tail[0];
            }

            @Override
            public void rebuild(long accountId, String lastHashFromDb) {
                tail[0] = lastHashFromDb;
            }
        };
        service = new RecordFlowService(mapper, hashChainService, tailStore, new AmountPolicy(),
                idGenerator, new ShardingRouter());
    }

    @Test
    @DisplayName("UT-B01/IT-03: 记账成功且 hash=HashChainService.compute(链尾,行数据,时间戳)")
    void ut_recordFlowComputesHashChain() {
        when(idGenerator.nextId()).thenReturn(1001L);
        RecordFlowRequest req = new RecordFlowRequest(1L, "PAYROLL", "IN", "3200.00", "wx001", "PAYROLL", OCCURRED_AT);

        WalletFlow result = service.recordFlow(req);

        String rowData = "PAYROLL|IN|3200.00|wx001";
        String expectedHash = hashChainService.compute(hashChainService.genesisHash(), rowData, OCCURRED_AT);
        assertThat(result.getHash()).isEqualTo(expectedHash);
        assertThat(result.getFlowId()).isEqualTo(1001L);
        assertThat(result.getStatus()).isEqualTo("SUCCEEDED");
        assertThat(result.getCreatedAt()).isEqualTo(OCCURRED_AT);
        assertThat(tail[0]).isEqualTo(expectedHash);
        verify(mapper).insert(result);
    }

    @Test
    @DisplayName("同 channelOrderNo 重复 → 幂等返回原 flow 不重复插入")
    void ut_duplicateChannelOrderNoReturnsExistingFlow() {
        WalletFlow existing = new WalletFlow();
        existing.setFlowId(500L);
        existing.setAccountId(1L);
        existing.setType("PAYROLL");
        existing.setDirection("IN");
        existing.setAmount("3200.00");
        existing.setChannelOrderNo("wx001");
        existing.setOccurredAt(OCCURRED_AT);
        existing.setCreatedAt(OCCURRED_AT);
        when(mapper.selectByAccountAndRange(anyString(), eq(1L), any(), any(), anyInt(), anyInt()))
                .thenReturn(List.of(existing));

        RecordFlowRequest req = new RecordFlowRequest(1L, "PAYROLL", "IN", "3200.00", "wx001", "PAYROLL", OCCURRED_AT);

        WalletFlow result = service.recordFlow(req);

        assertThat(result.getFlowId()).isEqualTo(500L);
        assertThat(tail[0]).as("查重命中不写链尾").isNull();
        verify(mapper, never()).insert(any());
    }

    @Test
    @DisplayName("金额非法 → 1003")
    void ut_invalidAmountRejected() {
        RecordFlowRequest req = new RecordFlowRequest(1L, "PAYROLL", "IN", "abc", "wx001", "PAYROLL", OCCURRED_AT);

        assertThatThrownBy(() -> service.recordFlow(req))
                .isInstanceOfSatisfying(AccBusinessException.class,
                        e -> assertThat(e.code()).isEqualTo(1003));
        verify(mapper, never()).insert(any());
    }
}
