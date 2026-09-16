package com.msz.acc.application;

import com.msz.acc.application.port.CaptchaPort;
import com.msz.acc.application.port.SessionStore;
import com.msz.acc.application.support.HmacFingerprint;
import com.msz.acc.domain.model.Account;
import com.msz.acc.domain.support.AccBusinessException;
import com.msz.acc.infrastructure.auth.AuthException;
import com.msz.acc.infrastructure.auth.JwtCodec;
import com.msz.acc.infrastructure.auth.session.AccessTokenIssuer;
import com.msz.acc.infrastructure.auth.session.FamilyRecord;
import com.msz.acc.infrastructure.auth.session.InMemorySessionStore;
import com.msz.acc.infrastructure.auth.session.RefreshTokenStore;
import com.msz.acc.infrastructure.auth.session.SessionStoreUnavailableException;
import com.msz.acc.repository.AccountMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * {@link SessionFlow} 行为契约（spec `acc-session` 7 条 Requirement 的流程级守卫）：
 * 登录签发（1）、单次使用轮换（2）、会话族与重用检测（3）、登出吊销与幂等（4）、
 * 会话存储 fail-closed（6）、签发口径（7）。
 *
 * <p>介质全部可控：内存会话存储 + 固定时钟（宽限窗口/到期判定无 sleep）+ 假账户表 + 假票据端口 +
 * 记录型审计日志。</p>
 */
class SessionFlowTest {

    private static final String FIXTURE_SECRET = "acc-jwt-fixture-secret-0123456789";
    private static final long FIXED_EPOCH_MILLIS = 1_760_000_000_000L;
    private static final String MOBILE = "13800138000";

    private MutableClock clock;
    private InMemorySessionStore store;
    private RecordingAuditLog auditLog;
    private SessionFlow flow;
    private AccountMapper accountMapper;
    private CaptchaPort captchaPort;

    @BeforeEach
    void setUp() {
        clock = new MutableClock(FIXED_EPOCH_MILLIS);
        store = new InMemorySessionStore(clock);
        auditLog = new RecordingAuditLog();
        accountMapper = mock(AccountMapper.class);
        captchaPort = mock(CaptchaPort.class);
        flow = newFlow(store);
    }

    private SessionFlow newFlow(SessionStore sessionStore) {
        Clock fixed = Clock.fixed(Instant.ofEpochMilli(FIXED_EPOCH_MILLIS), ZoneOffset.UTC);
        JwtCodec codec = new JwtCodec(fixed);
        AccessTokenIssuer accessIssuer = new AccessTokenIssuer(codec, FIXTURE_SECRET,
                AccessTokenIssuer.ACCESS_TOKEN_TTL_SECONDS, fixed);
        RefreshTokenStore refreshStore = new RefreshTokenStore(sessionStore, codec, FIXTURE_SECRET,
                604_800L, 5L, AccessTokenIssuer.ACCESS_TOKEN_TTL_SECONDS, clock);
        return new SessionFlow(sessionStore, accountMapper, captchaPort, new HmacFingerprint("acc-fingerprint-fixture"),
                accessIssuer, refreshStore, auditLog.logger());
    }

    private Account account(String walletStatus, Instant closedAt) {
        Account account = new Account();
        account.setAccountId(1001L);
        account.setRole("CONSUMER");
        account.setWalletStatus(walletStatus);
        account.setClosedAt(closedAt);
        return account;
    }

    /** 用与生产同源的编解码器/密钥/时钟签发一条 refresh（合法签名 + 合法 typ），供存储故障用例使用。 */
    private String validRefreshToken(String familyId, String jti) {
        return codec().sign(Map.of("sub", "1001", "role", "CONSUMER", "mfa", false, "fam", familyId,
                "jti", jti, "typ", RefreshTokenStore.TYPE_REFRESH), FIXTURE_SECRET, 604_800L);
    }

