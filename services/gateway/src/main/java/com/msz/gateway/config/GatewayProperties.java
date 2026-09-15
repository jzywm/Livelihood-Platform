package com.msz.gateway.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

import java.time.Duration;
import java.util.List;

/**
 * 网关配置(F8 配置总表):鉴权(白名单/JWT 密钥/令牌有效期上限)、三级限流初值、存储模式。
 *
 * <p>路由表使用 Spring Cloud Gateway 原生键位 {@code spring.cloud.gateway.routes}
 * (含 {@code metadata.timeout} 路由级超时、{@code metadata.weight} 灰度权重预留);
 * 业务键位全部收敛在 {@code gateway.*} 下。</p>
 */
@ConfigurationProperties(prefix = "gateway")
public record GatewayProperties(Auth auth, RateLimit rateLimit, Store store, List<String> internalPaths) {

    /** 路由级默认超时(内部服务 1s 分级)。 */
    public static final int DEFAULT_TIMEOUT_MS = 1000;

    /** 存储模式:REDIS 生产(吊销/限流走 Redis);MEMORY 开发兜底(M1 无 Redis 部署,同 acc 惯例)。 */
    public enum Store { REDIS, MEMORY }

    public record Auth(List<String> whitelist, String jwtSecret, Duration accessTokenMaxTtl, Duration clockSkew) {

        /** 访问令牌(短 token)有效期上限(2026-09-15 用户裁决:短 token 15 分钟)。 */
        public static final Duration DEFAULT_ACCESS_TOKEN_MAX_TTL = Duration.ofMinutes(15);

        /** 时钟容差:仅用于放宽有效期上限判定,不用于放宽过期判定(过期仍严格按当前时间)。 */
        public static final Duration DEFAULT_CLOCK_SKEW = Duration.ofSeconds(60);

        /**
         * 便捷构造(缺省令牌策略:短 token 15 分钟 + 容差 60s)。
         *
         * <p>注意:必须是**静态工厂**而非第二构造器——{@code @ConfigurationProperties} 的记录绑定
         * 要求「唯一构造器」,加第二构造器会让 Spring 无法确定绑定入口(实测 {@code auth()} 绑定为 null,
         * 见 2026-09-15 回归)。</p>
         */
        public static Auth of(List<String> whitelist, String jwtSecret) {
            return new Auth(whitelist, jwtSecret, DEFAULT_ACCESS_TOKEN_MAX_TTL, DEFAULT_CLOCK_SKEW);
        }

        /** 归一:未配置(绑定缺省)时回落默认策略,避免 null 漏过校验。 */
        public Auth {
            if (accessTokenMaxTtl == null) {
                accessTokenMaxTtl = DEFAULT_ACCESS_TOKEN_MAX_TTL;
            }
            if (clockSkew == null) {
                clockSkew = DEFAULT_CLOCK_SKEW;
            }
        }
    }

    /** 三级限流初值(TBD-3 定档):读 1000/s/账号、写 100/s/账号、AI 10/min/账号、资金 100/s、IP 200/s。 */
    public record RateLimit(Limit ip, Limit read, Limit write, Limit ai, Limit funds) {

        public static RateLimit defaults() {
            return new RateLimit(
                    new Limit(200, 1),
                    new Limit(1000, 1),
                    new Limit(100, 1),
                    new Limit(10, 60),
                    new Limit(100, 1));
        }

        /** 分级 → 容量(资金链路独立桶,不被其他流量挤占)。 */
        public Limit limitFor(com.msz.gateway.ratelimit.Tier tier) {
            return switch (tier) {
                case AI -> ai;
                case FUNDS -> funds;
                case WRITE -> write;
                case READ -> read;
            };
        }
    }

    /** 单级桶:capacity = 窗口内允许次数,windowSeconds = 窗口秒。 */
    public record Limit(int capacity, long windowSeconds) {
    }

    /**
     * 配置校验(启动 fail-fast):REDIS 存储模式必须有 JWT 签名密钥
     * (env GATEWAY_JWT_SECRET,生产 KMS 注入,密钥不出网关);MEMORY 模式仅开发/测试,允许空密钥。
     */
    public static void validate(GatewayProperties props) {
        boolean secretBlank = props.auth() == null
                || props.auth().jwtSecret() == null
                || props.auth().jwtSecret().isBlank();
        if (props.store() == Store.REDIS && secretBlank) {
            throw new IllegalStateException(
                    "gateway.auth.jwt-secret 不能为空(REDIS 模式需真实 HS256 密钥,env GATEWAY_JWT_SECRET 注入)");
        }
    }
}
