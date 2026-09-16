package com.msz.acc.infrastructure.auth.session;

import com.msz.acc.application.port.SessionStore;
import com.msz.acc.infrastructure.auth.JwtCodec;
import org.junit.jupiter.api.Assumptions;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * 会话存储**端口契约测试**（2.1/2.2 共用一套）：键构造与 TTL 语义、refresh 单次使用、
 * 轮换续期、重用识别所需的「已轮换标记」、网关共享吊销契约。
 *
 * <p>子类只负责给出实现与可控时钟——{@code InMemorySessionStoreContractTest}（直跑内存实现）与
 * {@code RedisSessionStoreContractTest}（Lettuce 实现 + 假客户端）**通过同一套断言**，
 * 因此两种实现的语义差异在测试层面不可能悄悄漂移（任务 2.2 验证口径）。</p>
 *
 * <p><b>最终评审修复波（FIX-1）追加的三条契约</b>：① {@code bindAccessJti} 只能追加短 token jti，
 * **不得改变族记录的到期时刻与族键 TTL**（A1：族寿命由 refresh 有效期决定，短 token 的到期时刻
 * 写进族记录会让重用检测窗口从 7 天塌缩到 15 分钟）；② 族记录的读-改-写**并发安全**——并发绑定
 * 不丢 jti（B11：丢掉的 jti 会逃过整族吊销）；③ 轮换写回时不得丢掉「快照之后被并发绑定」的 jti。</p>
 */
abstract class AbstractSessionStoreContractTest {

    /** 契约冻结时间，全部 TTL 断言都相对它计算。 */
    static final long T0 = 1_760_000_000_000L;

    static final long REFRESH_TTL_SECONDS = 604_800L;
    static final long ACCESS_TTL_SECONDS = 900L;

    /** 被测实现。 */
    protected SessionStore store;

    /** 可控时钟（毫秒）。 */
    protected MutableClock clock;

    @BeforeEach
    void setUpContract() {
        clock = new MutableClock(T0);
        store = newStore(clock);
    }

    /** 由子类提供被测实现（同一 {@code clock} 供实现内部判 TTL）。 */
    protected abstract SessionStore newStore(MutableClock clock);

    private FamilyRecord family(String familyId, String jti) {
        return new FamilyRecord(familyId, 1001L, "CONSUMER", false, clock.now(),
                clock.now() + REFRESH_TTL_SECONDS * 1000L, FamilyRecord.STATUS_ACTIVE, jti, null, 0L, Map.of(),
                Map.of());
    }

    @Test
    @DisplayName("2.1 建族：族键与 refresh 键同时可读，且 refresh 值 = familyId")
    void issueWritesBothKeys() {
        store.issue(family("fam_a", "rf-1"), "rf-1", REFRESH_TTL_SECONDS);

        assertThat(store.find("fam_a")).isNotNull();
        assertThat(store.find("fam_a").currentJti()).isEqualTo("rf-1");
        assertThat(rawValue(SessionStore.REFRESH_KEY_PREFIX + "rf-1")).isEqualTo("fam_a");
    }

    @Test
    @DisplayName("2.1 TTL：refresh 映射 TTL 不得超过其有效期；族键 TTL ≤ refresh TTL")
    void issueTtlsAreBoundedByValidity() {
        store.issue(family("fam_a", "rf-1"), "rf-1", REFRESH_TTL_SECONDS);

        long refreshTtl = rawTtl(SessionStore.REFRESH_KEY_PREFIX + "rf-1");
        long familyTtl = rawTtl(SessionStore.FAMILY_KEY_PREFIX + "fam_a");

        assertThat(refreshTtl).isBetween(1L, REFRESH_TTL_SECONDS);
        assertThat(familyTtl).isBetween(1L, REFRESH_TTL_SECONDS);
    }

    @Test
    @DisplayName("2.1 键构造：三个键前缀分别为 acc:session: / acc:refresh: / revoked:jti:")
    void keyPrefixesAreTheSharedContract() {
        assertThat(SessionStore.FAMILY_KEY_PREFIX).isEqualTo("acc:session:");
        assertThat(SessionStore.REFRESH_KEY_PREFIX).isEqualTo("acc:refresh:");
        assertThat(SessionStore.REVOKED_KEY_PREFIX).isEqualTo("revoked:jti:");
        assertThat(SessionStore.REVOKED_VALUE).isEqualTo("1");
    }

