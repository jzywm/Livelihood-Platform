package com.msz.acc.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * ACC 服务配置（前缀 {@code acc.*}）。
 *
 * <ul>
 *   <li>{@code acc.internal-token}：内部接口鉴权 token（默认测试值，测试环境可改）。</li>
 *   <li>{@code acc.callback-secret}：实名回调验签密钥（HMAC-SHA256，默认测试值）。</li>
 *   <li>{@code acc.realname.authorize-url-template}：实名授权跳转模板，占位符 {@code {bizId}}。</li>
 *   <li>{@code acc.jwt-secret}：JWT HS256 签名密钥（默认测试值）；**同时用于短 token 与 refresh**。</li>
 *   <li>{@code acc.channel.*-base-url}：实名/支付/账单通道基址（M1 默认本地占位，测试经 WireMock 注入）。</li>
 *   <li>{@code acc.redis.*}：会话存储 Redis 连接（R-A6）——{@code acc.session.store=redis} 时**必填**
 *       （缺 {@code host} 即启动失败，见 {@code AccConfiguration#sessionStore}）；未配置时
 *       {@code SessionStore} 由 {@code acc.session.store}（默认 {@code memory}）决定，进程内实现
 *       **仅单元测试/演练兜底，不可用于生产**（进程内存储无法与网关共享吊销名单 ⇒ 登出/踢人失效）。</li>
 *   <li>{@code acc.session.*}：会话凭据配置（R-A7 + L1/R-A8，与 PDD v1.18 §8.4.1 口径一致）：
 *       {@code store}（{@code memory}|{@code redis}，默认 {@code memory}；**生产必须设 redis**）。</li>
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
    private final Redis redis = new Redis();
    private final Session session = new Session();

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

    public Redis getRedis() {
        return redis;
    }

    public Session getSession() {
        return session;
    }

    /**
     * 会话存储 Redis 连接（{@code acc.redis.*}）。
     *
     * <p>{@code host} 默认空串 = **未配置**。{@code acc.session.store=redis} 时必填（缺失即启动失败）；
     * 生产部署必须指向网关读取 `revoked:jti:*` 的**同一个实例**。</p>
     */
    public static class Redis {

        private String host = "";
        private int port = 6379;
        private String username = "";
        private String password = "";

        public String getHost() {
            return host;
        }

        public void setHost(String host) {
            this.host = host;
        }

        public int getPort() {
            return port;
        }

        public void setPort(int port) {
            this.port = port;
        }

        public String getUsername() {
            return username;
        }

        public void setUsername(String username) {
            this.username = username;
        }

        public String getPassword() {
            return password;
        }

        public void setPassword(String password) {
            this.password = password;
        }
    }

    /**
     * 会话凭据配置（{@code acc.session.*}，R-A7）。
     *
     * <p>默认值与 PDD v1.18 §8.4.1 / 高并发 v0.9 §7.3 定档口径一致：短 token 15 分钟
     * （**不得超网关上限** {@code gateway.auth.access-token-max-ttl}=15m）、refresh 7 天、
     * 轮换宽限 5 秒、Cookie `HttpOnly; Secure; SameSite=Lax; Path=/api/v1/acc/auth`。</p>
     */
    public static class Session {

        /** 会话存储实现：{@code memory}（默认，仅测试/演练）| {@code redis}（生产，必须配 acc.redis.host）。 */
        private String store = "memory";

        /** 短 token 有效期（秒）。默认 900 = 15 分钟；**超过 15 分钟会被网关按策略拒绝**。 */
        private long accessTokenTtlSeconds = 900L;

        /** 长 token（refresh）有效期（秒）。默认 604800 = 7 天。 */
        private long refreshTokenTtlSeconds = 604_800L;

        /** 轮换并发宽限窗口（秒）：窗口内重复换发按并发重试处理，不判泄露。 */
        private long rotationGraceSeconds = 5L;

        /** 换发/仅凭 Cookie 登出允许的来源（逗号分隔，如 {@code https://app.example.com}）；默认空 = 仅同源。 */
        private String allowedOrigins = "";

        /** refresh Cookie 名。 */
        private String cookieName = "refresh_token";

        /** refresh Cookie 是否带 Secure（生产必须 true；本地 HTTP 演练可置 false）。 */
        private boolean cookieSecure = true;

        /** refresh Cookie SameSite 取值（Lax/Strict/None；None 需配合 Secure）。 */
        private String cookieSameSite = "Lax";

        public String getStore() {
            return store;
        }

        public void setStore(String store) {
            this.store = store;
        }

        public long getAccessTokenTtlSeconds() {
            return accessTokenTtlSeconds;
        }

        public void setAccessTokenTtlSeconds(long accessTokenTtlSeconds) {
            this.accessTokenTtlSeconds = accessTokenTtlSeconds;
        }

        public long getRefreshTokenTtlSeconds() {
            return refreshTokenTtlSeconds;
        }

        public void setRefreshTokenTtlSeconds(long refreshTokenTtlSeconds) {
            this.refreshTokenTtlSeconds = refreshTokenTtlSeconds;
        }

        public long getRotationGraceSeconds() {
            return rotationGraceSeconds;
        }

        public void setRotationGraceSeconds(long rotationGraceSeconds) {
            this.rotationGraceSeconds = rotationGraceSeconds;
        }

        public String getAllowedOrigins() {
            return allowedOrigins;
        }

        public void setAllowedOrigins(String allowedOrigins) {
            this.allowedOrigins = allowedOrigins;
        }

        public String getCookieName() {
            return cookieName;
        }

        public void setCookieName(String cookieName) {
            this.cookieName = cookieName;
        }

        public boolean isCookieSecure() {
            return cookieSecure;
        }

        public void setCookieSecure(boolean cookieSecure) {
            this.cookieSecure = cookieSecure;
        }

        public String getCookieSameSite() {
            return cookieSameSite;
        }

        public void setCookieSameSite(String cookieSameSite) {
            this.cookieSameSite = cookieSameSite;
        }
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
