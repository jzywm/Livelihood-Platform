package com.msz.acc.infrastructure.auth.session;

import com.msz.acc.application.port.SessionStore;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * {@link RedisSessionStore}（生产实现，{@code StringRedisOps} + Lua）：
 *
 * <ul>
 *   <li><b>端口契约同套直跑</b>：继承 {@link AbstractSessionStoreContractTest}，键构造/TTL/单次使用/
 *       轮换/整族吊销/存储不可用的断言与内存实现**逐条相同**（任务 2.2「两实现通过同一套端口契约测试」）。</li>
 *   <li><b>键构造与 TTL 换算取证</b>：断言真正发给 Redis 的键名与 TTL 秒数（从端口签名看不到）。</li>
 *   <li><b>fail-closed</b>：底层 Redis 抛错 → 统一 {@link SessionStoreUnavailableException}，
 *       不签发、不静默降级（任务 2.3）。</li>
 * </ul>
 */
class RedisSessionStoreContractTest extends AbstractSessionStoreContractTest {

    private FakeRedis redis;

    @Override
    protected SessionStore newStore(MutableClock clock) {
        redis = new FakeRedis(clock);
        return new RedisSessionStore(redis.ops(), clock);
    }

    @Override
    protected SessionStore brokenStore() {
        return new RedisSessionStore(new BrokenOps(), clock);
    }

    @Override
    protected String rawValue(String key) {
        return redis.rawValue(key);
    }

    @Override
    protected long rawTtl(String key) {
        return redis.rawTtl(key);
    }

    @Test
    @DisplayName("ISSUE 脚本：写 acc:session:{fam}（族 JSON）+ acc:refresh:{jti}（值 = familyId），TTL 由绝对毫秒反算为秒")
    void issueScriptWritesContractKeysAndTtlSeconds() {
        SessionStore store = new RedisSessionStore(redis.ops(), clock);
        redis.clearCalls();

        FamilyRecord family = new FamilyRecord("fam_a", 1001L, "CONSUMER", false, T0,
                T0 + 604_800_000L, FamilyRecord.STATUS_ACTIVE, "rf-1", null, 0L, Map.of());
        store.issue(family, "rf-1", 604_800L);

        FakeRedis.Call call = redis.lastOf("ISSUE");
        assertThat(call.key(0)).isEqualTo("acc:session:fam_a");
        assertThat(call.key(1)).isEqualTo("acc:refresh:rf-1");
        assertThat(call.arg(3)).isEqualTo("fam_a");
        assertThat(call.arg(1)).isEqualTo("604800");
        assertThat(call.arg(2)).isEqualTo("604800");
    }

    @Test
    @DisplayName("TTL 换算：已过期的族给 1 秒（Redis 拒收 0/负 TTL，会让键永不过期）")
    void expiredFamilyTtlIsClampedToOneSecond() {
        SessionStore store = new RedisSessionStore(redis.ops(), clock);
        redis.clearCalls();

        FamilyRecord expired = new FamilyRecord("fam_old", 1001L, "CONSUMER", false, T0 - 1_000_000L,
                T0 - 500_000L, FamilyRecord.STATUS_ACTIVE, "rf-old", null, 0L, Map.of());
        store.issue(expired, "rf-old", 604_800L);

        assertThat(redis.lastOf("ISSUE").arg(1)).isEqualTo("1");
    }

    @Test
    @DisplayName("TTL 换算：不足 1 秒的剩余量向上取整为 1 秒（不因截断把键提前判死）")
    void subSecondRemainingRoundsUpToOneSecond() {
        SessionStore store = new RedisSessionStore(redis.ops(), clock);
        redis.clearCalls();

        FamilyRecord almost = new FamilyRecord("fam_near", 1001L, "CONSUMER", false, T0,
                T0 + 400L, FamilyRecord.STATUS_ACTIVE, "rf-near", null, 0L, Map.of());
        store.issue(almost, "rf-near", 604_800L);

        assertThat(redis.lastOf("ISSUE").arg(1)).isEqualTo("1");
    }

    @Test
    @DisplayName("ROTATE 脚本：一次调用内 SET 族键 + DEL 旧映射 + SET 新映射（原子，无孤儿凭据窗口）")
    void rotateScriptIsAtomic() {
        SessionStore store = new RedisSessionStore(redis.ops(), clock);
        FamilyRecord family = new FamilyRecord("fam_a", 1001L, "CONSUMER", false, T0,
                T0 + 604_800_000L, FamilyRecord.STATUS_ACTIVE, "rf-1", null, 0L, Map.of());
        store.issue(family, "rf-1", 604_800L);
        redis.clearCalls();

        FamilyRecord rotated = new FamilyRecord("fam_a", 1001L, "CONSUMER", false, T0,
                T0 + 604_800_000L, FamilyRecord.STATUS_ACTIVE, "rf-2", "rf-1", T0 + 5_000L,
                Map.of("rf-1", T0 + 604_800_000L));
        store.rotate(rotated, "rf-2", 604_800L, "rf-1");

        assertThat(redis.calls()).hasSize(1);
        assertThat(redis.lastOf("ROTATE").keys())
                .containsExactly("acc:session:fam_a", "acc:refresh:rf-2", "acc:refresh:rf-1");
        assertThat(redis.rawValue("acc:refresh:rf-1")).isNull();
        assertThat(redis.rawValue("acc:refresh:rf-2")).isEqualTo("fam_a");
    }

