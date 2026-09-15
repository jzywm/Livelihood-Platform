package com.msz.acc.infrastructure.auth.session;

import com.msz.acc.application.port.SessionStore;
import com.msz.common.redis.StringRedisOps;

import java.util.List;
import java.util.function.LongSupplier;

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
 * （网关契约 `SET revoked:jti:{jti} 1 PX <剩余 TTL>` 的等价写法）。</p>
 */
public final class RedisSessionStore implements SessionStore {

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
     * ARGV[1]=族值 ARGV[2]=族 TTL 秒 ARGV[3]=新 refresh TTL 秒 ARGV[4]=familyId。
     */
    static final String ROTATE_SCRIPT =
            "redis.call('SET', KEYS[1], ARGV[1], 'EX', ARGV[2]);"
            + "redis.call('DEL', KEYS[3]);"
            + "redis.call('SET', KEYS[2], ARGV[4], 'EX', ARGV[3]);"
            + "return 1";

    /** 单次使用脚本：KEYS[1]=refresh 键。返回 1=本次消费成功，0=已被消费/不存在/已过期。 */
    static final String CONSUME_SCRIPT =
            "if redis.call('EXISTS', KEYS[1]) == 0 then return 0 end;"
            + "redis.call('DEL', KEYS[1]);"
            + "return 1";

    /** 单键写 + TTL 脚本（标记族已吊销时保留记录）：KEYS[1]=键；ARGV[1]=值 ARGV[2]=TTL 秒。 */
    static final String SET_SCRIPT =
            "redis.call('SET', KEYS[1], ARGV[1], 'EX', ARGV[2]);"
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
        call(ROTATE_SCRIPT,
                List.of(familyKey(family.familyId()), refreshKey(newRefreshJti), refreshKey(consumedJti)),
                List.of(FamilyRecordJson.encode(family), String.valueOf(ttlSeconds(family.expiresAtMillis())),
                        String.valueOf(refreshTtlSeconds), family.familyId()));
    }

    @Override
    public boolean consume(String refreshJti) {
        Object result = call(CONSUME_SCRIPT, List.of(refreshKey(refreshJti)), List.of());
        return result instanceof Number n && n.longValue() == 1L;
    }

    @Override
    public void markRevoked(String familyId) {
        FamilyRecord family = find(familyId);
        if (family == null) {
            return;
        }
        FamilyRecord revoked = new FamilyRecord(family.familyId(), family.accountId(), family.role(),
                family.mfa(), family.createdAtMillis(), family.expiresAtMillis(), FamilyRecord.STATUS_REVOKED,
                family.currentJti(), family.previousJti(), family.previousValidUntilMillis(),
                family.rotatedJtis());
        call(SET_SCRIPT, List.of(familyKey(familyId)),
                List.of(FamilyRecordJson.encode(revoked), String.valueOf(ttlSeconds(family.expiresAtMillis()))));
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