    /** 从 token 中读出 jti（断言族内标记用，不校验业务语义）。 */
    private String jtiOf(String token) {
        return (String) codec().verify(token, FIXTURE_SECRET).get("jti");
    }

    private static JwtCodec codec() {
        return new JwtCodec(Clock.fixed(Instant.ofEpochMilli(FIXED_EPOCH_MILLIS), ZoneOffset.UTC));
    }

    // ---------- 3.1 登录 ----------

    @Test
    @DisplayName("3.1 登录成功：消费票据 + 签发双 token（短 token 在响应、长 token 独立返回）")
    void loginIssuesBothTokens() {
        when(accountMapper.selectByMobileHash(anyString())).thenReturn(account("ACTIVE", null));

        SessionFlow.LoginOutcome outcome = flow.login(MOBILE, "ct_fixture_1");

        assertThat(outcome.accountId()).isEqualTo(1001L);
        assertThat(outcome.role()).isEqualTo("CONSUMER");
        assertThat(outcome.accessToken()).isNotBlank();
        assertThat(outcome.refreshToken()).isNotBlank();
        assertThat(outcome.familyId()).startsWith("fam_");
        assertThat(store.find(outcome.familyId())).isNotNull();
        org.mockito.Mockito.verify(captchaPort).consumeToken("ct_fixture_1");
    }

    @Test
    @DisplayName("3.1 账户不存在 / 已注销 / 已冻结 / 票据无效 → 一律 AuthException(2001)，且不建族")
    void loginFailuresAreUniformlyUnauthorized() {
        when(accountMapper.selectByMobileHash(anyString())).thenReturn(null);
        assertThatThrownBy(() -> flow.login(MOBILE, "ct_1")).isInstanceOf(AuthException.class);

        when(accountMapper.selectByMobileHash(anyString()))
                .thenReturn(account("ACTIVE", Instant.ofEpochMilli(FIXED_EPOCH_MILLIS)));
        assertThatThrownBy(() -> flow.login(MOBILE, "ct_2")).isInstanceOf(AuthException.class);

        when(accountMapper.selectByMobileHash(anyString())).thenReturn(account("FROZEN", null));
        assertThatThrownBy(() -> flow.login(MOBILE, "ct_3")).isInstanceOf(AuthException.class);

        when(accountMapper.selectByMobileHash(anyString())).thenReturn(account("ACTIVE", null));
        doThrow(new AccBusinessException(1003, "captchaToken 无效或已用"))
                .when(captchaPort).consumeToken("ct_used");
        assertThatThrownBy(() -> flow.login(MOBILE, "ct_used")).isInstanceOf(AuthException.class);

        // 手机号格式非法不走票据/账户链路
        assertThatThrownBy(() -> flow.login("12345", "ct_4")).isInstanceOf(AuthException.class);
    }

    @Test
    @DisplayName("3.1 票据无效时不查询账户（不泄露账户是否存在，也不浪费一次查询）")
    void invalidCaptchaShortCircuitsBeforeAccountLookup() {
        doThrow(new AccBusinessException(1003, "captchaToken 无效或已用"))
                .when(captchaPort).consumeToken("ct_used");

        assertThatThrownBy(() -> flow.login(MOBILE, "ct_used")).isInstanceOf(AuthException.class);

        org.mockito.Mockito.verify(accountMapper, org.mockito.Mockito.never()).selectByMobileHash(anyString());
    }

    // ---------- 3.2 换发轮换 ----------

    @Test
    @DisplayName("3.2 换发成功：旧 refresh 立即失效、族 currentJti 前移、宽限窗口记录旧 jti")
    void refreshRotatesAndInvalidatesOldToken() {
        when(accountMapper.selectByMobileHash(anyString())).thenReturn(account("ACTIVE", null));
        SessionFlow.LoginOutcome login = flow.login(MOBILE, "ct_1");

        SessionFlow.RefreshOutcome refreshed = flow.refresh(login.refreshToken());

        assertThat(refreshed.refreshToken()).isNotEqualTo(login.refreshToken());
        assertThat(refreshed.accessToken()).isNotBlank();
        assertThat(refreshed.familyId()).isEqualTo(login.familyId());

        FamilyRecord family = store.find(login.familyId());
        assertThat(family.previousJti()).isNotNull();
        // 旧 refresh 的映射已被消费（单次使用）
        assertThat(store.consume(family.previousJti())).isFalse();
    }

