package com.msz.acc.infrastructure.redis;

import com.msz.common.redis.StringRedisOps;

import java.time.Instant;
import java.util.List;
import java.util.function.Function;

/**
 * 基于 {@link StringRedisOps} 的哈希链尾存储实现（2.2，D-1 方案 A）。
 *
 * <p>key：{@code acc:hash:{accountId}}。写链尾的并发串行化用 Redis Lua CAS 原子完成：
 * Java 侧先读旧链尾并计算新 hash，再以「期望旧值 → 写新值」的 Lua 脚本原子提交，
 * 冲突（并发被别的写抢先）则重试，保证链尾不丢写、不覆盖。
 *
 * <p>哈希计算依赖 Java 的 SHA-256（无法下沉到 Redis Lua），故 Lua 脚本只承担「比较-交换」
 * 这一原子边界；{@code WRITE_TAIL_SCRIPT} 为生产真实脚本常量，测试以 fake eval 的
 * synchronized 语义模拟其原子性（见 RedisHashTailStoreTest）。
 */
public final class RedisHashTailStore implements HashTailStore {

    /** 原子追加链尾 CAS 脚本：KEYS[1]=链尾 key，ARGV[1]=期望旧值（缺失视为创世哈希），ARGV[2]=新 hash。 */
    public static final String WRITE_TAIL_SCRIPT =
            "local cur = redis.call('GET', KEYS[1]);"
            + "if not cur then cur = ARGV[1] end;"
            + "if cur == ARGV[1] then redis.call('SET', KEYS[1], ARGV[2]); return 1 else return 0 end";

    /** 直接覆盖写脚本（rebuild 用）：KEYS[1]=链尾 key，ARGV[1]=新值。 */
    public static final String SET_SCRIPT =
            "redis.call('SET', KEYS[1], ARGV[1]); return 1";

    private final StringRedisOps ops;
    private final String genesisHash;

    public RedisHashTailStore(StringRedisOps ops, String genesisHash) {
        this.ops = ops;
        this.genesisHash = genesisHash;
    }

    @Override
    public String writeTail(long accountId, String rowData, Instant occurredAt, Function<String, String> hashFn) {
        String key = key(accountId);
        while (true) {
            String prev = ops.get(key);
            if (prev == null) {
                prev = genesisHash;
            }
            String newHash = hashFn.apply(prev);
            Object result = ops.eval(WRITE_TAIL_SCRIPT, List.of(key), List.of(prev, newHash));
            if (isSuccess(result)) {
                return newHash;
            }
            // 冲突：别的写先落链尾，重试（重新取链尾→算 hash→CAS）
        }
    }

    @Override
    public String readTail(long accountId) {
        return ops.get(key(accountId));
    }

    @Override
    public void rebuild(long accountId, String lastHashFromDb) {
        if (lastHashFromDb == null) {
            // 无 DB 链尾可回填：保持 Redis 丢失态，下次写入自创世哈希起链
            return;
        }
        ops.eval(SET_SCRIPT, List.of(key(accountId)), List.of(lastHashFromDb));
    }

    private static String key(long accountId) {
        return "acc:hash:" + accountId;
    }

    private static boolean isSuccess(Object evalResult) {
        return evalResult instanceof Number n && n.longValue() == 1L;
    }
}
