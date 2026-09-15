package com.msz.acc.application.port;

import com.msz.acc.infrastructure.auth.session.AccessJti;
import com.msz.acc.infrastructure.auth.session.FamilyRecord;

import java.util.List;

/**
 * 会话存储端口（design D2/D3/D8）：会话族 + refresh 映射 + 网关共享的吊销名单写入。
 *
 * <p>键与 TTL 契约（**跨服务契约，不得单方变更**）：</p>
 * <ul>
 *   <li>{@code acc:session:{familyId}} → 族记录（扁平 JSON）：TTL = 族剩余有效期（≤ refresh 有效期 7 天），
 *       每次轮换续期</li>
 *   <li>{@code acc:refresh:{jti}} → familyId：TTL = 该 refresh 剩余有效期（**不得超过其有效期**）</li>
 *   <li>{@code revoked:jti:{jti}} → {@code 1}：**网关读取的吊销名单**（契约沿用
 *       `implement-gateway-service` D3），TTL = 该短 token 剩余有效期</li>
 * </ul>
 *
 * <p><b>fail-closed</b>：存储不可用时实现必须抛 {@link SessionStoreUnavailableException}，调用方据此
 * 快速失败——绝不降级为「无法吊销」的本地兜底（proposal「BREAKING」、spec「Session store unavailable
 * fails fast」）。实现落 {@code infrastructure.auth.session}（{@code InMemorySessionStore} 测试/演练兜底、
 * {@code RedisSessionStore} 生产），二者通过同一套端口契约测试。</p>
 */
public interface SessionStore {

    /** 会话族键前缀。 */
    String FAMILY_KEY_PREFIX = "acc:session:";

    /** refresh 映射键前缀。 */
    String REFRESH_KEY_PREFIX = "acc:refresh:";

    /** 网关共享的吊销名单键前缀（契约键）。 */
    String REVOKED_KEY_PREFIX = "revoked:jti:";

    /** 吊销名单占位值（网关只判存在性）。 */
    String REVOKED_VALUE = "1";

    /**
     * 建族（登录）：写族记录并在**同一原子操作**内写入 {@code acc:refresh:{jti}} → familyId 映射。
     * 二者必须同时生效，否则会出现「有 refresh 但无族」的孤儿凭据（无法整族吊销）。
     */
    void issue(FamilyRecord family, String refreshJti, long refreshTtlSeconds);

    /** 读族记录；不存在返回 null。 */
    FamilyRecord find(String familyId);

    /** 轮换：消费旧 refresh 映射 + 写新映射 + 覆盖族记录并续期（宽限/已轮换标记由调用方算好）。 */
    void rotate(FamilyRecord family, String newRefreshJti, long refreshTtlSeconds, String consumedJti);

    /**
     * 原子消费 refresh 映射（单次使用，spec「Refresh tokens are single-use and rotate」）。
     *
     * @return true = 本次调用消费成功（并发下恰一个调用能拿到 true）；false = 键不存在/已被消费
     */
    boolean consume(String refreshJti);

    /** 标记族已吊销（记录保留至到期，使重放被识别为「已吊销族」而非「未知 token」）。 */
    void markRevoked(String familyId);

    /**
     * 把一条**已签发短 token** 的 jti 归属到会话族（整族吊销时按此逐条写 `revoked:jti:{jti}`，
     * spec「revoke every access token of the family including unexpired ones」）。
     *
     * <p>调用时机在「签发前」：绑定失败即不签发，避免出现族不知道的短 token（无法吊销）。</p>
     *
     * @param expiresAtMillis 该短 token 的到期时刻（epoch 毫秒）
     */
    void bindAccessJti(String familyId, String accessJti, long expiresAtMillis);

    /** 写网关共享吊销名单：逐条 `revoked:jti:{jti}` 占位值 + 剩余有效期 TTL（秒，≥1）。 */
    void revoke(List<AccessJti> accessJtis);

    /** 健康检查：存储不可用即抛 {@link SessionStoreUnavailableException}（请求期 fail-closed 判据）。 */
    void ping();
}
