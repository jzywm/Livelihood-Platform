package com.msz.acc.infrastructure.redis;

import java.util.function.Consumer;

/**
 * 哈希链尾核对器实现（2.2）。
 *
 * <p>核对逻辑：
 * <ul>
 *   <li>Redis 链尾丢失（null）且 DB 有链尾 → 调 {@link HashTailStore#rebuild} 从 DB 重建；</li>
 *   <li>Redis 与 DB 链尾不一致 → 调告警钩子（{@link Consumer}）并重建为 DB 值；</li>
 *   <li>一致 → 无动作。</li>
 * </ul>
 */
public final class RedisHashTailVerifier implements HashTailVerifier {

    private final HashTailStore store;
    private final Consumer<String> alertHook;

    public RedisHashTailVerifier(HashTailStore store, Consumer<String> alertHook) {
        this.store = store;
        this.alertHook = alertHook;
    }

    @Override
    public void verifyOnce(long accountId, FlowHashReader reader) {
        String redisTail = store.readTail(accountId);
        String dbHash = reader.latestHash(accountId);

        if (redisTail == null) {
            if (dbHash != null) {
                store.rebuild(accountId, dbHash);
            }
            return;
        }
        if (!redisTail.equals(dbHash)) {
            alertHook.accept("哈希链尾不一致 accountId=" + accountId + " redis=" + redisTail + " db=" + dbHash);
            store.rebuild(accountId, dbHash);
        }
    }
}
