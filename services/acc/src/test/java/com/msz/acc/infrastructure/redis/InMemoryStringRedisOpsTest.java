package com.msz.acc.infrastructure.redis;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * InMemoryStringRedisOps（S5）：StringRedisOps 内存实现（M1 无 Redis 部署的本地兜底）。
 * 覆盖：setNx/expire/get（TTL 过期）、incr，以及 RedisHashTailStore 依赖的
 * WRITE_TAIL_SCRIPT（CAS）/SET_SCRIPT 两条 Lua 语义。
 */
class InMemoryStringRedisOpsTest {

    private final InMemoryStringRedisOps ops = new InMemoryStringRedisOps();

    @Test
    @DisplayName("setNx：首次写入成功、重复写入失败；expire 后 get 为 null")
    void ut_setNxAndExpiry() {
        assertThat(ops.setNx("k1", "v1", 300)).isTrue();
        assertThat(ops.setNx("k1", "v2", 300)).isFalse();
        assertThat(ops.get("k1")).isEqualTo("v1");

        ops.expire("k1", 0);
        assertThat(ops.get("k1")).isNull();
    }

    @Test
    @DisplayName("incr：不存在从 0 起、存在则自增")
    void ut_incr() {
        assertThat(ops.incr("c")).isEqualTo(1L);
        assertThat(ops.incr("c")).isEqualTo(2L);
    }

    @Test
    @DisplayName("WRITE_TAIL_SCRIPT：期望旧值匹配才 CAS 写入，返回 1；不匹配返回 0")
    void ut_writeTailCasSemantics() {
        assertThat(ops.eval(RedisHashTailStore.WRITE_TAIL_SCRIPT, List.of("tail"),
                List.of("genesis", "hash-1"))).isEqualTo(1L);
        assertThat(ops.get("tail")).isEqualTo("hash-1");

        // 期望旧值不匹配 → CAS 失败，值不变
        assertThat(ops.eval(RedisHashTailStore.WRITE_TAIL_SCRIPT, List.of("tail"),
                List.of("stale", "hash-2"))).isEqualTo(0L);
        assertThat(ops.get("tail")).isEqualTo("hash-1");
    }

    @Test
    @DisplayName("SET_SCRIPT：直接覆盖写入")
    void ut_setScriptOverwrites() {
        ops.setNx("tail", "old", 300);
        assertThat(ops.eval(RedisHashTailStore.SET_SCRIPT, List.of("tail"), List.of("new"))).isEqualTo(1L);
        assertThat(ops.get("tail")).isEqualTo("new");
    }

    @Test
    @DisplayName("未知脚本 → UnsupportedOperationException")
    void ut_unknownScriptRejected() {
        org.assertj.core.api.Assertions.assertThatThrownBy(() -> ops.eval("return 1", List.of("k"), List.of()))
                .isInstanceOf(UnsupportedOperationException.class);
    }
}