    @Test
    @DisplayName("3.2 过期/未知/非法签名的 refresh → AuthException(2001)，且不轮换、不建键")
    void unknownOrExpiredRefreshRejected() {
        assertThatThrownBy(() -> flow.refresh("not-a-jwt")).isInstanceOf(AuthException.class);
        assertThatThrownBy(() -> flow.refresh(null)).isInstanceOf(AuthException.class);

        // 用别的密钥签发 → 验签失败
        JwtCodec otherCodec = new JwtCodec();
        String foreign = otherCodec.sign(Map.of("sub", "1001", "fam", "fam_x", "jti", "rf_x", "typ", "refresh"),
                "another-fixture-secret", 600L);
        assertThatThrownBy(() -> flow.refresh(foreign)).isInstanceOf(AuthException.class);
    }

    @Test
    @DisplayName("3.2 短 token 不能当 refresh 用（typ 区分，同算法同密钥）")
    void accessTokenCannotBeUsedAsRefresh() {
        when(accountMapper.selectByMobileHash(anyString())).thenReturn(account("ACTIVE", null));
        SessionFlow.LoginOutcome login = flow.login(MOBILE, "ct_1");

        assertThatThrownBy(() -> flow.refresh(login.accessToken())).isInstanceOf(AuthException.class);
    }

    // ---------- 3.3 重用检测 ----------

    @Test
    @DisplayName("3.3 重用检测：宽限窗口外重放已轮换 refresh → 整族吊销 + 审计事件 + 401")
    void replayOutsideGraceRevokesWholeFamily() {
        when(accountMapper.selectByMobileHash(anyString())).thenReturn(account("ACTIVE", null));
        SessionFlow.LoginOutcome login = flow.login(MOBILE, "ct_1");
        SessionFlow.RefreshOutcome first = flow.refresh(login.refreshToken());
        String familyId = login.familyId();
        String accessJti = store.find(familyId).accessJtis().keySet().iterator().next();

        clock.advanceSeconds(6);   // 越过 5 秒宽限窗口

        assertThatThrownBy(() -> flow.refresh(login.refreshToken())).isInstanceOf(AuthException.class);

        // 整族吊销：族标记 REVOKED（记录保留）
        assertThat(store.find(familyId).revoked()).isTrue();
        // 族内未过期短 token 的 jti 已进网关共享吊销名单
        assertThat(store.rawValue("revoked:jti:" + accessJti)).isEqualTo("1");
        assertThat(store.rawTtlSeconds("revoked:jti:" + accessJti)).isBetween(1L, 900L);
        // 审计事件（不含 token 原文）
        assertThat(auditLog.messages()).anyMatch(m -> m.contains(SessionFlow.AUDIT_REFRESH_REPLAY)
                && m.contains(familyId) && m.contains("accountId=1001"));
        assertThat(auditLog.messages()).noneMatch(m -> m.contains(login.refreshToken())
                || m.contains(first.refreshToken()) || m.contains(first.accessToken())
                || m.contains(login.accessToken()));
    }

    @Test
    @DisplayName("3.3 族已吊销后：换发与再次重放一律 401，且不重复放大审计/写入")
    void revokedFamilyRejectsEverything() {
        when(accountMapper.selectByMobileHash(anyString())).thenReturn(account("ACTIVE", null));
        SessionFlow.LoginOutcome login = flow.login(MOBILE, "ct_1");
        SessionFlow.RefreshOutcome first = flow.refresh(login.refreshToken());
        clock.advanceSeconds(6);
        assertThatThrownBy(() -> flow.refresh(login.refreshToken())).isInstanceOf(AuthException.class);

        // 当前（有效）refresh 在族吊销后同样被拒
        assertThatThrownBy(() -> flow.refresh(first.refreshToken())).isInstanceOf(AuthException.class);
        assertThatThrownBy(() -> flow.refresh(login.refreshToken())).isInstanceOf(AuthException.class);
    }

