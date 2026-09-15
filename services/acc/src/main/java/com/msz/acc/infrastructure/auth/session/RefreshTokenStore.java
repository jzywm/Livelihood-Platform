package com.msz.acc.infrastructure.auth.session;

import com.msz.acc.application.port.SessionStore;
import com.msz.acc.infrastructure.auth.AuthException;
import com.msz.acc.infrastructure.auth.JwtCodec;

import java.time.Instant;
import java.util.Map;
import java.util.function.LongSupplier;

/**
 * refresh 签发、判定与轮换（design D2/D6，spec「Refresh tokens are single-use and rotate」/
 * 「Session family and replay detection」）。
 *
 * <p><b>长期凭据形态</b>：与短 token 同为手写 HS256 JWT（复用 {@link JwtCodec}，不引 JWT 库），
 * 声明 {@code sub}（账户）/ {@code role} / {@code mfa} / {@code fam}（会话族）/ {@code jti} /
 * {@code iat} / {@code exp}，另加 {@code typ=refresh} 以防长短 token 互换（短 token 由网关侧
 * `JwtVerifier` 校验，两侧都是 HS256，必须靠 `typ` 区分）。</p>
 *
 * <p><b>单次使用 + 轮换</b>：每次换发消费旧 jti 映射（{@link SessionStore#consume} 原子完成）、
 * 签发新 jti、把族记录的 {@code currentJti} 覆盖为新 jti，并把旧 jti 记为「已轮换」
 * （保留到其原始到期时刻——**标记必须保留**，否则重放看起来只是「未知 token」而无法触发整族吊销）。</p>
 *
 * <p><b>并发宽限</b>：轮换后 {@code rotationGraceSeconds} 秒内再次出现同一个旧 jti 视为并发重试
 * （多标签页同时换发），返回当前有效 token 对、不判泄露；超出窗口即判重放。同一族在窗口内
 * **不签发第二个新 jti**——重复换发复用当前 jti，故不会放大签名/存储写入。</p>
 */
public final class RefreshTokenStore {

    /** refresh 声明类型标记（与短 token 区分）。 */
    public static final String TYPE_REFRESH = "refresh";

    private static final String CLAIM_TYPE = "typ";
    private static final String CLAIM_FAMILY = "fam";

    private final SessionStore store;
    private final JwtCodec jwtCodec;
    private final String secret;
    private final long refreshTtlSeconds;
    private final long rotationGraceSeconds;
    private final long accessTtlSeconds;
    private final LongSupplier clockMillis;

    public RefreshTokenStore(SessionStore store, JwtCodec jwtCodec, String secret, long refreshTtlSeconds,
                             long rotationGraceSeconds, long accessTtlSeconds, LongSupplier clockMillis) {
        this.store = store;
        this.jwtCodec = jwtCodec;
        this.secret = secret;
        this.refreshTtlSeconds = refreshTtlSeconds;
        this.rotationGraceSeconds = rotationGraceSeconds;
        this.accessTtlSeconds = accessTtlSeconds;
        this.clockMillis = clockMillis;
    }

    /** 建族时签发首个 refresh（写入族记录 + jti 映射，原子）。 */
    public String issueNewFamily(long accountId, String role, boolean mfa) {
        long now = clockMillis.getAsLong();
        String familyId = "fam_" + java.util.UUID.randomUUID().toString().replace("-", "");
        String jti = newJti();
        FamilyRecord family = new FamilyRecord(familyId, accountId, role, mfa, now,
                now + refreshTtlSeconds * 1000L, FamilyRecord.STATUS_ACTIVE, jti, null, 0L, Map.of(), Map.of());
        store.issue(family, jti, refreshTtlSeconds);
        return sign(accountId, role, mfa, familyId, jti);
    }

    /**
     * 把一条已签发短 token 的 jti 归属到族（整族吊销的依据）。
     *
     * <p><b>调用顺序约定</b>：先绑定、后签发——绑定失败即不返回 token，避免「客户端拿到一个
     * 族不知道的短 token」（登出/重放时将无法吊销它）。</p>
     */
    public void bindAccessJti(String familyId, String accessJti) {
        store.bindAccessJti(familyId, accessJti, clockMillis.getAsLong() + accessTtlSeconds * 1000L);
    }