    @Test
    @DisplayName("CONSUME 脚本：存在则删并返回 1，第二次返回 0（单次使用的原子边界）")
    void consumeScriptIsAtomicSingleUse() {
        SessionStore store = new RedisSessionStore(redis.ops(), clock);
        store.issue(new FamilyRecord("fam_a", 1001L, "CONSUMER", false, T0, T0 + 604_800_000L,
                FamilyRecord.STATUS_ACTIVE, "rf-1", null, 0L, Map.of()), "rf-1", 604_800L);
        redis.clearCalls();

        assertThat(store.consume("rf-1")).isTrue();
        assertThat(redis.lastOf("CONSUME_HIT").key(0)).isEqualTo("acc:refresh:rf-1");
        assertThat(store.consume("rf-1")).isFalse();
        assertThat(redis.lastOf("CONSUME_MISS")).isNotNull();
    }

    @Test
    @DisplayName("REVOKE 脚本：逐条 SET revoked:jti:{jti} 占位值 1 + TTL = 剩余有效期（网关共享契约）")
    void revokeScriptUsesGatewayContract() {
        SessionStore store = new RedisSessionStore(redis.ops(), clock);
        redis.clearCalls();

        store.revoke(List.of(new AccessJti("jti-a", 900L)));

        FakeRedis.Call call = redis.lastOf("REVOKE");
        assertThat(call.key(0)).isEqualTo("revoked:jti:jti-a");
        assertThat(call.arg(0)).isEqualTo("1");
        assertThat(call.arg(1)).isEqualTo("900");
        assertThat(redis.rawTtl("revoked:jti:jti-a")).isEqualTo(900L);
    }

    @Test
    @DisplayName("族记录读回：GET acc:session:{fam} 的值可被解码为族记录（键值格式与内存实现一致）")
    void familyRecordRoundTripsThroughRedisValue() {
        SessionStore store = new RedisSessionStore(redis.ops(), clock);
        FamilyRecord family = new FamilyRecord("fam_a", 1001L, "MERCHANT", true, T0,
                T0 + 604_800_000L, FamilyRecord.STATUS_ACTIVE, "rf-1", null, 0L, Map.of("rf-0", T0 + 1000L));
        store.issue(family, "rf-1", 604_800L);

        FamilyRecord back = store.find("fam_a");

        assertThat(back).isEqualTo(family);
    }

    @Test
    @DisplayName("2.3 fail-closed：Redis 读/写/脚本抛错 → SessionStoreUnavailableException（不静默放行）")
    void redisFailureFailsFast() {
        SessionStore store = new RedisSessionStore(new BrokenOps(), clock);
        FamilyRecord family = new FamilyRecord("fam_a", 1001L, "CONSUMER", false, T0,
                T0 + 604_800_000L, FamilyRecord.STATUS_ACTIVE, "rf-1", null, 0L, Map.of());

        assertThatThrownBy(store::ping).isInstanceOf(SessionStoreUnavailableException.class);
        assertThatThrownBy(() -> store.find("fam_a")).isInstanceOf(SessionStoreUnavailableException.class);
        assertThatThrownBy(() -> store.issue(family, "rf-1", 604_800L))
                .isInstanceOf(SessionStoreUnavailableException.class);
        assertThatThrownBy(() -> store.consume("rf-1")).isInstanceOf(SessionStoreUnavailableException.class);
        assertThatThrownBy(() -> store.revoke(List.of(new AccessJti("jti-a", 900L))))
                .isInstanceOf(SessionStoreUnavailableException.class);
        assertThatThrownBy(() -> store.markRevoked("fam_a"))
                .isInstanceOf(SessionStoreUnavailableException.class);
    }

    /** 一律抛错的端口实现，模拟 Redis 连接失败/超时（fail-closed 触发源）。 */
    private static final class BrokenOps implements com.msz.common.redis.StringRedisOps {

        @Override
        public Long incr(String key) {
            throw new IllegalStateException("Redis 连接失败");
        }

        @Override
        public Boolean expire(String key, long seconds) {
            throw new IllegalStateException("Redis 连接失败");
        }

        @Override
        public String get(String key) {
            throw new IllegalStateException("Redis 连接失败");
        }

        @Override
        public Boolean setNx(String key, String value, long ttlSeconds) {
            throw new IllegalStateException("Redis 连接失败");
        }

        @Override
        public Object eval(String script, List<String> keys, List<String> args) {
            throw new IllegalStateException("Redis 连接失败");
        }
    }
}
