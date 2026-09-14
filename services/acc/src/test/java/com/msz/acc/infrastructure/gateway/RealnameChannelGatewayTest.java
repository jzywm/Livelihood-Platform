package com.msz.acc.infrastructure.gateway;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.msz.acc.domain.support.AccBusinessException;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.startsWith;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * RealnameChannelGateway（S5 端口适配）：授权成功返回模板拼接 authorizeUrl；
 * 通道不可用/非 2xx → 4001（R-02 不静默降级）；超时 → 5002。
 */
class RealnameChannelGatewayTest {

    private static final String TEMPLATE = "https://open.example/authorize?bizId={bizId}";

    private final HttpChannelClient client = mock(HttpChannelClient.class);
    private final RealnameChannelGateway gateway =
            new RealnameChannelGateway(client, "http://channel:9999", TEMPLATE, new ObjectMapper());

    @Test
    @DisplayName("授权成功 → 返回模板拼接 bizId 的 authorizeUrl")
    void ut_authorizeSuccessReturnsTemplateUrl() {
        when(client.postJson(startsWith("http://channel:9999/realname/authorize"), anyString(), anyLong()))
                .thenReturn("{\"ok\":true}");

        String url = gateway.requestAuthorization("rz_1", "13800138000", "CONSUMER");

        assertThat(url).isEqualTo("https://open.example/authorize?bizId=rz_1");
    }

    @Test
    @DisplayName("通道不可用 → AccBusinessException(4001)")
    void ut_channelUnavailableRejected4001() {
        when(client.postJson(anyString(), anyString(), anyLong()))
                .thenThrow(new ChannelUnavailableException("connect refused"));

        assertThatThrownBy(() -> gateway.requestAuthorization("rz_1", "13800138000", "CONSUMER"))
                .isInstanceOfSatisfying(AccBusinessException.class,
                        e -> assertThat(e.code()).isEqualTo(4001));
    }

    @Test
    @DisplayName("通道超时 → AccBusinessException(5002)")
    void ut_timeoutRejected5002() {
        when(client.postJson(anyString(), anyString(), anyLong()))
                .thenThrow(new ChannelTimeoutException("timeout"));

        assertThatThrownBy(() -> gateway.requestAuthorization("rz_1", "13800138000", "CONSUMER"))
                .isInstanceOfSatisfying(AccBusinessException.class,
                        e -> assertThat(e.code()).isEqualTo(5002));
    }

    @Test
    @DisplayName("queryResult：解析通道回查结果；失败 → 4001")
    void ut_queryResult() {
        when(client.get(startsWith("http://channel:9999/realname/result/rz_1"), anyLong()))
                .thenReturn("{\"openId\":\"openid-1\",\"name\":\"张三\",\"idNo\":\"110101199001011234\",\"pass\":true}");

        var result = gateway.queryResult("rz_1");
        assertThat(result.openId()).isEqualTo("openid-1");
        assertThat(result.name()).isEqualTo("张三");
        assertThat(result.passed()).isTrue();

        when(client.get(anyString(), anyLong())).thenThrow(new ChannelUnavailableException("down"));
        assertThatThrownBy(() -> gateway.queryResult("rz_2"))
                .isInstanceOfSatisfying(AccBusinessException.class,
                        e -> assertThat(e.code()).isEqualTo(4001));
    }
}
