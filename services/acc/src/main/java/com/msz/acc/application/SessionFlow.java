package com.msz.acc.application;

import com.msz.acc.application.port.CaptchaPort;
import com.msz.acc.application.port.SessionStore;
import com.msz.acc.application.support.HmacFingerprint;
import com.msz.acc.domain.model.Account;
import com.msz.acc.domain.support.AccBusinessException;
import com.msz.acc.infrastructure.auth.AuthException;
import com.msz.acc.infrastructure.auth.session.AccessJti;
import com.msz.acc.infrastructure.auth.session.AccessTokenIssuer;
import com.msz.acc.infrastructure.auth.session.ConsumeResult;
import com.msz.acc.infrastructure.auth.session.FamilyRecord;
import com.msz.acc.infrastructure.auth.session.RefreshTokenStore;
import com.msz.acc.repository.AccountMapper;
import org.slf4j.Logger;

import java.util.List;
import java.util.regex.Pattern;

/**
 * 会话凭据生命周期流程（design D1/D2/D5，spec `acc-session` 全部 7 条 Requirement 的落地处）：
 * 登录签发 → 换发轮换 → 重用检测整族吊销 → 登出吊销。
 *
 * <p><b>错误口径（design D5）</b>：登录因子失败、refresh 失效/过期/重放、登出无有效凭据
 * **统一抛 {@link AuthException}**（→ HTTP 401 + 2001），不区分失败原因（避免泄露
 * 「该 token 是否存在/是否被重用」）；重放检测的可观测性由**审计日志**承载，不进响应码。</p>
 *
 * <p><b>日志脱敏</b>：本类绝不打印 token 原文与 Cookie 值，只打印会话族 ID / 账户 ID /
 * jti / 剩余 TTL 这类可排障但不构成凭据的信息。</p>
 *
 * <p><b>事务边界</b>：不做任何数据库显式事务——账户查询走事务感知 Mapper 代理，天然落在请求级
 * 事务内（`fix-acc-transaction-boundary` 已收敛）；会话状态在 Redis，不参与数据库事务。</p>
 */
public final class SessionFlow implements SessionOperations {

    /** 审计日志事件名：refresh 重放（泄露信号）→ 整族吊销。 */
    public static final String AUDIT_REFRESH_REPLAY = "SESSION_REFRESH_REPLAY";

    /** 审计日志事件名：登出吊销。 */
    public static final String AUDIT_LOGOUT = "SESSION_LOGOUT";

    private static final Pattern MOBILE_PATTERN = Pattern.compile("^1[3-9]\\d{9}$");

    /** 账户冻结/停用状态（account.wallet_status 口径）。 */
    private static final String WALLET_STATUS_FROZEN = "FROZEN";

    private final SessionStore store;
    private final AccountMapper accountMapper;
    private final CaptchaPort captchaPort;
    private final HmacFingerprint hmacFingerprint;
    private final AccessTokenIssuer accessTokenIssuer;
    private final RefreshTokenStore refreshTokenStore;
    private final Logger auditLog;

    public SessionFlow(SessionStore store, AccountMapper accountMapper, CaptchaPort captchaPort,
                       HmacFingerprint hmacFingerprint, AccessTokenIssuer accessTokenIssuer,
                       RefreshTokenStore refreshTokenStore, Logger auditLog) {
        this.store = store;
        this.accountMapper = accountMapper;
        this.captchaPort = captchaPort;
        this.hmacFingerprint = hmacFingerprint;
        this.accessTokenIssuer = accessTokenIssuer;
        this.refreshTokenStore = refreshTokenStore;
        this.auditLog = auditLog;
    }

    /**
     * 登录（spec「Login issues both tokens」）：手机号 + 人机验证一次性票据 → 建会话族 → 签发双 token。
     *
     * <p>顺序刻意是「先消费票据、再查账户」：票据是一次性的，无论后续账户校验结果如何都必须消耗，
     * 否则同一票据可被反复试探账户是否存在（爆破面）。</p>
     */
    public LoginOutcome login(String mobile, String captchaToken) {
        if (mobile == null || !MOBILE_PATTERN.matcher(mobile).matches()) {
            throw new AuthException("手机号格式非法");
        }
        try {
            captchaPort.consumeToken(captchaToken);
        } catch (AccBusinessException e) {
            // 票据无效/已消费：对外统一 2001（不暴露「票据状态」这一可枚举信号）
            throw new AuthException("人机验证票据无效", e);
        }

        Account account = accountMapper.selectByMobileHash(hmacFingerprint.hmacSha256Hex(mobile));
        if (account == null) {
            throw new AuthException("账户不存在");
        }
        if (account.getClosedAt() != null) {
            throw new AuthException("账户已注销");
        }
        if (WALLET_STATUS_FROZEN.equalsIgnoreCase(account.getWalletStatus())) {
            throw new AuthException("账户已冻结");
        }

        // 存储不可用会在建族时抛 SessionStoreUnavailableException → 503，且此刻尚未签发任何 token
        String refreshToken = refreshTokenStore.issueNewFamily(account.getAccountId(), account.getRole(), false);
        String familyId = refreshTokenStore.familyIdOf(refreshToken);
        return new LoginOutcome(account.getAccountId(), account.getRole(), false, familyId,
                issueAccess(account.getAccountId(), account.getRole(), false, familyId), refreshToken);
    }

