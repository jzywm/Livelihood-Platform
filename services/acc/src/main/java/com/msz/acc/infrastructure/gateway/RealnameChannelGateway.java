package com.msz.acc.infrastructure.gateway;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.msz.acc.application.port.ChannelQueryResult;
import com.msz.acc.application.port.RealnameChannelPort;
import com.msz.acc.domain.support.AccBusinessException;

/**
 * 第三方实名通道网关（S5 端口适配）：POST /realname/authorize 发起授权、GET /realname/result/{bizId} 回查。
 *
 * <p>唯一口径 R-02：通道不可用/非 2xx → 4001（不静默降级）；超时 → 5002（依赖超时/熔断）。
 * authorizeUrl 由配置模板 {@code acc.realname.authorize-url-template} 拼接 bizId。</p>
 */
public final class RealnameChannelGateway implements RealnameChannelPort {

    private static final long TIMEOUT_MILLIS = 3000;

    private final HttpChannelClient client;
    private final String baseUrl;
    private final String authorizeUrlTemplate;
    private final ObjectMapper mapper;

    public RealnameChannelGateway(HttpChannelClient client, String baseUrl,
                                  String authorizeUrlTemplate, ObjectMapper mapper) {
        this.client = client;
        this.baseUrl = baseUrl;
        this.authorizeUrlTemplate = authorizeUrlTemplate;
        this.mapper = mapper;
    }

    @Override
    public String requestAuthorization(String bizId, String mobile, String role) {
        String body = "{\"bizId\":\"" + bizId + "\",\"mobile\":\"" + mobile + "\",\"role\":\"" + role + "\"}";
        try {
            client.postJson(baseUrl + "/realname/authorize", body, TIMEOUT_MILLIS);
        } catch (ChannelTimeoutException e) {
            throw new AccBusinessException(5002, "实名通道超时");
        } catch (ChannelUnavailableException e) {
            throw new AccBusinessException(4001, "实名通道不可用");
        }
        return authorizeUrlTemplate.replace("{bizId}", bizId);
    }

    @Override
    public ChannelQueryResult queryResult(String bizId) {
        String body;
        try {
            body = client.get(baseUrl + "/realname/result/" + bizId, TIMEOUT_MILLIS);
        } catch (ChannelTimeoutException e) {
            throw new AccBusinessException(5002, "实名通道超时");
        } catch (ChannelUnavailableException e) {
            throw new AccBusinessException(4001, "实名通道不可用");
        }
        try {
            JsonNode node = mapper.readTree(body);
            return new ChannelQueryResult(
                    text(node, "openId"),
                    text(node, "name"),
                    text(node, "idNo"),
                    node.has("pass") && node.get("pass").asBoolean());
        } catch (Exception e) {
            throw new AccBusinessException(4001, "实名通道回查响应异常");
        }
    }

    private static String text(JsonNode node, String field) {
        JsonNode value = node.get(field);
        return value == null || value.isNull() ? null : value.asText();
    }
}
