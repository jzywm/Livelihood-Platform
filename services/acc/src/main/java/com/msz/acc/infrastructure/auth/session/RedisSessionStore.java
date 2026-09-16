package com.msz.acc.infrastructure.auth.session;

import com.msz.acc.application.port.SessionStore;
import com.msz.common.redis.StringRedisOps;

import java.util.List;
import java.util.function.LongSupplier;
import java.util.function.UnaryOperator;

/**
 * {@link SessionStore} 的 Redis 实现（生产）：基于既有端口 {@link StringRedisOps}
 * （**扩展既有端口，不另造一套**——ACC 侧由 {@code AccLettuceStringRedisOps} 提供 Lettuce 实现）。
 *
 * <p><b>为什么在本类内联 Lua 常量</b>：会话键的写入必须原子（族记录与 refresh 映射要么同时生效、
 * 要么都不生效，否则产生无法整族吊销的孤儿凭据），而 {@link StringRedisOps} 的端口就是
 * {@code eval(script, keys, args)}——脚本常量因此与网关侧 {@code RedisLuaRateLimiter}、
 * 既有 {@code RedisHashTailStore} 同惯例放在使用它的类里。</p>
 *
 * <p><b>单次使用</b>：{@link #consume} 用「EXISTS + DEL」脚本，返回 1 表示**由本次调用删除**——
 * 并发下恰有一个调用拿到 1，这是 refresh 单次使用语义的唯一原子边界（spec「Refresh tokens are
 * single-use and rotate」）。</p>
 *
 * <p><b>fail-closed</b>：任何 Redis 异常（连接失败/超时/脚本错误）统一映射为
 * {@link SessionStoreUnavailableException}——调用方据此快速失败并**不签发任何 token**
 * （spec「Session store unavailable fails fast」，绝不静默降级为不可吊销的本地兜底）。</p>
 *
 * <p><b>TTL 语义</b>：族键/映射键 TTL 由绝对到期毫秒反算为秒（向上取整、下限 1 秒），使族续期与
 * refresh 剩余有效期严格一致；吊销名单键 TTL = 该短 token 剩余有效期
 * （网关契约 `SET revoked:jti:{jti} 1 PX <剩余 TTL>` 的等价写法）。族记录的 TTL **只由族到期时刻
 * 决定**（A1：短 token 的到期时刻进不了这个字段）。</p>
 *
 * <p><b>族记录的原子更新（B11）</b>：族记录是一整条 JSON，绑定短 token jti / 标记已吊销都是
 * 「读-改-写」。并发下朴素的 GET→改→SET 会丢更新（丢掉的 jti 会逃过整族吊销、丢掉的轮换标记会让
 * 重放被误判为「未知 token」），故两条路径都用 {@link #CAS_SET_SCRIPT} / {@link #ROTATE_SCRIPT}
 * 的 **Lua CAS + 有界重试**（与单次使用的 EXISTS+DEL 脚本同风格：判定与写入在同一次 EVAL 内完成）。
 * CAS 冲突重试耗尽时抛 {@link SessionStoreUnavailableException}（fail-closed：绝不静默丢掉绑定，
 * 调用方据此 503 并让客户端重试）。</p>
 */
public final class RedisSessionStore implements SessionStore {

    /** CAS 期望值哨兵：族键不存在（GET 返回 false）时用于表达「期望不存在」。 */
    static final String ABSENT_SENTINEL = "__absent__";

    /**
     * CAS 有界重试上限：每次冲突都会重读最新族记录后重算，实际冲突次数远小于该值；
     * 上限只是「绝不无限循环」的兜底（耗尽即 fail-closed）。
     */
    private static final int CAS_MAX_ATTEMPTS = 64;

    /**
     * 建族脚本：KEYS[1]=族键 KEYS[2]=refresh 键；ARGV[1]=族值 ARGV[2]=族 TTL 秒 ARGV[3]=refresh TTL 秒
     * ARGV[4]=familyId（refresh 映射的值）。两条 SET 在一个脚本内完成 → 原子，不产生孤儿凭据。
     */
    static final String ISSUE_SCRIPT =
            "redis.call('SET', KEYS[1], ARGV[1], 'EX', ARGV[2]);"
            + "redis.call('SET', KEYS[2], ARGV[4], 'EX', ARGV[3]);"
            + "return 1";

