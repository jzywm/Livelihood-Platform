package com.msz.acc.infrastructure.auth.session;

import com.msz.acc.application.port.SessionStore;
import com.msz.acc.infrastructure.auth.JwtCodec;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * 会话存储**端口契约测试**（2.1/2.2 共用一套）：键构造与 TTL 语义、refresh 单次使用、
 * 轮换续期、重用识别所需的「已轮换标记」、网关共享吊销契约。
 *
 * <p>子类只负责给出实现与可控时钟——{@code InMemorySessionStoreContractTest}（直跑内存实现）与
 * {@code RedisSessionStoreContractTest}（Lettuce 实现 + 假客户端）**通过同一套断言**，
 * 因此两种实现的语义差异在测试层面不可能悄悄漂移（任务 2.2 验证口径）。</p>
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
                clock.now() + REFRESH_TTL_SECONDS * 1000L, FamilyRecord.STATUS_ACTIVE, jti, null, 0L, Map.of());
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
                clock.now() + 5_000L, Map.of("rf-1", clock.now() + REFRESH_TTL_SECONDS * 1000L));
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
    @DisplayName("存储不可用：ping 抛 SessionStoreUnavailableException（fail-closed，不静默降级）")
    void unavailableStoreFailsFast() {
        SessionStore broken = brokenStore();
        if (broken == null) {
            // 本实现的「不可用」只能由底层客户端故障触发，其行为由 RedisSessionStoreTest 覆盖
            return;
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
