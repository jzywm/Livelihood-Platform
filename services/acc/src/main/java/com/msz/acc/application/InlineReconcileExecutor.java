package com.msz.acc.application;

import com.msz.acc.application.port.ChannelStatement;
import com.msz.acc.application.port.ChannelStatementSource;
import com.msz.acc.application.port.FlowStatement;
import com.msz.acc.application.port.FlowStatementReader;
import com.msz.acc.application.port.ReconcileExecutor;

import java.time.LocalDate;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * 同步对账执行器（4.6）：逐笔对 channelOrderNo+amount 做多重集对称差，返回不一致笔数。
 * 异步核对（从库/不压 OLTP）作为后续演进，S4 提供同步实现。
 */
public final class InlineReconcileExecutor implements ReconcileExecutor {

    private final ChannelStatementSource channelStatementSource;
    private final FlowStatementReader flowStatementReader;

    public InlineReconcileExecutor(ChannelStatementSource channelStatementSource,
                                   FlowStatementReader flowStatementReader) {
        this.channelStatementSource = channelStatementSource;
        this.flowStatementReader = flowStatementReader;
    }

    @Override
    public long compare(LocalDate from, LocalDate to) {
        List<ChannelStatement> channel = channelStatementSource.statements(from, to);
        List<FlowStatement> platform = flowStatementReader.read(from, to);
        Map<String, Long> channelCounts = counts(channel.stream().map(s -> key(s)).toList());
        Map<String, Long> platformCounts = counts(platform.stream().map(s -> key(s)).toList());
        Set<String> keys = new HashSet<>(channelCounts.keySet());
        keys.addAll(platformCounts.keySet());
        long diff = 0L;
        for (String k : keys) {
            diff += Math.abs(channelCounts.getOrDefault(k, 0L) - platformCounts.getOrDefault(k, 0L));
        }
        return diff;
    }

    private static String key(ChannelStatement s) {
        return s.channelOrderNo() + "|" + s.amount();
    }

    private static String key(FlowStatement s) {
        return s.channelOrderNo() + "|" + s.amount();
    }

    private static Map<String, Long> counts(List<String> keys) {
        Map<String, Long> result = new HashMap<>();
        for (String k : keys) {
            result.merge(k, 1L, Long::sum);
        }
        return result;
    }
}
