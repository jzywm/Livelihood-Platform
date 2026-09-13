package com.msz.acc.domain.service;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.time.Instant;
import java.util.ArrayList;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatCode;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * 哈希链单元测试 · 对应 test-plan.md UT-B01/B02（R-04 红线：流水只增不改、哈希链可验篡改）。
 */
class HashChainServiceTest {

    private final HashChainService service = new HashChainService();

    private HashChainEntry entry(String flowId, String rowData, Instant at, String prevHash) {
        return new HashChainEntry(flowId, rowData, at, service.compute(prevHash, rowData, at));
    }

    private List<HashChainEntry> intactChain() {
        Instant t1 = Instant.parse("2026-01-15T10:30:00Z");
        Instant t2 = Instant.parse("2026-01-15T11:00:00Z");
        Instant t3 = Instant.parse("2026-02-03T09:15:00Z");
        List<HashChainEntry> chain = new ArrayList<>();
        HashChainEntry e1 = entry("flw_1", "PAYROLL|IN|3200.00|wx001", t1, service.genesisHash());
        HashChainEntry e2 = entry("flw_2", "REFUND|OUT|12.80|wx002", t2, e1.hash());
        HashChainEntry e3 = entry("flw_3", "SPLIT|IN|880.50|wx003", t3, e2.hash());
        chain.add(e1);
        chain.add(e2);
        chain.add(e3);
        return chain;
    }

    @Test
    @DisplayName("UT-B01: 创世哈希确定性（64 位小写 hex）")
    void ut_b01_genesisHashIsDeterministic() {
        String genesis = service.genesisHash();
        assertThat(genesis).matches("[0-9a-f]{64}");
        assertThat(service.genesisHash()).isEqualTo(genesis);
    }

    @Test
    @DisplayName("UT-B01: 同输入哈希确定")
    void ut_b01_computeIsDeterministic() {
        Instant at = Instant.parse("2026-01-15T10:30:00Z");
        String h1 = service.compute("prev", "PAYROLL|IN|3200.00", at);
        String h2 = service.compute("prev", "PAYROLL|IN|3200.00", at);
        assertThat(h1).matches("[0-9a-f]{64}");
        assertThat(h2).isEqualTo(h1);
    }

    @Test
    @DisplayName("UT-B01: 任一输入变化（前链/行数据/时间戳）哈希必变")
    void ut_b01_computeChangesWithAnyInput() {
        Instant at = Instant.parse("2026-01-15T10:30:00Z");
        String base = service.compute("prev", "PAYROLL|IN|3200.00", at);
        assertThat(service.compute("prev2", "PAYROLL|IN|3200.00", at)).isNotEqualTo(base);
        assertThat(service.compute("prev", "PAYROLL|IN|3200.01", at)).isNotEqualTo(base);
        assertThat(service.compute("prev", "PAYROLL|IN|3200.00", at.plusMillis(1))).isNotEqualTo(base);
    }

    @Test
    @DisplayName("UT-B02: 完整链验链通过")
    void ut_b02_verifyPassesOnIntactChain() {
        assertThatCode(() -> service.verify(intactChain())).doesNotThrowAnyException();
    }

    @Test
    @DisplayName("UT-B02: 篡改行数据（金额）被检出，定位下标 1")
    void ut_b02_verifyDetectsTamperedRowData() {
        List<HashChainEntry> chain = intactChain();
        HashChainEntry e = chain.get(1);
        chain.set(1, new HashChainEntry(e.flowId(), "REFUND|OUT|99.99|wx002", e.occurredAt(), e.hash()));
        assertThatThrownBy(() -> service.verify(chain))
                .isInstanceOfSatisfying(ChainVerificationException.class,
                        ex -> assertThat(ex.index()).isEqualTo(1));
    }

    @Test
    @DisplayName("UT-B02: 篡改 hash 字段被检出，定位下标 2")
    void ut_b02_verifyDetectsTamperedHash() {
        List<HashChainEntry> chain = intactChain();
        HashChainEntry e = chain.get(2);
        chain.set(2, new HashChainEntry(e.flowId(), e.rowData(), e.occurredAt(), "deadbeef"));
        assertThatThrownBy(() -> service.verify(chain))
                .isInstanceOfSatisfying(ChainVerificationException.class,
                        ex -> assertThat(ex.index()).isEqualTo(2));
    }

    @Test
    @DisplayName("UT-B02: 断链（首行 prev 非创世/中途掉链）被检出，定位下标 0")
    void ut_b02_verifyDetectsBrokenPrevLink() {
        List<HashChainEntry> chain = intactChain();
        HashChainEntry e = chain.get(0);
        chain.set(0, new HashChainEntry(e.flowId(), e.rowData(), e.occurredAt(), "cafebabe"));
        assertThatThrownBy(() -> service.verify(chain))
                .isInstanceOfSatisfying(ChainVerificationException.class,
                        ex -> assertThat(ex.index()).isEqualTo(0));
    }
}
