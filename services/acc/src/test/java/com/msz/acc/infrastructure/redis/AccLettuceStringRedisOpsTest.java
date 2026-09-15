package com.msz.acc.infrastructure.redis;

import io.lettuce.core.RedisURI;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.time.Duration;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * {@link AccLettuceStringRedisOps} 的连接参数构造（R-A6）：主机/端口/可选 AUTH 与**有界超时**
 * （命令 2s / 连接 1s，与网关 `spring.data.redis.timeout/connect-timeout` 同口径）。
 *
 * <p>不在单测里连真实 Redis（单元测试环境无 Redis）：连接 URI 的构造是纯函数，直接断言；
 * 真实连通性由真机演练（`services/acc/deploy/drill`）覆盖。</p>
 */
class AccLettuceStringRedisOpsTest {

    @Test
    @DisplayName("URI 构造：host/port 生效，未配置用户名密码时不带 AUTH")
    void uriWithoutAuth() {
        RedisURI uri = AccLettuceStringRedisOps.redisUri("127.0.0.1", 6379, null, null);

        assertThat(uri.getHost()).isEqualTo("127.0.0.1");
        assertThat(uri.getPort()).isEqualTo(6379);
        assertThat(uri.getUsername()).isNull();
        assertThat(uri.getPassword()).isNull();
    }

    @Test
    @DisplayName("URI 构造：配置了密码则带 AUTH（用户名可空，兼容 Redis 6 以前的 requirepass）")
    void uriWithPasswordOnly() {
        RedisURI uri = AccLettuceStringRedisOps.redisUri("redis.internal", 6380, null, "s3cret");

        assertThat(uri.getPassword()).isNotNull();
        assertThat(new String(uri.getPassword())).isEqualTo("s3cret");
        assertThat(uri.getUsername()).isNull();
    }

    @Test
    @DisplayName("URI 构造：用户名 + 密码（Redis 6 ACL）都配置时同时带上")
    void uriWithUsernameAndPassword() {
        RedisURI uri = AccLettuceStringRedisOps.redisUri("redis.internal", 6379, "acc", "s3cret");

        assertThat(uri.getUsername()).isEqualTo("acc");
        assertThat(new String(uri.getPassword())).isEqualTo("s3cret");
    }

    @Test
    @DisplayName("URI 构造：空白用户名/密码视为未配置（不产生空 AUTH，否则 Redis 拒绝连接）")
    void blankCredentialsIgnored() {
        RedisURI uri = AccLettuceStringRedisOps.redisUri("127.0.0.1", 6379, "  ", "");

        assertThat(uri.getUsername()).isNull();
        assertThat(uri.getPassword()).isNull();
    }

    @Test
    @DisplayName("有界超时：命令 2s / 连接 1s（依赖故障快速失败，不拖垮会话端点）")
    void timeoutsAreBounded() {
        assertThat(AccLettuceStringRedisOps.COMMAND_TIMEOUT_SECONDS).isEqualTo(2L);
        assertThat(AccLettuceStringRedisOps.CONNECT_TIMEOUT_SECONDS).isEqualTo(1L);
        assertThat(AccLettuceStringRedisOps.COMMAND_TIMEOUT).isEqualTo(Duration.ofSeconds(2));
        assertThat(AccLettuceStringRedisOps.CONNECT_TIMEOUT).isEqualTo(Duration.ofSeconds(1));

        RedisURI uri = AccLettuceStringRedisOps.redisUri("127.0.0.1", 6379, null, null);

        assertThat(uri.getTimeout()).isEqualTo(Duration.ofSeconds(2));
    }
}
