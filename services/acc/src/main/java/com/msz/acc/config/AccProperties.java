package com.msz.acc.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * ACC 服务配置（前缀 {@code acc.*}）。
 *
 * <ul>
 *   <li>{@code acc.internal-token}：内部接口鉴权 token（默认测试值，测试环境可改）。</li>
 *   <li>{@code acc.callback-secret}：实名回调验签密钥（HMAC-SHA256，默认测试值）。</li>
 *   <li>{@code acc.realname.authorize-url-template}：实名授权跳转模板，占位符 {@code {bizId}}。</li>
 *   <li>{@code acc.jwt-secret}：JWT HS256 签名密钥（默认测试值）。</li>
 *   <li>{@code acc.channel.*-base-url}：实名/支付/账单通道基址（M1 默认本地占位，测试经 WireMock 注入）。</li>
 * </ul>
 */
@ConfigurationProperties(prefix = "acc")
public class AccProperties {

    private String internalToken = "acc-internal-test-token";
    private String callbackSecret = "acc-callback-test-secret";
    private String jwtSecret = "acc-jwt-test-secret-0123456789abcdef";
    private String realnameAuthorizeUrlTemplate =
            "https://open.weixin.qq.com/connect/oauth2/authorize?bizId={bizId}";
    private final Channel channel = new Channel();

    public String getInternalToken() {
        return internalToken;
    }

    public void setInternalToken(String internalToken) {
        this.internalToken = internalToken;
    }

    public String getCallbackSecret() {
        return callbackSecret;
    }

    public void setCallbackSecret(String callbackSecret) {
        this.callbackSecret = callbackSecret;
    }

    public String getJwtSecret() {
        return jwtSecret;
    }

    public void setJwtSecret(String jwtSecret) {
        this.jwtSecret = jwtSecret;
    }

    public String getRealnameAuthorizeUrlTemplate() {
        return realnameAuthorizeUrlTemplate;
    }

    public void setRealnameAuthorizeUrlTemplate(String realnameAuthorizeUrlTemplate) {
        this.realnameAuthorizeUrlTemplate = realnameAuthorizeUrlTemplate;
    }

    public Channel getChannel() {
        return channel;
    }

    /** 第三方通道基址（{@code acc.channel.*}）。 */
    public static class Channel {

        private String realnameBaseUrl = "http://localhost:9999";
        private String paymentBaseUrl = "http://localhost:9998";
        private String statementBaseUrl = "http://localhost:9997";

        public String getRealnameBaseUrl() {
            return realnameBaseUrl;
        }

        public void setRealnameBaseUrl(String realnameBaseUrl) {
            this.realnameBaseUrl = realnameBaseUrl;
        }

        public String getPaymentBaseUrl() {
            return paymentBaseUrl;
        }

        public void setPaymentBaseUrl(String paymentBaseUrl) {
            this.paymentBaseUrl = paymentBaseUrl;
        }

        public String getStatementBaseUrl() {
            return statementBaseUrl;
        }

        public void setStatementBaseUrl(String statementBaseUrl) {
            this.statementBaseUrl = statementBaseUrl;
        }
    }
}
