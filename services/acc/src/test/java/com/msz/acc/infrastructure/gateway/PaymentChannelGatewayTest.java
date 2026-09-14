package com.msz.acc.infrastructure.gateway;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.msz.acc.domain.support.AccBusinessException;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatCode;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * PaymentChannelGateway（S5 端口适配）：POST /verify-payee——matched=true 通过；
 * matched=false（户名与实名不一致）→ 3002；超时/不可用/响应异常 → 4002。
 */
class PaymentChannelGatewayTest {

    private final HttpChannelClient client = mock(HttpChannelClient.class);
    private final PaymentChannelGateway gateway =
            new PaymentChannelGateway(client, "http://pay:9998", new ObjectMapper());

    @Test
    @DisplayName("matched=true → 校验通过")
    void ut_matchedPasses() {
        when(client.postJson(anyString(), anyString(), anyLong())).thenReturn("{\"matched\":true}");

        assertThatCode(() -> gateway.verifyPayee(1L, "WECHAT", "6222021234567890", "张三"))
                .doesNotThrowAnyException();
    }

    @Test
    @DisplayName("matched=false（户名不符）→ AccBusinessException(3002)")
    void ut_nameMismatchRejected3002() {
        when(client.postJson(anyString(), anyString(), anyLong())).thenReturn("{\"matched\":false}");

        assertThatThrownBy(() -> gateway.verifyPayee(1L, "WECHAT", "6222021234567890", "张三"))
                .isInstanceOfSatisfying(AccBusinessException.class,
                        e -> assertThat(e.code()).isEqualTo(3002));
    }

    @Test
    @DisplayName("通道超时 → AccBusinessException(4002)")
    void ut_timeoutRejected4002() {
        when(client.postJson(anyString(), anyString(), anyLong()))
                .thenThrow(new ChannelTimeoutException("timeout"));

        assertThatThrownBy(() -> gateway.verifyPayee(1L, "WECHAT", "6222021234567890", "张三"))
                .isInstanceOfSatisfying(AccBusinessException.class,
                        e -> assertThat(e.code()).isEqualTo(4002));
    }

    @Test
    @DisplayName("通道不可用 → AccBusinessException(4002)")
    void ut_unavailableRejected4002() {
        when(client.postJson(anyString(), anyString(), anyLong()))
                .thenThrow(new ChannelUnavailableException("down"));

        assertThatThrownBy(() -> gateway.verifyPayee(1L, "WECHAT", "6222021234567890", "张三"))
                .isInstanceOfSatisfying(AccBusinessException.class,
                        e -> assertThat(e.code()).isEqualTo(4002));
    }

    @Test
    @DisplayName("响应不可解析 → AccBusinessException(4002)")
    void ut_malformedResponseRejected4002() {
        when(client.postJson(anyString(), anyString(), anyLong())).thenReturn("not-json");

        assertThatThrownBy(() -> gateway.verifyPayee(1L, "WECHAT", "6222021234567890", "张三"))
                .isInstanceOfSatisfying(AccBusinessException.class,
                        e -> assertThat(e.code()).isEqualTo(4002));
    }
}