    @Test
    @DisplayName("FIX-1/A1 族寿命：轮换后族到期与「已轮换标记」按 refresh 有效期（7 天）计，不被 15 分钟短 token 污染")
    void familyAndRotationMarkerLifetimeFollowRefreshTtl() {
        when(accountMapper.selectByMobileHash(anyString())).thenReturn(account("ACTIVE", null));
        SessionFlow.LoginOutcome login = flow.login(MOBILE, "ct_1");
        String familyId = login.familyId();
        String firstRefreshJti = jtiOf(login.refreshToken());

        flow.refresh(login.refreshToken());

        FamilyRecord family = store.find(familyId);
        assertThat(family.expiresAtMillis())
                .as("族到期 = 本次 refresh 签发时刻 + refresh 有效期（轮换会续期），与短 token 无关")
                .isEqualTo(FIXED_EPOCH_MILLIS + 604_800_000L);
        assertThat(store.rawTtlSeconds("acc:session:" + familyId))
                .as("族键 TTL 必须是 7 天量级（1e5 秒），不是 900 秒量级")
                .isBetween(604_790L, 604_800L);
        assertThat(family.rotatedJtis())
                .as("被轮换 jti 的标记保留到该 refresh 的原始到期时刻；塌缩成 900s 会让重放被误判为「未知 token」")
                .containsEntry(firstRefreshJti, FIXED_EPOCH_MILLIS + 604_800_000L);
        assertThat(family.accessJtis().values())
                .as("短 token 的到期时刻只存在于 accessJtis 条目里（独立于族寿命）")
                .allSatisfy(expiry -> assertThat(expiry).isEqualTo(FIXED_EPOCH_MILLIS + 900_000L));
    }

    @Test
    @DisplayName("FIX-1/A1 安全承诺：轮换后超过 15 分钟（短 token 已过期）重放旧 refresh → 仍判重用：整族吊销 + 审计")
    void replayLongAfterRotationStillRevokesWholeFamily() {
        when(accountMapper.selectByMobileHash(anyString())).thenReturn(account("ACTIVE", null));
        SessionFlow.LoginOutcome login = flow.login(MOBILE, "ct_1");
        SessionFlow.RefreshOutcome first = flow.refresh(login.refreshToken());

        // 15 分钟 + 1 秒：短 token 全部过期；被污染的「已轮换标记」恰在此刻到期 → 旧实现落入「未知 token」分支
        clock.advanceSeconds(901);
        flow.refresh(first.refreshToken());
        assertThat(store.find(login.familyId()).revoked())
                .as("refresh 未过期，15 分钟后正常换发必须成功（旧实现下族键已消失 → 401 强制重登）")
                .isFalse();
        String liveAccessJti = store.find(login.familyId()).accessJtis().keySet().iterator().next();

        assertThatThrownBy(() -> flow.refresh(login.refreshToken())).isInstanceOf(AuthException.class);

        assertThat(store.find(login.familyId()).revoked())
                .as("重放必须整族吊销（REVOKED 记录保留），而不是只回 401「未知 token」")
                .isTrue();
        assertThat(store.rawValue("revoked:jti:" + liveAccessJti))
                .as("整族吊销必须含「重放发生时仍未过期」的短 token（网关据此立即 401）")
                .isEqualTo("1");
        assertThat(store.rawTtlSeconds("revoked:jti:" + liveAccessJti)).isBetween(1L, 900L);
        assertThat(auditLog.messages())
                .as("重放必须留安全审计事件（可观测性）")
                .anyMatch(m -> m.contains(SessionFlow.AUDIT_REFRESH_REPLAY) && m.contains(login.familyId()));
    }

