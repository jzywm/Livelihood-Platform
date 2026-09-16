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
 * 会话存储装配（任务 2.3 + L1 修复裁定 R-A8 + C1 加严裁定 R-A11）：由**显式开关**
 * {@code acc.session.store=memory|redis} 决定实现——{@code redis} → {@link RedisSessionStore}
 * （生产，必须配 {@code acc.redis.host}，缺失即**启动 fail-fast**）；{@code memory}（默认）→
 * {@link InMemorySessionStore}，**且此时 {@code acc.redis.host} 必须为空**（配了 host 即启动 fail-fast）。
 *
 * <p>L1 背景：原实现「{@code acc.redis.host} 为空即静默退化为内存」——生产误配不报错，登出/踢人
 * 静默失效，与 spec `acc-session` 的 fail-closed 要求相悖。开关化的关键在于让「未配置」与
 * 「显式选内存」**可区分**：想用内存必须写明，写了 redis 就必须给 host。</p>
 *
 * <p>C1/R-A11 加严：仅有 R-A8 单向校验仍留一个静默降级口——**配了 {@code acc.redis.host} 却漏设
 * {@code acc.session.store=redis}**（默认 memory）会照常启动，会话族与吊销名单只落进程内 ⇒
 * 登出/踢人静默失效。故校验改为两方向对称：{@code redis} 无 host 失败、{@code memory} 有 host 也失败，
 * 「memory + 空 host」是进程内实现的**唯一合法组合**（本地/测试）。</p>
 *
 * <p>fail-closed 断言用「故障端口」直接驱动装配出来的 {@link RedisSessionStore}：存储抛错必须
 * 上抛 {@link SessionStoreUnavailableException}，**不产生任何写入**（不签发无法吊销的 token）。</p>
 */
class SessionStoreAssemblyTest {

    private final AccConfiguration configuration = new AccConfiguration();

    @Test
    @DisplayName("2.3 默认（acc.session.store=memory）→ 进程内兜底实现（保证单测/演练无需 Redis）")
    void unconfiguredRedisFallsBackToInMemory() {
        AccProperties properties = new AccProperties();
        SessionStore store = configuration.sessionStore(properties, new InMemoryStringRedisOps(),
                Clock.systemUTC());

        assertThat(store).isInstanceOf(InMemorySessionStore.class);
    }

    @Test
    @DisplayName("2.3 acc.session.store=redis → Redis 实现（生产语义：与网关共享吊销名单）")
    void configuredRedisUsesRedisStore() {
        AccProperties properties = new AccProperties();
        properties.getSession().setStore("redis");
        properties.getRedis().setHost("127.0.0.1");

        SessionStore store = configuration.sessionStore(properties, new InMemoryStringRedisOps(),
                Clock.systemUTC());

        assertThat(store).isInstanceOf(RedisSessionStore.class);
    }

    @Test
    @DisplayName("L1/R-A8 acc.session.store=redis 但 acc.redis.host 为空 → 启动 fail-fast（不再静默退化）")
    void storeRedisWithBlankHostFailsFast() {
        AccProperties properties = new AccProperties();
        properties.getSession().setStore("redis");
        properties.getRedis().setHost("   ");

        assertThatThrownBy(() -> configuration.sessionStore(properties, new InMemoryStringRedisOps(),
                Clock.systemUTC()))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("acc.session.store=redis")
                .hasMessageContaining("acc.redis.host");
    }

    @Test
    @DisplayName("L1/R-A8 acc.session.store 取值非法 → 启动 fail-fast（避免拼错即静默退化）")
    void unknownStoreValueFailsFast() {
        AccProperties properties = new AccProperties();
        properties.getSession().setStore("redis-cluster");

        assertThatThrownBy(() -> configuration.sessionStore(properties, new InMemoryStringRedisOps(),
                Clock.systemUTC()))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("acc.session.store");
    }

    @Test
    @DisplayName("C1/R-A11 默认 acc.session.store（memory）但 acc.redis.host 已配置 → 启动 fail-fast"
            + "（「配了 Redis host 却漏设开关」不再静默退化为内存）")
    void defaultStoreWithConfiguredHostFailsFast() {
        AccProperties properties = new AccProperties();
        properties.getRedis().setHost("127.0.0.1");

        assertThatThrownBy(() -> configuration.sessionStore(properties, new InMemoryStringRedisOps(),
                Clock.systemUTC()))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("acc.redis.host")
                .hasMessageContaining("acc.session.store=memory");
    }

    @Test
    @DisplayName("C1/R-A11 显式 acc.session.store=memory 但 acc.redis.host 已配置 → 启动 fail-fast"
            + "（与 R-A8「取 redis 而缺 host」方向对称）")
    void storeMemoryWithConfiguredHostFailsFast() {
        AccProperties properties = new AccProperties();
        properties.getSession().setStore("memory");
        properties.getRedis().setHost("127.0.0.1");

        assertThatThrownBy(() -> configuration.sessionStore(properties, new InMemoryStringRedisOps(),
                Clock.systemUTC()))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("acc.redis.host")
                .hasMessageContaining("acc.session.store=memory")
                .hasMessageContaining("请显式设置 acc.session.store=redis")
                .hasMessageContaining("或清空 acc.redis.host");
    }

    @Test
    @DisplayName("L1/R-A8 + C1/R-A11 显式 memory 且未配 host（合法本地组合）："
            + "即使端口「一用就炸」也绝不触碰 Redis")
    void storeMemoryNeverTouchesRedis() {
        AccProperties properties = new AccProperties();
        properties.getSession().setStore("memory");
        properties.getRedis().setHost("   ");

        SessionStore store = configuration.sessionStore(properties, new BrokenStringRedisOps(), Clock.systemUTC());

        assertThat(store).isInstanceOf(InMemorySessionStore.class);
        // 端口每次调用都抛错：以下调用若发生任何 Redis 委托都会失败
        store.ping();
        assertThat(store.consume("rf-never-touched")).isFalse();
        assertThat(store.find("fam-never-touched")).isNull();
    }

    @Test
    @DisplayName("2.3 fail-closed：存储故障时 issue/find/consume/revoke 全部上抛，且无任何写入副作用")
    void brokenStoreFailsClosedWithoutSideEffects() {
        AccProperties properties = new AccProperties();
        properties.getSession().setStore("redis");
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