    /**
     * 族内所有**未过期**短 token 的 jti 与剩余有效期（整族吊销入参）。
     *
     * @param extraJti               当前请求携带的短 token jti（其剩余有效期由请求方精确知道，
     *                               优先于族记录的近似值）；无则传 null
     * @param extraRemainingSeconds  当前请求短 token 的剩余有效期（秒）
     */
    public java.util.List<AccessJti> liveAccessJtis(FamilyRecord family, String extraJti,
                                                    long extraRemainingSeconds) {
        long now = clockMillis.getAsLong();
        java.util.List<AccessJti> result = new java.util.ArrayList<>();
        java.util.Set<String> seen = new java.util.HashSet<>();
        boolean externalJtiKnown = extraJti != null && !extraJti.isBlank();
        if (externalJtiKnown) {
            result.add(new AccessJti(extraJti, Math.max(extraRemainingSeconds, 1L)));
            seen.add(extraJti);
        }
        for (Map.Entry<String, Long> entry : family.accessJtis().entrySet()) {
            long remaining = (entry.getValue() - now) / 1000L;
            if (remaining >= 0 && seen.add(entry.getKey())) {
                result.add(new AccessJti(entry.getKey(), Math.max(remaining, 1L)));
            }
        }
        return result;
    }

    /**
     * 消费并判定（**唯一入口**，判别顺序：签名/类型 → 族已吊销 → 当前 jti → 宽限内上一个 jti →
     * 已轮换标记 → 未知/过期）。
     *
     * <p>副作用仅在成功轮换时发生（spec「an exchange MUST NOT have side effects other than rotation and
     * issuance」）：判定为拒绝时不写任何键。</p>
     */
    public ConsumeResult consume(String refreshToken) {
        Map<String, Object> claims = verifyOrNull(refreshToken);
        if (claims == null) {
            return new ConsumeResult.Invalid();
        }
        String jti = stringClaim(claims, "jti");
        String familyId = stringClaim(claims, CLAIM_FAMILY);
        if (jti == null || familyId == null) {
            return new ConsumeResult.Invalid();
        }

        FamilyRecord family = store.find(familyId);
        if (family == null) {
            return new ConsumeResult.Invalid();
        }
        long now = clockMillis.getAsLong();
        if (family.revoked()) {
            // 已吊销族：任一 token 一律拒绝；重放已轮换 jti 仍算泄露事件（幂等记审计）
            return new ConsumeResult.Replay(family);
        }
        if (jti.equals(family.currentJti())) {
            if (!store.consume(jti)) {
                // 竞态：并发请求刚好消费了它，此时族记录已指向新 jti
                FamilyRecord latest = store.find(familyId);
                if (latest == null) {
                    return new ConsumeResult.Invalid();
                }
                if (jti.equals(latest.currentJti())) {
                    return new ConsumeResult.Invalid();
                }
                return latest.previousJti() != null && latest.previousJti().equals(jti)
                        ? new ConsumeResult.ConcurrentRetry(latest)
                        : new ConsumeResult.Replay(latest);
            }
            return new ConsumeResult.Rotated(family);
        }
        if (jti.equals(family.previousJti())) {
            if (family.previousValidUntilMillis() > now) {
                // 并发重试：复用当前 jti（不再签发第二个新 jti，避免写放大）
                return new ConsumeResult.ConcurrentRetry(family);
            }
            // 超出宽限窗口 → 泄露信号
            return new ConsumeResult.Replay(family);
        }
        Long rotatedUntil = family.rotatedJtis().get(jti);
        if (rotatedUntil != null && rotatedUntil > now) {
            return new ConsumeResult.Replay(family);
        }
        // 未知 jti（或标记已到期）：可能是别的族的 token、已过期的 refresh，或族记录被淘汰
        return new ConsumeResult.Invalid();
    }