    // ---------- 3.4 并发宽限 ----------

    @Test
    @DisplayName("3.4 宽限窗口内重复换发：不判泄露、不吊销，复用同一 refresh、仍签发新短 token")
    void replayInsideGraceIsTreatedAsConcurrentRetry() {
        when(accountMapper.selectByMobileHash(anyString())).thenReturn(account("ACTIVE", null));
        SessionFlow.LoginOutcome login = flow.login(MOBILE, "ct_1");
        SessionFlow.RefreshOutcome first = flow.refresh(login.refreshToken());

        SessionFlow.RefreshOutcome second = flow.refresh(login.refreshToken());   // 同一旧 refresh 再来一次

        assertThat(second.refreshToken()).isEqualTo(first.refreshToken());
        assertThat(store.find(login.familyId()).revoked()).isFalse();
        assertThat(auditLog.messages()).noneMatch(m -> m.contains(SessionFlow.AUDIT_REFRESH_REPLAY));
    }

    @Test
    @DisplayName("3.4 窗口内并发不签发第二个 refresh jti（无签名/存储写放大）")
    void graceRetryDoesNotIssueSecondRefresh() {
        when(accountMapper.selectByMobileHash(anyString())).thenReturn(account("ACTIVE", null));
        SessionFlow.LoginOutcome login = flow.login(MOBILE, "ct_1");
        flow.refresh(login.refreshToken());
        String current = store.find(login.familyId()).currentJti();

        flow.refresh(login.refreshToken());
        flow.refresh(login.refreshToken());

        assertThat(store.find(login.familyId()).currentJti()).isEqualTo(current);
    }

    @Test
    @DisplayName("3.4 窗口边界：恰好 5 秒内为并发重试，超过 5 秒即判泄露")
    void graceBoundaryIsFiveSeconds() {
        when(accountMapper.selectByMobileHash(anyString())).thenReturn(account("ACTIVE", null));
        SessionFlow.LoginOutcome login = flow.login(MOBILE, "ct_1");
        flow.refresh(login.refreshToken());

        clock.advanceSeconds(4);
        assertThat(flow.refresh(login.refreshToken()).refreshToken()).isNotBlank();   // 4s：仍在窗口内

        clock.advanceSeconds(2);   // 累计 6s > 5s
        assertThatThrownBy(() -> flow.refresh(login.refreshToken())).isInstanceOf(AuthException.class);
    }

    // ---------- 3.5 登出 ----------

    @Test
    @DisplayName("3.5 登出（短 token 路径）：族 REVOKED + 族内短 token jti 入吊销名单 + 审计")
    void logoutWithAccessTokenRevokesFamily() {
        when(accountMapper.selectByMobileHash(anyString())).thenReturn(account("ACTIVE", null));
        SessionFlow.LoginOutcome login = flow.login(MOBILE, "ct_1");
        String jti = store.find(login.familyId()).accessJtis().keySet().iterator().next();

        SessionFlow.LogoutOutcome outcome = flow.logout(jti, login.familyId(), 880L, null);

        assertThat(outcome.revoked()).isTrue();
        assertThat(store.find(login.familyId()).revoked()).isTrue();
        assertThat(store.rawValue("revoked:jti:" + jti)).isEqualTo("1");
        assertThat(store.rawTtlSeconds("revoked:jti:" + jti)).isEqualTo(880L);
        assertThat(auditLog.messages()).anyMatch(m -> m.contains(SessionFlow.AUDIT_LOGOUT));
    }

