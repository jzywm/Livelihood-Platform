package com.msz.acc.application;

import com.msz.acc.application.port.ChannelStatement;
import com.msz.acc.application.port.ChannelStatementSource;
import com.msz.acc.application.port.FlowStatement;
import com.msz.acc.application.port.FlowStatementReader;
import com.msz.acc.domain.model.IdempotencyRecord;
import com.msz.acc.domain.service.ReconcileDecision;
import com.msz.acc.domain.support.AccBusinessException;
import com.msz.acc.repository.IdempotencyRecordMapper;
import com.msz.acc.repository.ReconcileTaskMapper;
import com.msz.common.idgen.IdGenerator;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.time.Clock;
import java.time.Instant;
import java.time.LocalDate;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * ReconcileFlowTest（UT-D01~D03/D05 口径）：diff=0 → DONE；diff>0 → DIFF + alertCode 3009；
 * 同 Idempotency-Key 重复触发返回原任务；日期非法 1002/1003。
 */
class ReconcileFlowTest {

    private ReconcileTaskMapper taskMapper;
    private IdempotencyRecordMapper idempotencyRecordMapper;
    private IdGenerator idGenerator;
    private FakeChannelStatementSource channelSource;
    private FakeFlowStatementReader flowReader;
    private ReconcileFlow flow;

    @BeforeEach
    void setUp() {
        taskMapper = mock(ReconcileTaskMapper.class);
        idempotencyRecordMapper = mock(IdempotencyRecordMapper.class);
        idGenerator = mock(IdGenerator.class);
        channelSource = new FakeChannelStatementSource();
        flowReader = new FakeFlowStatementReader();
        Clock clock = Clock.fixed(Instant.parse("2026-01-15T00:00:00Z"), ZoneOffset.UTC);
        InlineReconcileExecutor executor = new InlineReconcileExecutor(channelSource, flowReader);
        flow = new ReconcileFlow(taskMapper, idempotencyRecordMapper, idGenerator, executor,
                new ReconcileDecision(), clock);
    }

    @Test
    @DisplayName("UT-D02: 对账 diff=0 → DONE")
    void ut_reconcileNoDiffDone() {
        Instant at = Instant.parse("2026-01-05T10:00:00Z");
        channelSource.statements = List.of(new ChannelStatement("wx1", "10.00", at));
        flowReader.statements = List.of(new FlowStatement("wx1", "10.00", at));
        when(idGenerator.nextId()).thenReturn(1L);
        when(idempotencyRecordMapper.insertIgnore(anyString(), anyString(), anyInt(), anyString())).thenReturn(1);

        ReconcileResult result = flow.trigger("2026-01-01", "2026-01-31", "k1");

        assertThat(result.reconcileId()).isEqualTo("rec_1");
        assertThat(result.status()).isEqualTo("DONE");
        assertThat(result.diffCount()).isZero();
        assertThat(result.alertCode()).isZero();
        verify(taskMapper).insert(any());
        verify(taskMapper).finish(eq("rec_1"), eq("DONE"), eq(0L), any());
    }

    @Test
    @DisplayName("UT-D03: 对账 diff>0 → DIFF + alertCode 3009")
    void ut_reconcileDiffAlerts() {
        channelSource.statements = List.of(new ChannelStatement("wx1", "10.00", Instant.parse("2026-01-05T10:00:00Z")));
        flowReader.statements = List.of();
        when(idGenerator.nextId()).thenReturn(2L);
        when(idempotencyRecordMapper.insertIgnore(anyString(), anyString(), anyInt(), anyString())).thenReturn(1);

        ReconcileResult result = flow.trigger("2026-01-01", "2026-01-31", "k2");

        assertThat(result.reconcileId()).isEqualTo("rec_2");
        assertThat(result.status()).isEqualTo("DIFF");
        assertThat(result.diffCount()).isEqualTo(1L);
        assertThat(result.alertCode()).isEqualTo(3009);
        verify(taskMapper).finish(eq("rec_2"), eq("DIFF"), eq(1L), any());
    }

    @Test
    @DisplayName("UT-D04: 同 Idempotency-Key 重复触发 → 返回原任务")
    void ut_sameKeyReturnsOriginalTask() {
        when(idGenerator.nextId()).thenReturn(3L);
        when(idempotencyRecordMapper.insertIgnore(anyString(), anyString(), anyInt(), anyString()))
                .thenReturn(1, 0);
        IdempotencyRecord record = new IdempotencyRecord();
        record.setResponsePayload("rec_3|DONE|0|0");
        when(idempotencyRecordMapper.selectByKey("k3")).thenReturn(record);

        ReconcileResult first = flow.trigger("2026-01-01", "2026-01-31", "k3");
        ReconcileResult second = flow.trigger("2026-01-01", "2026-01-31", "k3");

        assertThat(first.reconcileId()).isEqualTo("rec_3");
        assertThat(second.reconcileId()).isEqualTo("rec_3");
        verify(taskMapper, times(1)).insert(any());
    }

    @Test
    @DisplayName("UT-F09: 日期解析失败 → 1002；from>to → 1003")
    void ut_invalidDatesRejected() {
        assertThatThrownBy(() -> flow.trigger("2026-13-01", "2026-01-31", "k4"))
                .isInstanceOfSatisfying(AccBusinessException.class,
                        e -> assertThat(e.code()).isEqualTo(1002));
        assertThatThrownBy(() -> flow.trigger("2026-02-01", "2026-01-01", "k5"))
                .isInstanceOfSatisfying(AccBusinessException.class,
                        e -> assertThat(e.code()).isEqualTo(1003));
        verify(taskMapper, never()).insert(any());
    }

    private static final class FakeChannelStatementSource implements ChannelStatementSource {
        private List<ChannelStatement> statements = new ArrayList<>();

        @Override
        public List<ChannelStatement> statements(LocalDate from, LocalDate to) {
            return statements;
        }
    }

    private static final class FakeFlowStatementReader implements FlowStatementReader {
        private List<FlowStatement> statements = new ArrayList<>();

        @Override
        public List<FlowStatement> read(LocalDate from, LocalDate to) {
            return statements;
        }
    }
}
