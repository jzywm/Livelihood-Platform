package com.msz.acc.infrastructure.redis;

import com.msz.acc.domain.service.HashChainService;
import com.msz.common.redis.StringRedisOps;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.time.Instant;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.function.Consumer;
import java.util.function.Function;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * UT-B01 / D-1 方案 A：哈希链尾 Redis 快照——Lua CAS 原子写、并发一致性、Redis 丢失重建、异步核对。
 */
class RedisHashTailStoreTest {

    private static final long ACCOUNT_ID = 1001L;
    private static final String ROW_DATA = "TYPE=IN|AMT=1.00|CH=20260913";
    private static final Instant OCCURRED_AT = Instant.parse("2026-09-13T10:00:00Z");

    private final HashChainService hashChain = new HashChainService();

    private RedisHashTailStore store(FakeRedisOps ops) {
        return new RedisHashTailStore(ops, hashChain.genesisHash());
    }

    private Function<String, String> hashFn() {
        return prev -> hashChain.compute(prev, ROW_DATA, OCCURRED_AT);
    }

    @Test
    @DisplayName("UT-B01 写链尾：自创世哈希起链并读回")
    void ut_writeTailAppendsChainTail() {
        FakeRedisOps ops = new FakeRedisOps();
        RedisHashTailStore store = store(ops);

        String h1 = store.writeTail(ACCOUNT_ID, ROW_DATA, OCCURRED_AT, hashFn());

        String expected = hashChain.compute(hashChain.genesisHash(), ROW_DATA, OCCURRED_AT);
        assertThat(h1).isEqualTo(expected);
        assertThat(store.readTail(ACCOUNT_ID)).isEqualTo(expected);
    }

    @Test
    @DisplayName("D-1 并发写链尾一致性：20 线程 × 10 次，最终链尾与顺序计算一致")
    void ut_concurrentWriteTailFinalHashMatchesSequential() throws Exception {
        FakeRedisOps ops = new FakeRedisOps();
        RedisHashTailStore store = store(ops);
        Function<String, String> fn = hashFn();

        // 顺序基线：自创世哈希应用 hashFn 200 次
        List<String> expectedChain = new ArrayList<>();
        String cursor = hashChain.genesisHash();
        for (int i = 0; i < 200; i++) {
            cursor = fn.apply(cursor);
            expectedChain.add(cursor);
        }

        int threads = 20;
        int perThread = 10;
        ExecutorService pool = Executors.newFixedThreadPool(threads);
        List<Future<String>> futures = new ArrayList<>();
        for (int t = 0; t < threads; t++) {
            for (int i = 0; i < perThread; i++) {
                futures.add(pool.submit(() -> store.writeTail(ACCOUNT_ID, ROW_DATA, OCCURRED_AT, fn)));
            }
        }
        List<String> results = Collections.synchronizedList(new ArrayList<>());
        for (Future<String> f : futures) {
            results.add(f.get());
        }
        pool.shutdownNow();

        // 全部成功（无写入失败）
        assertThat(results).hasSize(200).doesNotContainNull();

        // 所有返回值构成一条可 verify 的链（相同语料下 = 顺序基线链的 200 个互异哈希，无丢失/无重复）
        Set<String> expectedSet = new HashSet<>(expectedChain);
        assertThat(expectedSet).hasSize(200);
        assertThat(new HashSet<>(results)).isEqualTo(expectedSet);

        // 最终链尾与单线程顺序计算结果一致
        assertThat(store.readTail(ACCOUNT_ID)).isEqualTo(expectedChain.get(199));
    }

    @Test
    @DisplayName("D-1 Redis 丢失（readTail null）→ 从 DB 链尾重建")
    void ut_readTailEmptyThenRebuildFromDb() {
        FakeRedisOps ops = new FakeRedisOps();
        RedisHashTailStore store = store(ops);

        assertThat(store.readTail(ACCOUNT_ID)).isNull();

        store.rebuild(ACCOUNT_ID, "db-hash-abc");

        assertThat(store.readTail(ACCOUNT_ID)).isEqualTo("db-hash-abc");
    }

    @Test
    @DisplayName("D-1 核对不一致 → 触发告警钩子并重建为 DB 值")
    void ut_verifierMismatchTriggersAlertAndRebuild() {
        FakeRedisOps ops = new FakeRedisOps();
        RedisHashTailStore store = store(ops);
        store.rebuild(ACCOUNT_ID, "redis-hash");

        List<String> alerts = new ArrayList<>();
        Consumer<String> alertHook = alerts::add;
        RedisHashTailVerifier verifier = new RedisHashTailVerifier(store, alertHook);
        FlowHashReader reader = accountId -> "db-hash-def";

        verifier.verifyOnce(ACCOUNT_ID, reader);

        assertThat(alerts).hasSize(1);
        assertThat(store.readTail(ACCOUNT_ID)).isEqualTo("db-hash-def");
    }

    @Test
    @DisplayName("D-1 Redis 丢失核对 → 从 DB 重建且不告警")
    void ut_verifierRedisLostRebuildsFromDbWithoutAlert() {
        FakeRedisOps ops = new FakeRedisOps();
        RedisHashTailStore store = store(ops);

        List<String> alerts = new ArrayList<>();
        RedisHashTailVerifier verifier = new RedisHashTailVerifier(store, alerts::add);
        FlowHashReader reader = accountId -> "db-hash-xyz";

        verifier.verifyOnce(ACCOUNT_ID, reader);

        assertThat(alerts).isEmpty();
        assertThat(store.readTail(ACCOUNT_ID)).isEqualTo("db-hash-xyz");
    }

    /**
     * 内存 fake：eval 以 synchronized 模拟 Lua 原子语义（简报允许「接口级原子」方案）。
     * WRITE_TAIL_SCRIPT → CAS；SET_SCRIPT → 直接覆盖写。
     */
    private static final class FakeRedisOps implements StringRedisOps {
        private final Map<String, String> store = new ConcurrentHashMap<>();

        @Override
        public Long incr(String key) {
            throw new UnsupportedOperationException();
        }

        @Override
        public Boolean expire(String key, long seconds) {
            return true;
        }

        @Override
        public String get(String key) {
            return store.get(key);
        }

        @Override
        public Boolean setNx(String key, String value, long ttlSeconds) {
            return store.putIfAbsent(key, value) == null;
        }

        @Override
        public Object eval(String script, List<String> keys, List<String> args) {
            synchronized (this) {
                if (RedisHashTailStore.WRITE_TAIL_SCRIPT.equals(script)) {
                    String cur = store.get(keys.get(0));
                    if (cur == null) {
                        cur = args.get(0);
                    }
                    if (cur.equals(args.get(0))) {
                        store.put(keys.get(0), args.get(1));
                        return 1L;
                    }
                    return 0L;
                }
                if (RedisHashTailStore.SET_SCRIPT.equals(script)) {
                    store.put(keys.get(0), args.get(0));
                    return 1L;
                }
                throw new UnsupportedOperationException("未知脚本");
            }
        }
    }
}
