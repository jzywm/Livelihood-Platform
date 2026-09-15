package com.msz.gateway.config;

import org.junit.jupiter.api.Test;
import org.springframework.boot.context.properties.bind.Binder;
import org.springframework.boot.context.properties.source.MapConfigurationPropertySource;

import java.time.Duration;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class GatewayPropertiesTest {

    @Test
    void bindsAuthWhitelistSecretAndStore() {
        MapConfigurationPropertySource source = new MapConfigurationPropertySource(Map.of(
                "gateway.auth.whitelist", List.of("/api/v1/acc/captcha", "/api/v1/acc/register"),
                "gateway.auth.jwt-secret", "s3cret",
                "gateway.store", "MEMORY"
        ));

        GatewayProperties bound = new Binder(source).bind("gateway", GatewayProperties.class).get();

        assertThat(bound.auth().whitelist()).containsExactly("/api/v1/acc/captcha", "/api/v1/acc/register");
        assertThat(bound.auth().jwtSecret()).isEqualTo("s3cret");
        assertThat(bound.store()).isEqualTo(GatewayProperties.Store.MEMORY);
    }

    @Test
    void bindsTokenPolicyAndFallsBackToAccessToken15Minutes() {
        // 只配了 auth 的既有键 → 令牌策略回落默认(短 token 15 分钟 + 容差 60s)
        GatewayProperties defaults = new Binder(new MapConfigurationPropertySource(Map.of(
                "gateway.auth.whitelist", List.of("/api/v1/acc/captcha"),
                "gateway.auth.jwt-secret", "s3cret",
                "gateway.store", "MEMORY")))
                .bind("gateway", GatewayProperties.class).get();
        assertThat(defaults.auth().accessTokenMaxTtl()).isEqualTo(Duration.ofMinutes(15));
        assertThat(defaults.auth().clockSkew()).isEqualTo(Duration.ofSeconds(60));

        // 显式配置 → 覆盖默认
        GatewayProperties bound = new Binder(new MapConfigurationPropertySource(Map.of(
                "gateway.auth.access-token-max-ttl", "30m",
                "gateway.auth.clock-skew", "5s",
                "gateway.store", "MEMORY")))
                .bind("gateway", GatewayProperties.class).get();
        assertThat(bound.auth().accessTokenMaxTtl()).isEqualTo(Duration.ofMinutes(30));
        assertThat(bound.auth().clockSkew()).isEqualTo(Duration.ofSeconds(5));
    }

    @Test
    void bindsRateLimitTierDefaults() {
        MapConfigurationPropertySource source = new MapConfigurationPropertySource(Map.of(
                "gateway.rate-limit.read.capacity", "1000",
                "gateway.rate-limit.write.capacity", "100",
                "gateway.rate-limit.ai.capacity", "10",
                "gateway.rate-limit.ai.window-seconds", "60",
                "gateway.rate-limit.funds.capacity", "100",
                "gateway.rate-limit.ip.capacity", "200"
        ));

        GatewayProperties bound = new Binder(source).bind("gateway", GatewayProperties.class).get();

        assertThat(bound.rateLimit().read().capacity()).isEqualTo(1000);
        assertThat(bound.rateLimit().write().capacity()).isEqualTo(100);
        assertThat(bound.rateLimit().ai().capacity()).isEqualTo(10);
        assertThat(bound.rateLimit().ai().windowSeconds()).isEqualTo(60);
        assertThat(bound.rateLimit().funds().capacity()).isEqualTo(100);
        assertThat(bound.rateLimit().ip().capacity()).isEqualTo(200);
    }

    @Test
    void bindsInternalPaths() {
        MapConfigurationPropertySource source = new MapConfigurationPropertySource(Map.of(
                "gateway.internal-paths", List.of("/api/v1/acc/internal/", "/api/v1/acc/realname/callback"),
                "gateway.store", "MEMORY"
        ));

        GatewayProperties bound = new Binder(source).bind("gateway", GatewayProperties.class).get();

        assertThat(bound.internalPaths())
                .containsExactly("/api/v1/acc/internal/", "/api/v1/acc/realname/callback");
    }

    @Test
    void rejectsBlankJwtSecretWhenRedisStore() {
        GatewayProperties props = new GatewayProperties(
                GatewayProperties.Auth.of(List.of(), ""),
                GatewayProperties.RateLimit.defaults(),
                GatewayProperties.Store.REDIS,
                List.of());

        assertThatThrownBy(() -> GatewayProperties.validate(props))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("jwt-secret");
    }

    @Test
    void acceptsBlankJwtSecretWhenMemoryStore() {
        GatewayProperties props = new GatewayProperties(
                GatewayProperties.Auth.of(List.of(), ""),
                GatewayProperties.RateLimit.defaults(),
                GatewayProperties.Store.MEMORY,
                List.of());

        GatewayProperties.validate(props);
    }
}
