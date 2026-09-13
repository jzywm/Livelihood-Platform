package com.msz.acc.infrastructure.redis;

/**
 * 哈希链尾核对器（2.2，D-1「DB 落库后异步核对」）：比对 Redis 链尾快照与 DB 链尾，
 * 不一致触发告警并重建；Redis 丢失则从 DB 反查重建。
 */
public interface HashTailVerifier {

    void verifyOnce(long accountId, FlowHashReader reader);
}
