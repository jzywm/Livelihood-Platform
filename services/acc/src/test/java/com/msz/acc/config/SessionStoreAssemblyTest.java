package com.msz.acc.config;

import com.msz.acc.application.port.SessionStore;
import com.msz.acc.infrastructure.auth.session.InMemorySessionStore;
import com.msz.acc.infrastructure.auth.session.RedisSessionStore;
import com.msz.acc.infrastructure.auth.session.SessionStoreUnavailableException;
import com.msz.acc.infrastructure.redis.AccLettuceStringRedisOps;
import com.msz.acc.infrastructure.redis.InMemoryStringRedisOps;
import com.msz.common.redis.StringRedisOps;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.time.Clock;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * 会话存储装配（任务 2.3）：由 {@code acc.redis.host} 决定实现——配置了 → Redis（生产），
 * 未配置 → 进程内兜底（测试/演练，且**口径为不可用于生产**，文档三处同步）。
 *
 * <p>fail-closed 断言用「故障端口」直接驱动装配出来的 {@link RedisSessionStore}：存储抛错必须
 * 上抛 {@link SessionStoreUnavailableException}，**不产生任何写入**（不签发无法吊销的 token）。</p>
 */
class SessionStoreAssemblyTest {

    private final AccConfiguration configuration = new AccConfiguration();

    @Test
    @DisplayName("2.3 未配置 acc.redis.host → 进程内兜底实现（保证单测/演练无需 Redis）")
    void unconfiguredRedisFallsBackToInMemory() {
        AccProperties properties = new AccProperties();
        SessionStore store = configuration.sessionStore(properties, new InMemoryStringRedisOps(),
                Clock.systemUTC());

        assertThat(store).isInstanceOf(InMemorySessionStore.class);
    }

    @Test
    @DisplayName("2.3 配置 acc.redis.host → Redis 实现（生产语义：与网关共享吊销名单）")
    void configuredRedisUsesRedisStore() {
        AccProperties properties = new AccProperties();
        properties.getRedis().setHost("127.0.0.1");

        SessionStore store = configuration.sessionStore(properties, new InMemoryStringRedisOps(),
                Clock.systemUTC());

        assertThat(store).isInstanceOf(RedisSessionStore.class);
    }

    @Test
    @DisplayName("2.3 host 为空白（含空格）也视为未配置，不退化为「连不上就降级」的模糊状态")
    void blankHostTreatedAsUnconfigured() {
        AccProperties properties = new AccProperties();
        properties.getRedis().setHost("   ");

        assertThat(configuration.sessionStore(properties, new InMemoryStringRedisOps(), Clock.systemUTC()))
                .isInstanceOf(InMemorySessionStore.class);
    }

    @Test
    @DisplayName("2.3 fail-closed：存储故障时 issue/find/consume/revoke 全部上抛，且无任何写入副作用")
    void brokenStoreFailsClosedWithoutSideEffects() {
        AccProperties properties = new AccProperties();
        properties.getRedis().setHost("127.0.0.1");
        SessionStore store = configuration.sessionStore(properties, new BrokenStringRedisOps(), Clock.systemUTC());

        assertThatThrownBy(store::ping).isInstanceOf(SessionStoreUnavailableException.class);
        assertThatThrownBy(() -> store.find("fam_1")).isInstanceOf(SessionStoreUnavailableException.class);
        assertThatThrownBy(() -> store.consume("rf-1")).isInstanceOf(SessionStoreUnavailableException.class);
        assertThatThrownBy(() -> store.markRevoked("fam_1")).isInstanceOf(SessionStoreUnavailableException.class);
    }

    @Test
    @DisplayName("2.3 未配置 Redis 时不构建 Lettuce 客户端（避免无 Redis 环境启动即连不上）")
    void noRedisHostMeansNoLettuceClient() {
        AccProperties properties = new AccProperties();

        // 未配置 host 时 stringRedisOps() 返回内存实现而非 Lettuce；返回类型可安全关闭
        StringRedisOps ops = configuration.stringRedisOps(properties);
        assertThat(ops).isInstanceOf(InMemoryStringRedisOps.class);
        assertThat(ops).isNotInstanceOf(AccLettuceStringRedisOps.class);
    }

    /** 一律抛错的端口实现（模拟 Redis 连接失败/超时）。 */
    private static final class BrokenStringRedisOps implements StringRedisOps {

        @Override
        public Long incr(String key) {
            throw new IllegalStateException("Redis 不可用");
        }

        @Override
        public Boolean expire(String key, long seconds) {
            throw new IllegalStateException("Redis 不可用");
        }

        @Override
        public String get(String key) {
            throw new IllegalStateException("Redis 不可用");
        }

        @Override
        public Boolean setNx(String key, String value, long ttlSeconds) {
            throw new IllegalStateException("Redis 不可用");
        }

        @Override
        public Object eval(String script, List<String> keys, List<String> args) {
            throw new IllegalStateException("Redis 不可用");
        }
    }
}
