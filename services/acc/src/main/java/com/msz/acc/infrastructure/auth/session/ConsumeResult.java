package com.msz.acc.infrastructure.auth.session;

/**
 * 一次 refresh 消费的判定结果（spec「Refresh tokens are single-use and rotate」/「Session family and
 * replay detection」）。判别顺序见 {@link RefreshTokenStore#consume}。
 */
public sealed interface ConsumeResult {

    /**
     * 正常轮换：refresh 有效且未被消费，已原子消费并续期族记录。
     *
     * @param family 轮换前的族记录（调用方据此写新 jti / 宽限窗口）
     */
    record Rotated(FamilyRecord family) implements ConsumeResult {
    }

    /**
     * 并发重试：presented jti 是「刚被轮换掉」的那一个，且仍在**宽限窗口**内——
     * 多标签页同时换发属正常并发，**不判泄露**（design Risks）；调用方返回当前有效 token 对。
     *
     * @param family 当前族记录（其 {@code currentJti} 即并发兄弟请求刚签发的那一个）
     */
    record ConcurrentRetry(FamilyRecord family) implements ConsumeResult {
    }

    /**
     * 重用/泄露信号：presented jti 已被轮换且超出宽限窗口（或属已吊销族）——
     * 调用方**吊销整族**并记安全审计事件。
     *
     * @param family 命中重放的族记录（族已吊销时 status 为 REVOKED，用于幂等记事件）
     */
    record Replay(FamilyRecord family) implements ConsumeResult {
    }

    /** 拒绝：refresh 缺失/签名非法/已过期/映射不存在（未知）；不区分原因，对外统一 2001。 */
    record Invalid() implements ConsumeResult {
    }
}