    @Test
    @DisplayName("refresh 单次使用：同一 jti 恰有一次消费成功，第二次返回 false")
    void consumeIsSingleUse() {
        store.issue(family("fam_a", "rf-1"), "rf-1", REFRESH_TTL_SECONDS);

        assertThat(store.consume("rf-1")).isTrue();
        assertThat(store.consume("rf-1")).isFalse();
        assertThat(rawValue(SessionStore.REFRESH_KEY_PREFIX + "rf-1")).isNull();
    }

    @Test
    @DisplayName("未知 refresh：消费返回 false（不抛异常、不产生副作用）")
    void consumeUnknownReturnsFalse() {
        assertThat(store.consume("rf-not-exists")).isFalse();
    }

    @Test
    @DisplayName("轮换：新映射可读、旧映射被消费、族记录指向新 jti 且 TTL 续期")
    void rotateMovesMappingAndRenewsFamily() {
        store.issue(family("fam_a", "rf-1"), "rf-1", REFRESH_TTL_SECONDS);

        clock.advanceSeconds(100);
        FamilyRecord rotated = new FamilyRecord("fam_a", 1001L, "CONSUMER", false, T0,
                clock.now() + REFRESH_TTL_SECONDS * 1000L, FamilyRecord.STATUS_ACTIVE, "rf-2", "rf-1",
                clock.now() + 5_000L, Map.of("rf-1", clock.now() + REFRESH_TTL_SECONDS * 1000L), Map.of());
        store.rotate(rotated, "rf-2", REFRESH_TTL_SECONDS, "rf-1");

        FamilyRecord back = store.find("fam_a");
        assertThat(back.currentJti()).isEqualTo("rf-2");
        assertThat(back.previousJti()).isEqualTo("rf-1");
        assertThat(back.rotatedJtis()).containsKey("rf-1");
        assertThat(rawValue(SessionStore.REFRESH_KEY_PREFIX + "rf-2")).isEqualTo("fam_a");
        assertThat(rawValue(SessionStore.REFRESH_KEY_PREFIX + "rf-1")).isNull();
        assertThat(rawTtl(SessionStore.FAMILY_KEY_PREFIX + "fam_a"))
                .isBetween(1L, REFRESH_TTL_SECONDS);
    }

    @Test
    @DisplayName("族到期：TTL 到期后族记录与 refresh 映射均不可读")
    void recordsExpireWithTheirTtl() {
        store.issue(family("fam_a", "rf-1"), "rf-1", REFRESH_TTL_SECONDS);

        clock.advanceSeconds(REFRESH_TTL_SECONDS + 1);

        assertThat(store.find("fam_a")).isNull();
        assertThat(rawValue(SessionStore.REFRESH_KEY_PREFIX + "rf-1")).isNull();
    }

    @Test
    @DisplayName("2.1 吊销契约：逐条 revoked:jti:{jti} 占位值 + TTL = 剩余有效期")
    void revokeWritesGatewayContractKeys() {
        store.revoke(List.of(new AccessJti("jti-a", ACCESS_TTL_SECONDS),
                new AccessJti("jti-b", 120L)));

        assertThat(rawValue(SessionStore.REVOKED_KEY_PREFIX + "jti-a")).isEqualTo(SessionStore.REVOKED_VALUE);
        assertThat(rawValue(SessionStore.REVOKED_KEY_PREFIX + "jti-b")).isEqualTo(SessionStore.REVOKED_VALUE);
        assertThat(rawTtl(SessionStore.REVOKED_KEY_PREFIX + "jti-a")).isEqualTo(ACCESS_TTL_SECONDS);
        assertThat(rawTtl(SessionStore.REVOKED_KEY_PREFIX + "jti-b")).isEqualTo(120L);
    }