    /**
     * 轮换脚本：KEYS[1]=族键 KEYS[2]=新 refresh 键 KEYS[3]=旧 refresh 键；
     * ARGV[1]=族值 ARGV[2]=族 TTL 秒 ARGV[3]=新 refresh TTL 秒 ARGV[4]=familyId
     * ARGV[5]=期望的族键旧值（CAS 快照；键不存在时为 {@link #ABSENT_SENTINEL}）。
     *
     * <p>首行的 CAS 前置校验（B11）保证「读-改-写」不丢并发写入：族键在快照之后被别人改过就返回 0，
     * 由调用方重读、重算（并与最新记录的 accessJtis 合并）后重试。</p>
     */
    static final String ROTATE_SCRIPT =
            "local cur = redis.call('GET', KEYS[1]);"
            + "local expected = ARGV[5];"
            + "if cur == false then"
            + "  if expected ~= '" + ABSENT_SENTINEL + "' then return 0 end;"
            + "else"
            + "  if cur ~= expected then return 0 end;"
            + "end;"
            + "redis.call('SET', KEYS[1], ARGV[1], 'EX', ARGV[2]);"
            + "redis.call('DEL', KEYS[3]);"
            + "redis.call('SET', KEYS[2], ARGV[4], 'EX', ARGV[3]);"
            + "return 1";

    /** 单次使用脚本：KEYS[1]=refresh 键。返回 1=本次消费成功，0=已被消费/不存在/已过期。 */
    static final String CONSUME_SCRIPT =
            "if redis.call('EXISTS', KEYS[1]) == 0 then return 0 end;"
            + "redis.call('DEL', KEYS[1]);"
            + "return 1";

    /**
     * 族记录「比较并写入」脚本（B11 原子读-改-写）：KEYS[1]=族键；
     * ARGV[1]=期望的族键旧值（CAS 快照）ARGV[2]=新值 ARGV[3]=TTL 秒。
     * 返回 1=写入成功，0=键值已被并发修改（调用方重读重算）。键不存在时 GET 返回 false，与任何
     * 快照串都不相等 → 返回 0（调用方重读后发现族已消失，直接返回）。
     */
    static final String CAS_SET_SCRIPT =
            "if redis.call('GET', KEYS[1]) ~= ARGV[1] then return 0 end;"
            + "redis.call('SET', KEYS[1], ARGV[2], 'EX', ARGV[3]);"
            + "return 1";

    /** 吊销名单写脚本（网关共享契约）：KEYS[1]=revoked:jti:{jti}；ARGV[1]=占位值 ARGV[2]=TTL 秒。 */
    static final String REVOKE_SCRIPT =
            "redis.call('SET', KEYS[1], ARGV[1], 'EX', ARGV[2]);"
            + "return 1";

    private final StringRedisOps ops;
    private final LongSupplier clockMillis;

    public RedisSessionStore(StringRedisOps ops, LongSupplier clockMillis) {
        this.ops = ops;
        this.clockMillis = clockMillis;
    }

    @Override
    public void issue(FamilyRecord family, String refreshJti, long refreshTtlSeconds) {
        call(ISSUE_SCRIPT, List.of(familyKey(family.familyId()), refreshKey(refreshJti)),
                List.of(FamilyRecordJson.encode(family), String.valueOf(ttlSeconds(family.expiresAtMillis())),
                        String.valueOf(refreshTtlSeconds), family.familyId()));
    }

    @Override
    public FamilyRecord find(String familyId) {
        String json = callGet(familyKey(familyId));
        return json == null ? null : FamilyRecordJson.decode(json);
    }

    @Override
    public void rotate(FamilyRecord family, String newRefreshJti, long refreshTtlSeconds, String consumedJti) {
        String key = familyKey(family.familyId());
        for (int attempt = 0; attempt < CAS_MAX_ATTEMPTS; attempt++) {
            String current = callGet(key);
            // B11：调用方可能拿着「消费旧 refresh 时的族快照」写回——先合并快照之后被并发绑定的 jti
            FamilyRecord toWrite = current == null
                    ? family
                    : family.mergedWithAccessJtisOf(FamilyRecordJson.decode(current), clockMillis.getAsLong());
            Object result = call(ROTATE_SCRIPT,
                    List.of(key, refreshKey(newRefreshJti), refreshKey(consumedJti)),
                    List.of(FamilyRecordJson.encode(toWrite), String.valueOf(ttlSeconds(toWrite.expiresAtMillis())),
                            String.valueOf(refreshTtlSeconds), family.familyId(),
                            current == null ? ABSENT_SENTINEL : current));
            if (written(result)) {
                return;
            }
        }
        throw casConflictExhausted("轮换", family.familyId());
    }

