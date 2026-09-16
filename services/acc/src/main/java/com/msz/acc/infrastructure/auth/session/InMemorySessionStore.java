package com.msz.acc.infrastructure.auth.session;

import com.msz.acc.application.port.SessionStore;

import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.function.LongSupplier;

/**
 * {@link SessionStore} 内存实现：**单元测试与真机演练兜底，不得用于有真实用户的部署**
 * （进程内存储无法与网关共享吊销名单，登出/踢人将失效——design D3 已显式接受该代价并写入文档）。
 *
 * <p>语义与 Redis 实现逐条对齐（同一套端口契约测试）；TTL 用注入的毫秒时钟判定，
 * 因此宽限窗口/到期行为在测试中完全可控、无 {@code Thread.sleep}。</p>
 *
 * <p><b>族记录的互斥（B11）</b>：族记录是整条 JSON 覆写，「读-改-写」必须互斥——并发绑定短 token jti
 * 或与轮换交错时若各写各的，会丢掉别的线程刚写进去的 jti（该短 token 因此逃过整族吊销）。
 * 故凡改动族记录的方法（{@code rotate}/{@code markRevoked}/{@code bindAccessJti}）都在
 * {@link #familyLock} 上串行；每次写入的 TTL 取**更新后**记录的族到期时刻（A1）。</p>
 */
public final class InMemorySessionStore implements SessionStore {

    private final Map<String, Entry> store = new ConcurrentHashMap<>();

    /** 族记录「读-改-写」互斥锁（B11，见类注释）。 */
    private final Object familyLock = new Object();

    private final LongSupplier clockMillis;

    public InMemorySessionStore(LongSupplier clockMillis) {
        this.clockMillis = clockMillis;
    }

    @Override
    public void issue(FamilyRecord family, String refreshJti, long refreshTtlSeconds) {
        long now = clockMillis.getAsLong();
        store.put(familyKey(family.familyId()), new Entry(FamilyRecordJson.encode(family), family.expiresAtMillis()));
        // refresh 映射 TTL 与族一致（不得超过其有效期）；值 = familyId
        store.put(refreshKey(refreshJti), new Entry(family.familyId(),
                now + refreshTtlSeconds * 1000L));
    }

    @Override
    public FamilyRecord find(String familyId) {
        Entry entry = live(familyKey(familyId));
        return entry == null ? null : FamilyRecordJson.decode(entry.value());
    }

    @Override
    public void rotate(FamilyRecord family, String newRefreshJti, long refreshTtlSeconds, String consumedJti) {
        long now = clockMillis.getAsLong();
        synchronized (familyLock) {
            // B11：调用方可能拿着「消费旧 refresh 时的族快照」写回——先合并快照之后被并发绑定的 jti
            FamilyRecord current = find(family.familyId());
            FamilyRecord toWrite = current == null ? family : family.mergedWithAccessJtisOf(current, now);
            store.remove(refreshKey(consumedJti));
            store.put(refreshKey(newRefreshJti), new Entry(family.familyId(), now + refreshTtlSeconds * 1000L));
            store.put(familyKey(family.familyId()),
                    new Entry(FamilyRecordJson.encode(toWrite), toWrite.expiresAtMillis()));
        }
    }

    @Override
    public boolean consume(String refreshJti) {
        // ConcurrentHashMap.remove(key) 的返回值唯一判定「是否由本次调用删除」→ 单次使用
        Entry removed = store.remove(refreshKey(refreshJti));
        return removed != null && removed.expiresAtMillis() > clockMillis.getAsLong();
    }

    @Override
    public void markRevoked(String familyId) {
        synchronized (familyLock) {
            FamilyRecord family = find(familyId);
            if (family == null) {
                return;
            }
            FamilyRecord revoked = new FamilyRecord(family.familyId(), family.accountId(), family.role(),
                    family.mfa(), family.createdAtMillis(), family.expiresAtMillis(), FamilyRecord.STATUS_REVOKED,
                    family.currentJti(), family.previousJti(), family.previousValidUntilMillis(),
                    family.rotatedJtis(), family.accessJtis());
            // A1：TTL 取更新后记录的族到期时刻
            store.put(familyKey(familyId), new Entry(FamilyRecordJson.encode(revoked), revoked.expiresAtMillis()));
        }
    }

    @Override
    public void bindAccessJti(String familyId, String accessJti, long expiresAtMillis) {
        synchronized (familyLock) {
            FamilyRecord family = find(familyId);
            if (family == null) {
                return;
            }
            FamilyRecord updated = family.pruned(clockMillis.getAsLong()).withAccessJti(accessJti, expiresAtMillis);
            // A1：族键 TTL 只由**族**到期时刻决定（原实现沿用更新前记录的值，是同一污染的传播点）
            store.put(familyKey(familyId), new Entry(FamilyRecordJson.encode(updated), updated.expiresAtMillis()));
        }
    }

    @Override
    public void revoke(List<AccessJti> accessJtis) {
        long now = clockMillis.getAsLong();
        for (AccessJti jti : accessJtis) {
            long ttlMillis = Math.max(jti.remainingSeconds(), 1L) * 1000L;
            store.put(revokedKey(jti.jti()), new Entry(REVOKED_VALUE, now + ttlMillis));
        }
    }

    @Override
    public void ping() {
        // 进程内存储恒可用（该实现的「不可用」不是可注入状态；fail-closed 由 Redis 实现承担）
    }

    /** 原始键值读取（测试断言 TTL/键构造用）。 */
    public String rawValue(String key) {
        Entry entry = live(key);
        return entry == null ? null : entry.value();
    }

    /** 原始键剩余 TTL（秒，向上取整，与 Redis TTL 语义对齐）。 */
    public long rawTtlSeconds(String key) {
        Entry entry = live(key);
        if (entry == null) {
            return -2L;
        }
        long remainingMillis = entry.expiresAtMillis() - clockMillis.getAsLong();
        return remainingMillis <= 0 ? -2L : Math.max(1L, (remainingMillis + 999L) / 1000L);
    }

    private Entry live(String key) {
        Entry entry = store.get(key);
        if (entry == null) {
            return null;
        }
        if (entry.expiresAtMillis() <= clockMillis.getAsLong()) {
            store.remove(key);
            return null;
        }
        return entry;
    }

    private static String familyKey(String familyId) {
        return FAMILY_KEY_PREFIX + familyId;
    }

    private static String refreshKey(String jti) {
        return REFRESH_KEY_PREFIX + jti;
    }

    private static String revokedKey(String jti) {
        return REVOKED_KEY_PREFIX + jti;
    }

    private record Entry(String value, long expiresAtMillis) {
    }
}