    @Test
    @DisplayName("吊销名单 TTL 必须覆盖剩余有效期：正常返回后不得为 0/负（否则网关读不到）")
    void revokeTtlIsAtLeastOneSecond() {
        store.revoke(List.of(new AccessJti("jti-zero", 0L), new AccessJti("jti-neg", -5L)));

        assertThat(rawTtl(SessionStore.REVOKED_KEY_PREFIX + "jti-zero")).isGreaterThanOrEqualTo(1L);
        assertThat(rawTtl(SessionStore.REVOKED_KEY_PREFIX + "jti-neg")).isGreaterThanOrEqualTo(1L);
    }

    @Test
    @DisplayName("整族吊销：族记录标记 REVOKED 且**保留**（供重放识别），refresh 映射可继续消费判定")
    void markRevokedKeepsRecord() {
        store.issue(family("fam_a", "rf-1"), "rf-1", REFRESH_TTL_SECONDS);

        store.markRevoked("fam_a");

        FamilyRecord back = store.find("fam_a");
        assertThat(back).isNotNull();
        assertThat(back.revoked()).isTrue();
        assertThat(back.status()).isEqualTo(FamilyRecord.STATUS_REVOKED);
    }

    @Test
    @DisplayName("FIX-1/A1 回归：bindAccessJti 不得缩短族寿命（族到期与外层族键 TTL 仍 ≈ refresh 有效期，不是 15 分钟）")
    void bindAccessJtiKeepsFamilyLifetime() {
        store.issue(family("fam_a", "rf-1"), "rf-1", REFRESH_TTL_SECONDS);
        long ttlBefore = rawTtl(SessionStore.FAMILY_KEY_PREFIX + "fam_a");

        clock.advanceSeconds(60);
        store.bindAccessJti("fam_a", "at-1", clock.now() + ACCESS_TTL_SECONDS * 1000L);

        FamilyRecord back = store.find("fam_a");
        assertThat(back.expiresAtMillis())
                .as("族到期时刻只能由 refresh 有效期决定；短 token 的到期时刻不得写进族记录")
                .isEqualTo(T0 + REFRESH_TTL_SECONDS * 1000L);
        assertThat(back.accessJtis())
                .as("短 token 的到期时刻只进 accessJtis 这一条目")
                .containsEntry("at-1", clock.now() + ACCESS_TTL_SECONDS * 1000L);

        long ttlAfter = rawTtl(SessionStore.FAMILY_KEY_PREFIX + "fam_a");
        assertThat(ttlAfter)
                .as("族键 TTL 只随时间流逝（60s），不得塌缩到短 token 量级")
                .isEqualTo(ttlBefore - 60L);
        assertThat(ttlAfter)
                .as("族键必须活过短 token 有效期，否则轮换后 15 分钟族记录消失、重放无法识别")
                .isGreaterThan(ACCESS_TTL_SECONDS);
    }

    @Test
    @DisplayName("FIX-1/B11 并发：8 线程 × 8 轮并发 bindAccessJti 后族内 jti 集合无丢失（读-改-写必须原子）")
    void concurrentBindAccessJtiKeepsEveryJti() throws Exception {
        store.issue(family("fam_a", "rf-1"), "rf-1", REFRESH_TTL_SECONDS);
        int threads = 8;
        int rounds = 8;
        Set<String> expected = new LinkedHashSet<>();
        ExecutorService pool = Executors.newFixedThreadPool(threads);
        try {
            for (int round = 0; round < rounds; round++) {
                CountDownLatch start = new CountDownLatch(1);
                List<Future<?>> futures = new ArrayList<>();
                for (int slot = 0; slot < threads; slot++) {
                    String jti = "at-r" + round + "-t" + slot;
                    expected.add(jti);
                    futures.add(pool.submit(() -> {
                        start.await();
                        store.bindAccessJti("fam_a", jti, clock.now() + ACCESS_TTL_SECONDS * 1000L);
                        return null;
                    }));
                }
                start.countDown();
                for (Future<?> future : futures) {
                    future.get(10, TimeUnit.SECONDS);
                }
            }
        } finally {
            pool.shutdownNow();
        }

        assertThat(store.find("fam_a").accessJtis().keySet())
                .as("丢掉的 jti 会逃过整族吊销（该短 token 在剩余有效期内仍可用）")
                .containsExactlyInAnyOrderElementsOf(expected);
    }

