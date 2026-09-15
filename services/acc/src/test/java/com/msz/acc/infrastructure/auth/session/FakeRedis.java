package com.msz.acc.infrastructure.auth.session;

import com.msz.acc.application.port.SessionStore;
import com.msz.common.redis.StringRedisOps;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 测试用假 Redis（仅测试源集，不属生产代码）：以一张 Map 模拟键空间，**支持真实 TTL 语义**
 * （外部提供毫秒时钟），并把 {@link RedisSessionStore} 的五条 Lua 脚本按**脚本常量精确匹配**
 * 分派执行、把「脚本名 + 键 + 参数」记录下来。
 *
 * <p>为什么需要它：单元测试环境没有真实 Redis，而 `RedisSessionStore` 的正确性有一半在
 * 「键构造 + TTL 秒数换算 + 单次使用返回值」——这些从 {@code SessionStore} 签名完全观察不到。
 * 假实现如实模拟 Redis 的 `SET ... EX` / `DEL` / `EXISTS` 语义，因此
 * {@link RedisSessionStoreContractTest} 可以**直跑与内存实现同一套端口契约断言**。</p>
 *
 * <p>脚本按常量字符串精确匹配分派：脚本内容改动而假实现未同步时会立刻
 * {@link UnsupportedOperationException} 失败，不会出现「脚本悄悄改坏但测试仍绿」。</p>
 */
final class FakeRedis {

    private final Map<String, String> store = new LinkedHashMap<>();
    private final Map<String, Long> deadlines = new LinkedHashMap<>();
    private final List<Call> calls = new ArrayList<>();
    private final java.util.function.LongSupplier clockMillis;

    FakeRedis(java.util.function.LongSupplier clockMillis) {
        this.clockMillis = clockMillis;
    }

    /** 记录一次端口调用（脚本名 + 键 + 参数）。 */
    record Call(String script, List<String> keys, List<String> args) {

        String key(int index) {
            return keys.get(index);
        }

        String arg(int index) {
            return args.get(index);
        }
    }

    List<Call> calls() {
        return List.copyOf(calls);
    }

    /** 指定脚本名的最后一次调用（无则断言失败）。 */
    Call lastOf(String script) {
        for (int i = calls.size() - 1; i >= 0; i--) {
            if (calls.get(i).script().equals(script)) {
                return calls.get(i);
            }
        }
        throw new AssertionError("未观察到脚本调用：" + script + "，实际=" + calls);
    }

    void clearCalls() {
        calls.clear();
    }

    StringRedisOps ops() {
        return new Ops();
    }

    /** 原始值（已过期视为不存在）。 */
    String rawValue(String key) {
        return live(key) ? store.get(key) : null;
    }

    /** 原始剩余 TTL（秒，向上取整；与 Redis TTL 语义一致，键不存在/已过期返回 -2）。 */
    long rawTtl(String key) {
        if (!live(key)) {
            return -2L;
        }
        Long deadline = deadlines.get(key);
        if (deadline == null) {
            return -1L;
        }
        long remaining = deadline - clockMillis.getAsLong();
        return remaining <= 0 ? -2L : Math.max(1L, (remaining + 999L) / 1000L);
    }

    private boolean live(String key) {
        if (!store.containsKey(key)) {
            return false;
        }
        Long deadline = deadlines.get(key);
        if (deadline != null && deadline <= clockMillis.getAsLong()) {
            store.remove(key);
            deadlines.remove(key);
            return false;
        }
        return true;
    }

    private void set(String key, String value, long ttlSeconds) {
        store.put(key, value);
        deadlines.put(key, clockMillis.getAsLong() + ttlSeconds * 1000L);
    }

    private void del(String key) {
        store.remove(key);
        deadlines.remove(key);
    }

    private String dispatch(String script, List<String> keys, List<String> args) {
        if (RedisSessionStore.ISSUE_SCRIPT.equals(script)) {
            set(keys.get(0), args.get(0), Long.parseLong(args.get(1)));
            set(keys.get(1), args.get(3), Long.parseLong(args.get(2)));
            return "ISSUE";
        }
        if (RedisSessionStore.ROTATE_SCRIPT.equals(script)) {
            set(keys.get(0), args.get(0), Long.parseLong(args.get(1)));
            del(keys.get(2));
            set(keys.get(1), args.get(3), Long.parseLong(args.get(2)));
            return "ROTATE";
        }
        if (RedisSessionStore.CONSUME_SCRIPT.equals(script)) {
            // EXISTS + DEL：单次使用的原子边界，恰有一次调用拿到「存在」
            boolean existed = live(keys.get(0));
            del(keys.get(0));
            return existed ? "CONSUME_HIT" : "CONSUME_MISS";
        }
        // 注意顺序：REVOKE_SCRIPT 与 SET_SCRIPT 都是「SET key value EX ttl」，字符串相同；
        // 先判 REVOKE 才能让吊销名单的断言区分出「这是吊销写入」而非「族记录续期写」
        if (RedisSessionStore.REVOKE_SCRIPT.equals(script)) {
            set(keys.get(0), args.get(0), Long.parseLong(args.get(1)));
            return "REVOKE";
        }
        if (RedisSessionStore.SET_SCRIPT.equals(script)) {
            set(keys.get(0), args.get(0), Long.parseLong(args.get(1)));
            return "SET";
        }
        throw new UnsupportedOperationException("假 Redis 未覆盖的脚本：" + script);
    }

    private final class Ops implements StringRedisOps {

        @Override
        public Object eval(String script, List<String> keys, List<String> args) {
            String name = dispatch(script, keys, args);
            calls.add(new Call(name, List.copyOf(keys), List.copyOf(args)));
            return name.startsWith("CONSUME") ? ("CONSUME_HIT".equals(name) ? 1L : 0L) : 1L;
        }

        @Override
        public String get(String key) {
            calls.add(new Call("GET", List.of(key), List.of()));
            return rawValue(key);
        }

        @Override
        public Long incr(String key) {
            throw new UnsupportedOperationException("会话存储不使用 INCR");
        }

        @Override
        public Boolean expire(String key, long seconds) {
            throw new UnsupportedOperationException("会话存储不使用 EXPIRE");
        }

        @Override
        public Boolean setNx(String key, String value, long ttlSeconds) {
            throw new UnsupportedOperationException("会话存储不使用 SETNX");
        }
    }
}