    @Override
    public boolean consume(String refreshJti) {
        Object result = call(CONSUME_SCRIPT, List.of(refreshKey(refreshJti)), List.of());
        return result instanceof Number n && n.longValue() == 1L;
    }

    @Override
    public void markRevoked(String familyId) {
        updateFamily(familyId, family -> new FamilyRecord(family.familyId(), family.accountId(), family.role(),
                family.mfa(), family.createdAtMillis(), family.expiresAtMillis(), FamilyRecord.STATUS_REVOKED,
                family.currentJti(), family.previousJti(), family.previousValidUntilMillis(),
                family.rotatedJtis(), family.accessJtis()));
    }

    @Override
    public void bindAccessJti(String familyId, String accessJti, long expiresAtMillis) {
        updateFamily(familyId, family -> family.pruned(clockMillis.getAsLong())
                .withAccessJti(accessJti, expiresAtMillis));
    }

    /**
     * 族记录的原子「读-改-写」（B11）：CAS 快照 + Lua 内比较写入，冲突则重读重算。
     *
     * <p>族键不存在（已到期/被清理）时直接返回——与 {@link #find} 返回 null 的既有语义一致，
     * 不会凭空重建族记录。</p>
     */
    private void updateFamily(String familyId, UnaryOperator<FamilyRecord> mutation) {
        String key = familyKey(familyId);
        for (int attempt = 0; attempt < CAS_MAX_ATTEMPTS; attempt++) {
            String current = callGet(key);
            if (current == null) {
                return;
            }
            FamilyRecord updated = mutation.apply(FamilyRecordJson.decode(current));
            // A1：TTL 取**更新后**记录的族到期时刻（不得再用更新前的值，否则污染会继续传播）
            Object result = call(CAS_SET_SCRIPT, List.of(key), List.of(current, FamilyRecordJson.encode(updated),
                    String.valueOf(ttlSeconds(updated.expiresAtMillis()))));
            if (written(result)) {
                return;
            }
        }
        throw casConflictExhausted("族记录更新", familyId);
    }

    private static boolean written(Object result) {
        return result instanceof Number n && n.longValue() == 1L;
    }

    private static SessionStoreUnavailableException casConflictExhausted(String action, String familyId) {
        return new SessionStoreUnavailableException(action + "并发冲突：CAS 重试 " + CAS_MAX_ATTEMPTS
                + " 次仍未写入（familyId=" + familyId + "）——按 fail-closed 处置，绝不静默丢弃会话状态");
    }

    @Override
    public void revoke(List<AccessJti> accessJtis) {
        for (AccessJti jti : accessJtis) {
            call(REVOKE_SCRIPT, List.of(REVOKED_KEY_PREFIX + jti.jti()),
                    List.of(REVOKED_VALUE, String.valueOf(Math.max(jti.remainingSeconds(), 1L))));
        }
    }

    @Override
    public void ping() {
        // 读一个必然不存在的键：连通即返回 null，异常即 fail-closed
        callGet(FAMILY_KEY_PREFIX + "ping-probe");
    }

    /** 绝对到期毫秒 → Redis 秒 TTL（向上取整、下限 1 秒；已过期给 1 秒使其自然消失）。 */
    private long ttlSeconds(long expiresAtMillis) {
        long remainingMillis = expiresAtMillis - clockMillis.getAsLong();
        if (remainingMillis <= 0) {
            return 1L;
        }
        return Math.max(1L, (remainingMillis + 999L) / 1000L);
    }

    private String callGet(String key) {
        try {
            return ops.get(key);
        } catch (RuntimeException e) {
            throw new SessionStoreUnavailableException("会话存储不可用（GET " + key + "）", e);
        }
    }

    private Object call(String script, List<String> keys, List<String> args) {
        try {
            return ops.eval(script, keys, args);
        } catch (RuntimeException e) {
            throw new SessionStoreUnavailableException("会话存储不可用（EVAL " + keys + "）", e);
        }
    }

    private static String familyKey(String familyId) {
        return FAMILY_KEY_PREFIX + familyId;
    }

    private static String refreshKey(String jti) {
        return REFRESH_KEY_PREFIX + jti;
    }
}