    /**
     * 换发（spec「Refresh tokens are single-use and rotate」/「Session family and replay detection」）。
     *
     * <p>判定分支：</p>
     * <ul>
     *   <li>{@code Rotated}：正常轮换——消费旧 refresh，签发新 refresh + 新短 token</li>
     *   <li>{@code ConcurrentRetry}：宽限窗口内的并发重试——**不判泄露**，复用当前 refresh、
     *       签发新短 token（多标签页同时换发不会误伤）</li>
     *   <li>{@code Replay}：重放泄露信号——**吊销整族**（含族内未过期短 token 的 `jti`）
     *       并记安全审计事件，随后仍按 401/2001 拒绝</li>
     *   <li>{@code Invalid}/{@code RetryableRace}：统一 401/2001，**不产生任何副作用**</li>
     * </ul>
     */
    public RefreshOutcome refresh(String refreshToken) {
        ConsumeResult result = refreshTokenStore.consume(refreshToken);
        if (result instanceof ConsumeResult.Rotated rotated) {
            String newRefresh = refreshTokenStore.rotate(rotated.family(), consumedJtiOf(refreshToken));
            return issueFromFamily(rotated.family(), newRefresh);
        }
        if (result instanceof ConsumeResult.ConcurrentRetry retry) {
            // 并发重试：返回当前有效 token 对（新短 token + 同一 refresh），不产生新 refresh jti
            return issueFromFamily(retry.family(), refreshTokenStore.current(retry.family()));
        }
        if (result instanceof ConsumeResult.Replay replay) {
            revokeFamily(replay.family(), AUDIT_REFRESH_REPLAY, null, 0L);
            throw new AuthException("refresh 已失效");
        }
        throw new AuthException("refresh 无效或已过期");
    }

    /**
     * 登出（spec「Logout revokes the current session」，design Risks：两种凭据任一有效即可）。
     *
     * <p>① 有有效短 token：按其 {@code jti} + 会话族吊销；② 无短 token 但 Cookie 中有有效 refresh：
     * 按该族吊销（**控制器负责先做 Origin/Referer 校验**，与换发同口径）。幂等：族不存在或已吊销
     * 时仍返回成功（`revoked=false`）。</p>
     */
    public LogoutOutcome logout(String accessJti, String accessFamilyId, long accessRemainingSeconds,
                                String refreshToken) {
        if (accessJti != null && !accessJti.isBlank() && accessFamilyId != null && !accessFamilyId.isBlank()) {
            FamilyRecord family = store.find(accessFamilyId);
            if (family == null) {
                // 族已到期/被清理：仍把该短 token 自己写进吊销名单（登出语义不因族缺失而失效）
                store.revoke(List.of(new AccessJti(accessJti, Math.max(accessRemainingSeconds, 1L))));
                return new LogoutOutcome(false);
            }
            boolean alreadyRevoked = family.revoked();
            revokeFamily(family, AUDIT_LOGOUT, accessJti, accessRemainingSeconds);
            return new LogoutOutcome(!alreadyRevoked);
        }

        String familyId = refreshTokenStore.familyIdOf(refreshToken);
        if (familyId == null) {
            throw new AuthException("缺少有效会话凭据");
        }
        FamilyRecord family = store.find(familyId);
        if (family == null) {
            throw new AuthException("会话已失效");
        }
        boolean alreadyRevoked = family.revoked();
        revokeFamily(family, AUDIT_LOGOUT, null, 0L);
        return new LogoutOutcome(!alreadyRevoked);
    }

    private RefreshOutcome issueFromFamily(FamilyRecord family, String refreshToken) {
        String accessToken = issueAccess(family.accountId(), family.role(), family.mfa(), family.familyId());
        return new RefreshOutcome(family.accountId(), family.role(), family.mfa(), family.familyId(),
                accessToken, refreshToken);
    }

    /** 先绑定 jti 到族、再签发（绑定失败即不签发，避免产生族不知道、因而无法吊销的短 token）。 */
    private String issueAccess(long accountId, String role, boolean mfa, String familyId) {
        AccessTokenIssuer.Issued issued = accessTokenIssuer.issue(accountId, role, mfa, familyId);
        refreshTokenStore.bindAccessJti(familyId, issued.jti());
        return issued.token();
    }

    /**
     * 整族吊销（登出 / 重用检测共用）：逐条写网关可读的 `revoked:jti:{jti}`（族内全部未过期短 token，
     * 含当前请求携带的那一个）+ 标记族 REVOKED（**保留记录**，使后续重放被识别为「已吊销族」
     * 而非「未知 token」）+ 记安全审计事件。
     */
    private void revokeFamily(FamilyRecord family, String event, String requestAccessJti,
                              long requestAccessRemainingSeconds) {
        List<AccessJti> jtis = refreshTokenStore.liveAccessJtis(family, requestAccessJti,
                requestAccessRemainingSeconds);
        store.revoke(jtis);
        store.markRevoked(family.familyId());
        auditLog.warn("{} event=session_revoked familyId={} accountId={} refreshJti={} revokedAccessJtis={}",
                event, family.familyId(), family.accountId(), family.currentJti(), jtis.size());
    }

    private String consumedJtiOf(String refreshToken) {
        String jti = refreshTokenStore.jtiOf(refreshToken);
        if (jti == null) {
            throw new AuthException("refresh 无效");
        }
        return jti;
    }

    /** 登录结果（token 原文只进响应体 / Set-Cookie，禁止进日志）。 */
    public record LoginOutcome(long accountId, String role, boolean mfa, String familyId, String accessToken,
                               String refreshToken) {
    }

    /** 换发结果。 */
    public record RefreshOutcome(long accountId, String role, boolean mfa, String familyId, String accessToken,
                                 String refreshToken) {
    }

    /** 登出结果：{@code revoked=false} 表示本次调用未实际改变状态（已登出/族不存在），仍视为成功。 */
    public record LogoutOutcome(boolean revoked) {
    }
}