    @Test
    @DisplayName("FIX-1/B11 并发：轮换按「旧快照」写回时不得丢掉快照之后被并发绑定的 jti")
    void rotateKeepsJtisBoundAfterItsSnapshot() {
        store.issue(family("fam_a", "rf-1"), "rf-1", REFRESH_TTL_SECONDS);
        store.bindAccessJti("fam_a", "at-before", clock.now() + ACCESS_TTL_SECONDS * 1000L);
        // 轮换调用方在消费旧 refresh 时读到的族快照（此刻还没有 at-after）
        FamilyRecord snapshot = store.find("fam_a");
        FamilyRecord rotated = new FamilyRecord("fam_a", 1001L, "CONSUMER", false, snapshot.createdAtMillis(),
                clock.now() + REFRESH_TTL_SECONDS * 1000L, FamilyRecord.STATUS_ACTIVE, "rf-2", "rf-1",
                clock.now() + 5_000L, Map.of("rf-1", snapshot.expiresAtMillis()), snapshot.accessJtis());

        // 竞态：另一请求在本线程写回之前绑定了新的短 token jti
        store.bindAccessJti("fam_a", "at-after", clock.now() + ACCESS_TTL_SECONDS * 1000L);

        store.rotate(rotated, "rf-2", REFRESH_TTL_SECONDS, "rf-1");

        FamilyRecord back = store.find("fam_a");
        assertThat(back.currentJti()).isEqualTo("rf-2");
        assertThat(back.accessJtis())
                .as("轮换写回必须合并最新族记录（否则并发绑定的短 token 逃过整族吊销）")
                .containsKeys("at-before", "at-after");
    }

    @Test
    @DisplayName("存储不可用：ping 抛 SessionStoreUnavailableException（fail-closed，不静默降级）")
    void unavailableStoreFailsFast() {
        SessionStore broken = brokenStore();
        if (broken == null) {
            // FIX-1/M2：本实现的「不可用」不是可注入状态（内存实现无底层客户端故障面）。
            // 显式 abort（记为 skipped）而非静默 return——后者是一条「什么也不断言却计为通过」的假绿用例。
            Assumptions.abort("本实现（" + store.getClass().getSimpleName()
                    + "）的不可用状态不可注入：fail-closed 由 RedisSessionStoreContractTest#redisFailureFailsFast 覆盖");
        }
        assertThatThrownBy(broken::ping)
                .isInstanceOf(SessionStoreUnavailableException.class);
        assertThatThrownBy(() -> broken.issue(family("fam_x", "rf-x"), "rf-x", REFRESH_TTL_SECONDS))
                .isInstanceOf(SessionStoreUnavailableException.class);
        assertThatThrownBy(() -> broken.find("fam_x"))
                .isInstanceOf(SessionStoreUnavailableException.class);
        assertThatThrownBy(() -> broken.consume("rf-x"))
                .isInstanceOf(SessionStoreUnavailableException.class);
        assertThatThrownBy(() -> broken.revoke(List.of(new AccessJti("jti-x", 10L))))
                .isInstanceOf(SessionStoreUnavailableException.class);
    }

    /** 子类若可构造「故障实现」则返回，否则返回 null（跳过该断言）。 */
    protected SessionStore brokenStore() {
        return null;
    }

    // ---------- 子类需提供原始键读取（TTL 断言无法从端口签名观察） ----------

    /** 原始键值读取（绕过族/refresh 语义）。 */
    protected abstract String rawValue(String key);

    /** 原始键剩余 TTL（秒）。 */
    protected abstract long rawTtl(String key);

    /** 可控毫秒时钟（实现内部以它计算剩余 TTL）。 */
    protected static final class MutableClock implements java.util.function.LongSupplier {

        private long millis;

        MutableClock(long millis) {
            this.millis = millis;
        }

        @Override
        public long getAsLong() {
            return millis;
        }

        long now() {
            return millis;
        }

        void advanceSeconds(long seconds) {
            millis += seconds * 1000L;
        }
    }

    /** 供子类复用的 refresh 判定夹具（同一密钥/同一编解码器）。 */
    protected static final class Stores {

        private Stores() {
        }

        static JwtCodec codec() {
            return new JwtCodec();
        }
    }
}
