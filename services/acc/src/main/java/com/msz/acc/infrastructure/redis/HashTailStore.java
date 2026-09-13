package com.msz.acc.infrastructure.redis;

import java.time.Instant;
import java.util.function.Function;

/**
 * 存证哈希链尾存储抽象（2.2，对齐 design.md D-1 方案 A：Redis 每账户链尾快照）。
 *
 * <p>{@link #writeTail} 的 hashFn 为「前链 hash → 新 hash」的一元函数（由调用方预绑定
 * rowData/occurredAt，即 {@code prev -> HashChainService.compute(prev, rowData, occurredAt)}）。
 */
public interface HashTailStore {

    /**
     * 原子追加链尾：取旧链尾（无则创世哈希）→ 计算 hashFn(prev) → 回写 → 返回新 hash。
     */
    String writeTail(long accountId, String rowData, Instant occurredAt, Function<String, String> hashFn);

    /** 读取链尾快照，不存在返回 null。 */
    String readTail(long accountId);

    /** 重建链尾（Redis 丢失时从 DB 反查最近月表后回填）。 */
    void rebuild(long accountId, String lastHashFromDb);
}
