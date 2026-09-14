package com.msz.acc.infrastructure.gateway;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.msz.acc.application.port.ChannelStatement;
import com.msz.acc.application.port.ChannelStatementSource;
import com.msz.acc.domain.support.AccBusinessException;

import java.time.Instant;
import java.time.LocalDate;
import java.util.List;

/**
 * 通道账单源（S5 端口适配）：GET /statements?from=&to= 拉取第三方通道流水账单。
 * 失败/超时 → 4002（通道口径，可重试）。
 */
public final class HttpChannelStatementSource implements ChannelStatementSource {

    private static final long TIMEOUT_MILLIS = 5000;

    private final HttpChannelClient client;
    private final String baseUrl;
    private final ObjectMapper mapper;

    public HttpChannelStatementSource(HttpChannelClient client, String baseUrl, ObjectMapper mapper) {
        this.client = client;
        this.baseUrl = baseUrl;
        this.mapper = mapper;
    }

    @Override
    public List<ChannelStatement> statements(LocalDate from, LocalDate to) {
        String url = baseUrl + "/statements?from=" + from + "&to=" + to;
        String body;
        try {
            body = client.get(url, TIMEOUT_MILLIS);
        } catch (ChannelTimeoutException e) {
            throw new AccBusinessException(4002, "通道账单拉取超时");
        } catch (ChannelUnavailableException e) {
            throw new AccBusinessException(4002, "通道账单拉取失败");
        }
        try {
            List<StatementBody> items = mapper.readValue(body, new TypeReference<>() {
            });
            return items.stream()
                    .map(s -> new ChannelStatement(s.channelOrderNo(), s.amount(),
                            s.occurredAt() == null ? null : Instant.parse(s.occurredAt())))
                    .toList();
        } catch (Exception e) {
            throw new AccBusinessException(4002, "通道账单响应异常");
        }
    }

    private record StatementBody(String channelOrderNo, String amount, String occurredAt) {
    }
}
