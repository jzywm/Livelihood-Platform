package com.msz.acc.infrastructure.auth.session;

import java.util.Map;

/**
 * 会话族记录（`acc:session:{familyId}` 的值，扁平 JSON 编解码）。
 *
 * <p>一次登录 = 一条会话族，族内所有短/长 token 一起吊销（design D2/D3）。字段口径：</p>
 * <ul>
 *   <li>{@code status}：{@link #STATUS_ACTIVE} / {@link #STATUS_REVOKED}——吊销后**保留记录**
 *       （不删除），否则重放已轮换的 refresh 只会看到「未知 token」，无法识别泄露。</li>
 *   <li>{@code currentJti}：当前有效的 refresh jti（每次轮换覆盖）。</li>
 *   <li>{@code previousJti} + {@code previousValidUntilMillis}：刚被轮换掉的 jti 及其
 *       **并发宽限窗口**截止时刻（绝对毫秒）——窗口内重复换发按并发重试处理，不判泄露（design Risks）。</li>
 *   <li>{@code rotatedJtis}：本族全部**已轮换** refresh jti → 其原始到期时刻（绝对毫秒）。
 *       保留期与原 refresh 一致（到期由 {@link #pruned(long)} 清理，不会无限累积）；
 *       正是这份标记让重放可被识别（design D2）。</li>
 *   <li>{@code accessJtis}：本族已签发且**可能仍未过期**的短 token jti → 其到期时刻（绝对毫秒）。
 *       整族吊销时逐条写 `revoked:jti:{jti}`（TTL = 剩余有效期），这正是 spec「revoke every access
 *       token of the family including unexpired ones」的落地依据；短 token 仅 15 分钟，
 *       条目随 {@link #pruned(long)} 收缩，数量有界。</li>
 *   <li>{@code expiresAtMillis}：族到期时刻（= 本次 refresh 签发时刻 + refresh 有效期），
 *       用于把 Redis 绝对毫秒 TTL 反算为秒。</li>
 * </ul>
 *
 * @param familyId              会话族 ID
 * @param accountId             账户 ID（refresh `sub`）
 * @param role                  六方角色（refresh `role`，轮换时回填短 token）
 * @param mfa                   建族时是否已完成 MFA
 * @param createdAtMillis       建族时刻（epoch 毫秒，宽松但足够审计）
 * @param expiresAtMillis       族到期时刻（epoch 毫秒）
 * @param status                族状态，见 {@link #STATUS_ACTIVE}/{@link #STATUS_REVOKED}
 * @param currentJti            当前 refresh jti
 * @param previousJti           上一个 refresh jti（宽限窗口内有效），无则 null
 * @param previousValidUntilMillis 上一个 jti 的宽限截止时刻（epoch 毫秒），无则 0
 * @param rotatedJtis           已轮换 jti → 原始到期时刻（epoch 毫秒）
 * @param accessJtis            短 token jti → 到期时刻（epoch 毫秒）
 */
public record FamilyRecord(String familyId, long accountId, String role, boolean mfa,
                           long createdAtMillis, long expiresAtMillis, String status, String currentJti,
                           String previousJti, long previousValidUntilMillis,
                           Map<String, Long> rotatedJtis, Map<String, Long> accessJtis) {

    /** 族有效（可换发）。 */
    public static final String STATUS_ACTIVE = "ACTIVE";

    /** 族已吊销（登出 / 重用检测整族吊销）；记录保留至到期以支持重放识别与审计。 */
    public static final String STATUS_REVOKED = "REVOKED";

    public boolean revoked() {
        return STATUS_REVOKED.equals(status);
    }

    /** 返回剪掉已过期「已轮换」标记与已过期短 token jti 后的副本（写入前调用，保证条目有界）。 */
    public FamilyRecord pruned(long nowMillis) {
        Map<String, Long> keptRotated = keepLive(rotatedJtis, nowMillis);
        Map<String, Long> keptAccess = keepLive(accessJtis, nowMillis);
        boolean previousExpired = previousJti != null && previousValidUntilMillis <= nowMillis;
        return new FamilyRecord(familyId, accountId, role, mfa, createdAtMillis, expiresAtMillis, status,
                currentJti, previousExpired ? null : previousJti, previousExpired ? 0L : previousValidUntilMillis,
                keptRotated, keptAccess);
    }

    /** 追加一条短 token jti（已存在则刷新其到期时刻）。 */
    public FamilyRecord withAccessJti(String jti, long expiresAtMillis) {
        Map<String, Long> updated = new java.util.LinkedHashMap<>(accessJtis);
        updated.put(jti, expiresAtMillis);
        return new FamilyRecord(familyId, accountId, role, mfa, createdAtMillis, expiresAtMillis, status,
                currentJti, previousJti, previousValidUntilMillis, rotatedJtis, updated);
    }

    private static Map<String, Long> keepLive(Map<String, Long> source, long nowMillis) {
        Map<String, Long> kept = new java.util.LinkedHashMap<>();
        for (Map.Entry<String, Long> entry : source.entrySet()) {
            if (entry.getValue() != null && entry.getValue() > nowMillis) {
                kept.put(entry.getKey(), entry.getValue());
            }
        }
        return kept;
    }
}
