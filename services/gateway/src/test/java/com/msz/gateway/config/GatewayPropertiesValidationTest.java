package com.msz.gateway.config;

import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThatCode;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * 启动校验边界:auth 段缺失 / 密钥为空 / 存储模式组合(启动 fail-fast)。
 */
class GatewayPropertiesValidationTest {

    @Test
    void rejectsMissingAuthWhenRedisStore() {
        GatewayProperties props = new GatewayProperties(
                null, GatewayProperties.RateLimit.defaults(),
                GatewayProperties.Store.REDIS, List.of());

        assertThatThrownBy(() -> GatewayProperties.validate(props))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("jwt-secret");
    }

    @Test
    void rejectsNullSecretWhenRedisStore() {
        GatewayProperties props = new GatewayProperties(
                GatewayProperties.Auth.of(List.of(), null),
                GatewayProperties.RateLimit.defaults(),
                GatewayProperties.Store.REDIS, List.of());

        assertThatThrownBy(() -> GatewayProperties.validate(props))
                .isInstanceOf(IllegalStateException.class);
    }

    @Test
    void acceptsSecretWhenRedisStore() {
        GatewayProperties props = new GatewayProperties(
                GatewayProperties.Auth.of(List.of("/api/v1/acc/captcha"), "s3cret"),
                GatewayProperties.RateLimit.defaults(),
                GatewayProperties.Store.REDIS, List.of());

        assertThatCode(() -> GatewayProperties.validate(props)).doesNotThrowAnyException();
    }

    @Test
    void limitForReturnsTierBucket() {
        GatewayProperties.RateLimit limits = new GatewayProperties.RateLimit(
                new GatewayProperties.Limit(1, 1),
                new GatewayProperties.Limit(2, 1),
                new GatewayProperties.Limit(3, 1),
                new GatewayProperties.Limit(4, 60),
                new GatewayProperties.Limit(5, 1));

        assertThatCode(() -> {
            org.assertj.core.api.Assertions.assertThat(
                    limits.limitFor(com.msz.gateway.ratelimit.Tier.AI).capacity()).isEqualTo(4);
            org.assertj.core.api.Assertions.assertThat(
                    limits.limitFor(com.msz.gateway.ratelimit.Tier.FUNDS).capacity()).isEqualTo(5);
            org.assertj.core.api.Assertions.assertThat(
                    limits.limitFor(com.msz.gateway.ratelimit.Tier.WRITE).capacity()).isEqualTo(3);
            org.assertj.core.api.Assertions.assertThat(
                    limits.limitFor(com.msz.gateway.ratelimit.Tier.READ).capacity()).isEqualTo(2);
        }).doesNotThrowAnyException();
    }

    @Test
    void defaultsProvideDocumentedInitialValues() {
        GatewayProperties.RateLimit limits = GatewayProperties.RateLimit.defaults();

        org.assertj.core.api.Assertions.assertThat(limits.ip().capacity()).isEqualTo(200);
        org.assertj.core.api.Assertions.assertThat(limits.read().capacity()).isEqualTo(1000);
        org.assertj.core.api.Assertions.assertThat(limits.write().capacity()).isEqualTo(100);
        org.assertj.core.api.Assertions.assertThat(limits.ai().capacity()).isEqualTo(10);
        org.assertj.core.api.Assertions.assertThat(limits.ai().windowSeconds()).isEqualTo(60);
        org.assertj.core.api.Assertions.assertThat(limits.funds().capacity()).isEqualTo(100);

        Map<String, Object> unused = Map.of();
        org.assertj.core.api.Assertions.assertThat(unused).isEmpty();
    }
}