    /**
     * 轮换签发：消费结果 {@link ConsumeResult.Rotated} 之后调用——签发新 refresh、覆盖族记录
     * （新 currentJti、旧 jti 进「已轮换」标记、宽限窗口起算）。
     *
     * @return 新 refresh token
     */
    public String rotate(FamilyRecord family, String consumedJti) {
        long now = clockMillis.getAsLong();
        String newJti = newJti();
        FamilyRecord rotated = family.pruned(now);
        Map<String, Long> markers = new java.util.LinkedHashMap<>(rotated.rotatedJtis());
        // 旧 jti 的标记保留到其原始到期时刻（= 族到期），重放因此在整个有效期内可识别
        markers.put(consumedJti, rotated.expiresAtMillis());
        FamilyRecord updated = new FamilyRecord(rotated.familyId(), rotated.accountId(), rotated.role(),
                rotated.mfa(), rotated.createdAtMillis(), now + refreshTtlSeconds * 1000L,
                FamilyRecord.STATUS_ACTIVE, newJti, consumedJti, now + rotationGraceSeconds * 1000L, markers,
                rotated.accessJtis());
        store.rotate(updated, newJti, refreshTtlSeconds, consumedJti);
        return sign(updated.accountId(), updated.role(), updated.mfa(), updated.familyId(), newJti);
    }

    /** 复用当前 refresh（并发重试分支：返回当前 jti 的 token，不再签发新值）。 */
    public String current(FamilyRecord family) {
        return sign(family.accountId(), family.role(), family.mfa(), family.familyId(), family.currentJti());
    }

    /**
     * 解析 refresh 并返回其会话族 ID（登出用：仅凭 Cookie 时需先定位族）。
     *
     * @return familyId；token 缺失/签名非法/类型不符/已过期 一律 null（调用方按 2001 处置）
     */
    public String familyIdOf(String refreshToken) {
        Map<String, Object> claims = verifyOrNull(refreshToken);
        return claims == null ? null : stringClaim(claims, CLAIM_FAMILY);
    }

    /** 解析 refresh 的 {@code jti}（审计日志用，不含 token 原文）。 */
    public String jtiOf(String refreshToken) {
        Map<String, Object> claims = verifyOrNull(refreshToken);
        return claims == null ? null : stringClaim(claims, "jti");
    }

    /** refresh 有效期（秒），供接口返回与文档口径对齐。 */
    public long refreshTtlSeconds() {
        return refreshTtlSeconds;
    }

    /** 按 refresh TTL 反算剩余秒数（≥1，避免 Redis 拒收 0/负 TTL），用于族/映射续期。 */
    public long remainingSeconds(long expiresAtMillis) {
        long remaining = (expiresAtMillis - clockMillis.getAsLong()) / 1000L;
        return Math.max(remaining, 1L);
    }

    /**
     * 验签 + 类型校验；失败返回 null（**不抛异常**：调用方统一按 401/2001 处置，
     * 且不区分失败原因以不泄露 token 是否存在，design D5）。
     */
    private Map<String, Object> verifyOrNull(String token) {
        if (token == null || token.isBlank()) {
            return null;
        }
        Map<String, Object> claims;
        try {
            claims = jwtCodec.verify(token, secret);
        } catch (AuthException e) {
            return null;
        }
        // 短 token 与 refresh 同算法同密钥：必须靠 typ 拒绝把短 token 当 refresh 用
        return TYPE_REFRESH.equals(stringClaim(claims, CLAIM_TYPE)) ? claims : null;
    }

    private String sign(long accountId, String role, boolean mfa, String familyId, String jti) {
        Map<String, Object> claims = new java.util.LinkedHashMap<>();
        claims.put("sub", String.valueOf(accountId));
        claims.put("role", role == null ? "CONSUMER" : role);
        claims.put("mfa", mfa);
        claims.put(CLAIM_FAMILY, familyId);
        claims.put("jti", jti);
        claims.put(CLAIM_TYPE, TYPE_REFRESH);
        return jwtCodec.sign(claims, secret, refreshTtlSeconds);
    }

    private static String stringClaim(Map<String, Object> claims, String key) {
        Object value = claims.get(key);
        return value instanceof String s && !s.isBlank() ? s : null;
    }

    private static String newJti() {
        return "rf_" + java.util.UUID.randomUUID().toString().replace("-", "");
    }

    /** 便于审计/排查的时间戳（不参与判定语义）。 */
    public Instant now() {
        return Instant.ofEpochMilli(clockMillis.getAsLong());
    }
}