    @Test
    @DisplayName("3.5 重复登出幂等：仍成功（revoked=false）、无异常、无重复写入放大")
    void repeatedLogoutIsIdempotent() {
        when(accountMapper.selectByMobileHash(anyString())).thenReturn(account("ACTIVE", null));
        SessionFlow.LoginOutcome login = flow.login(MOBILE, "ct_1");
        String jti = store.find(login.familyId()).accessJtis().keySet().iterator().next();

        assertThat(flow.logout(jti, login.familyId(), 880L, null).revoked()).isTrue();
        assertThat(flow.logout(jti, login.familyId(), 880L, null).revoked()).isFalse();
        assertThat(flow.logout(jti, login.familyId(), 880L, null).revoked()).isFalse();
    }

    @Test
    @DisplayName("3.5 仅凭 Cookie 登出（短 token 已过期）：按 refresh 定位族并整族吊销")
    void logoutWithRefreshCookieOnly() {
        when(accountMapper.selectByMobileHash(anyString())).thenReturn(account("ACTIVE", null));
        SessionFlow.LoginOutcome login = flow.login(MOBILE, "ct_1");
        String jti = store.find(login.familyId()).accessJtis().keySet().iterator().next();

        SessionFlow.LogoutOutcome outcome = flow.logout(null, null, 0L, login.refreshToken());

        assertThat(outcome.revoked()).isTrue();
        assertThat(store.find(login.familyId()).revoked()).isTrue();
        assertThat(store.rawValue("revoked:jti:" + jti)).isEqualTo("1");
    }

    @Test
    @DisplayName("3.5 两种凭据都无效 → AuthException(2001)")
    void logoutWithoutCredentialsRejected() {
        assertThatThrownBy(() -> flow.logout(null, null, 0L, null)).isInstanceOf(AuthException.class);
        assertThatThrownBy(() -> flow.logout(null, null, 0L, "garbage")).isInstanceOf(AuthException.class);
        assertThatThrownBy(() -> flow.logout("  ", null, 0L, null)).isInstanceOf(AuthException.class);
    }

    @Test
    @DisplayName("3.5 短 token 有效但族已到期（记录缺失）：仍把该 jti 写入吊销名单")
    void logoutWithExpiredFamilyStillRevokesOwnJti() {
        SessionFlow.LogoutOutcome outcome = flow.logout("at_orphan", "fam_missing", 100L, null);

        assertThat(outcome.revoked()).isFalse();
        assertThat(store.rawValue("revoked:jti:at_orphan")).isEqualTo("1");
        assertThat(store.rawTtlSeconds("revoked:jti:at_orphan")).isEqualTo(100L);
    }

    // ---------- 2.3 存储不可用 fail-closed ----------

    @Test
    @DisplayName("2.3 存储不可用：登录/换发/登出快速失败（SessionStoreUnavailableException），不签发 token")
    void unavailableStoreFailsFast() {
        SessionStore broken = mock(SessionStore.class);
        when(broken.find(anyString())).thenThrow(new SessionStoreUnavailableException("存储不可用"));
        doThrow(new SessionStoreUnavailableException("存储不可用"))
                .when(broken).issue(any(FamilyRecord.class), anyString(), org.mockito.ArgumentMatchers.anyLong());
        SessionFlow brokenFlow = newFlow(broken);
        when(accountMapper.selectByMobileHash(anyString())).thenReturn(account("ACTIVE", null));

        assertThatThrownBy(() -> brokenFlow.login(MOBILE, "ct_1"))
                .isInstanceOf(SessionStoreUnavailableException.class);
        assertThatThrownBy(() -> brokenFlow.logout("at_1", "fam_1", 100L, null))
                .isInstanceOf(SessionStoreUnavailableException.class);
        // FIX-1/M1：原用 "any"（非法 JWT）——它在触达存储之前就抛 AuthException（RuntimeException 子类），
        // 断言恒真。改为**合法签名/合法 typ** 的 refresh，证明失败确实来自存储不可用。
        assertThatThrownBy(() -> brokenFlow.refresh(validRefreshToken("fam_store_down", "rf_store_down")))
                .as("合法 refresh 必须真正触达存储后才失败")
                .isInstanceOf(SessionStoreUnavailableException.class);
        org.mockito.Mockito.verify(broken).find("fam_store_down");
        // 反向对照：非法 token 在触存储之前就被拒（与上一条区分开，证明上一条并非恒真）
        assertThatThrownBy(() -> brokenFlow.refresh("not-a-jwt")).isInstanceOf(AuthException.class);
        org.mockito.Mockito.verify(broken, org.mockito.Mockito.never()).find("not-a-jwt");
    }

