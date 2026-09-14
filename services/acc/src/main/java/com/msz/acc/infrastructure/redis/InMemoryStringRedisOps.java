package com.msz.acc.infrastructure.redis;

import com.msz.common.redis.StringRedisOps;

import java.util.List;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicLong;

/**
 * {@link StringRedisOps} 内存实现（S5）：M1 无 Redis 部署时的本地兜底。
 *
 * <p>支持 incr/get/setNx+TTL/expire 与 {@link RedisHashTailStore} 依赖的两条 Lua 语义
 * （{@link RedisHashTailStore#WRITE_TAIL_SCRIPT} 的 CAS 比较-交换、{@link RedisHashTailStore#SET_SCRIPT} 的直接覆盖）；
 * 其余脚本拒绝（UnsupportedOperationException）。</p>
 */
public final class InMemoryStringRedisOps implements StringRedisOps {

    private final ConcurrentHashMap<String, String> store = new ConcurrentHashMap<>();
    private final ConcurrentHashMap<String, Long> expiresAt = new ConcurrentHashMap<>();
    private final AtomicLong seq = new AtomicLong();

    @Override
    public Long incr(String key) {
        String current = get(key);
        long value = current == null ? 0L : Long.parseLong(current);
        value++;
        store.put(key, String.valueOf(value));
        expiresAt.remove(key);
        return value;
    }

    @Override
    public Boolean expire(String key, long seconds) {
        if (store.containsKey(key)) {
            expiresAt.put(key, System.currentTimeMillis() + seconds * 1000L);
            return true;
        }
        return false;
    }

    @Override
    public String get(String key) {
        Long expireAt = expiresAt.get(key);
        if (expireAt != null && expireAt <= System.currentTimeMillis()) {
            store.remove(key);
            expiresAt.remove(key);
            return null;
        }
        return store.get(key);
    }

    @Override
    public Boolean setNx(String key, String value, long ttlSeconds) {
        if (get(key) != null) {
            return false;
        }
        store.put(key, value);
        expiresAt.put(key, System.currentTimeMillis() + ttlSeconds * 1000L);
        return true;
    }

    @Override
    public Object eval(String script, List<String> keys, List<String> args) {
        if (RedisHashTailStore.WRITE_TAIL_SCRIPT.equals(script)) {
            return evalWriteTail(keys, args);
        }
        if (RedisHashTailStore.SET_SCRIPT.equals(script)) {
            String key = keys.get(0);
            store.put(key, args.get(0));
            expiresAt.remove(key);
            return 1L;
        }
        throw new UnsupportedOperationException("内存实现仅支持哈希链尾 CAS/覆盖脚本");
    }

    private long evalWriteTail(List<String> keys, List<String> args) {
        String key = keys.get(0);
        String expectedPrev = args.get(0);
        String newHash = args.get(1);
        String current = get(key);
        if (current == null) {
            current = expectedPrev;
        }
        if (current.equals(expectedPrev)) {
            store.put(key, newHash);
            expiresAt.remove(key);
            return 1L;
        }
        return 0L;
    }
}
