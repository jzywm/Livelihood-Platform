package com.msz.acc.infrastructure.gateway;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.msz.acc.application.port.PaymentChannelPort;
import com.msz.acc.domain.support.AccBusinessException;

/**
 * 支付通道网关（S5 端口适配）：POST /verify-payee 校验收款账户（户名与实名一致性由通道校验）。
 *
 * <p>通道判定 {@code matched=false}（户名不符）→ 3002；超时/不可用/响应异常 → 4002（可重试口径）。</p>
 */
public final class PaymentChannelGateway implements PaymentChannelPort {

    private static final long TIMEOUT_MILLIS = 2000;

    private final HttpChannelClient client;
    private final String baseUrl;
    private final ObjectMapper mapper;

    public PaymentChannelGateway(HttpChannelClient client, String baseUrl, ObjectMapper mapper) {
        this.client = client;
        this.baseUrl = baseUrl;
        this.mapper = mapper;
    }

    @Override
    public void verifyPayee(long accountId, String channel, String payeeAccount, String realName) {
        String body = "{\"accountId\":" + accountId + ",\"channel\":\"" + channel
                + "\",\"payeeAccount\":\"" + payeeAccount + "\",\"realName\":\"" + realName + "\"}";
        String response;
        try {
            response = client.postJson(baseUrl + "/verify-payee", body, TIMEOUT_MILLIS);
        } catch (ChannelTimeoutException e) {
            throw new AccBusinessException(4002, "支付通道超时");
        } catch (ChannelUnavailableException e) {
            throw new AccBusinessException(4002, "支付通道不可用");
        }
        try {
            JsonNode node = mapper.readTree(response);
            if (node.has("matched") && !node.get("matched").asBoolean()) {
                throw new AccBusinessException(3002, "户名与实名不一致");
            }
        } catch (AccBusinessException e) {
            throw e;
        } catch (Exception e) {
            throw new AccBusinessException(4002, "支付通道响应异常");
        }
    }
}