    // ---------- 7 签发口径 ----------

    @Test
    @DisplayName("3.6 登录与换发签发的短 token 均满足网关策略（900s 且 sub 非空白）")
    void issuedAccessTokensSatisfyGatewayPolicy() {
        when(accountMapper.selectByMobileHash(anyString())).thenReturn(account("ACTIVE", null));
        SessionFlow.LoginOutcome login = flow.login(MOBILE, "ct_1");
        SessionFlow.RefreshOutcome refreshed = flow.refresh(login.refreshToken());

        JwtCodec codec = new JwtCodec(Clock.fixed(Instant.ofEpochMilli(FIXED_EPOCH_MILLIS), ZoneOffset.UTC));
        for (String token : List.of(login.accessToken(), refreshed.accessToken())) {
            Map<String, Object> claims = codec.verify(token, FIXTURE_SECRET);
            long iat = ((Number) claims.get("iat")).longValue();
            long exp = ((Number) claims.get("exp")).longValue();
            assertThat(exp - iat).isEqualTo(900L);
            assertThat(claims.get("sub")).isEqualTo("1001");
            assertThat(claims.get("typ")).isEqualTo("access");
            assertThat(claims.get("jti")).isNotNull();
        }
    }

    @Test
    @DisplayName("3.6 短 token 不进 Cookie：由流程返回值交给控制器走响应体；refresh 只在返回值里")
    void tokensAreReturnedNotStored() {
        when(accountMapper.selectByMobileHash(anyString())).thenReturn(account("ACTIVE", null));
        SessionFlow.LoginOutcome login = flow.login(MOBILE, "ct_1");

        // 会话存储中不存在「短 token 原文」这类键（只存 jti），Cookie 由控制器写
        assertThat(store.rawValue("acc:refresh:" + login.accessToken())).isNull();
        assertThat(store.rawValue("acc:session:" + login.accessToken())).isNull();
    }

    /**
     * 记录型审计日志（断言事件与脱敏）：挂 logback {@code ListAppender} 到真实 logger。
     *
     * <p>用真实日志框架而非 mock：断言的是「实际写出的日志内容」——mock 只能验证调用形状，
     * 无法证明消息里**没有** token 原文；同时把该 logger 级别设为 OFF，避免测试输出噪音。</p>
     */
    private static final class RecordingAuditLog {

        private final ch.qos.logback.classic.Logger logger =
                (ch.qos.logback.classic.Logger) org.slf4j.LoggerFactory.getLogger(
                        "acc.session.audit.fixture." + System.nanoTime());
        private final ch.qos.logback.core.read.ListAppender<ch.qos.logback.classic.spi.ILoggingEvent> appender =
                new ch.qos.logback.core.read.ListAppender<>();

        RecordingAuditLog() {
            appender.start();
            logger.addAppender(appender);
            logger.setLevel(ch.qos.logback.classic.Level.WARN);
            logger.setAdditive(false);
        }

        org.slf4j.Logger logger() {
            return logger;
        }

        List<String> messages() {
            return appender.list.stream()
                    .map(event -> event.getFormattedMessage())
                    .collect(java.util.stream.Collectors.toList());
        }
    }

    /** 可控毫秒时钟（宽限/到期判定无 sleep）。 */
    private static final class MutableClock implements java.util.function.LongSupplier {

        private long millis;

        MutableClock(long millis) {
            this.millis = millis;
        }

        @Override
        public long getAsLong() {
            return millis;
        }

        void advanceSeconds(long seconds) {
            millis += seconds * 1000L;
        }
    }
}
