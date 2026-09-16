package com.msz.acc.config;

import ch.qos.logback.classic.Level;
import ch.qos.logback.classic.spi.ILoggingEvent;
import ch.qos.logback.core.read.ListAppender;
import com.msz.acc.application.port.SessionStore;
import com.msz.acc.controller.SessionCookie;
import com.msz.acc.infrastructure.auth.JwtCodec;
import com.msz.acc.infrastructure.auth.session.AccessTokenIssuer;
import com.msz.acc.infrastructure.auth.session.InMemorySessionStore;
import com.msz.acc.infrastructure.auth.session.RefreshTokenStore;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 会话凭据配置项的「真正生效 + 守门」口径（最终评审修复波 FIX-1/B6、B8）。
 *
 * <p><b>B6（原 M7）</b>：{@code acc.session.access-token-ttl-seconds} 原为**可配却被忽略**的键
 * （永远按常量 900s 签发），运维改小它没有任何效果——误导性配置面。现改为**真正生效**并夹紧到
 * {@code [60, 900]}：下限 60s 防止把短 token 配成「一出即过期」，上限 900s 保持
 * 「ACC 签发值 ≤ 网关上限（15m）+ 容差」不变式（超上限启动 WARN，不改写网关策略）。
 * 同一有效值必须同时驱动**签发**与**族内 jti 绑定**（否则族记录的短 token 到期时刻与实际不一致）。</p>
 *
 * <p><b>B8（原 M8）</b>：{@code acc.session.cookie-secure=false} 无任何守门——生产误配即明文下发
 * 7 天 refresh。不做 fail-fast（会打断本地/演练），改为启动打 WARN 并写明「仅本地/测试；生产必须 true」。</p>
 */
class SessionCredentialConfigTest {

    private static final String FIXTURE_SECRET = "acc-jwt-fixture-secret-0123456789";
    private static final long FIXED_EPOCH_MILLIS = 1_760_000_000_000L;

    private final AccConfiguration configuration = new AccConfiguration();
    private final Clock clock = Clock.fixed(Instant.ofEpochMilli(FIXED_EPOCH_MILLIS), ZoneOffset.UTC);

    private AccProperties propertiesWithAccessTtl(long ttlSeconds) {
        AccProperties properties = new AccProperties();
        properties.setJwtSecret(FIXTURE_SECRET);
        properties.getSession().setAccessTokenTtlSeconds(ttlSeconds);
        return properties;
    }

    @Test
    @DisplayName("B6 配置真正生效：access-token-ttl-seconds=300 → 实际签发 300s（原实现恒按 900s 签发，配置被忽略）")
    void configuredAccessTtlTakesEffect() {
        AccProperties properties = propertiesWithAccessTtl(300L);

        AccessTokenIssuer issuer = configuration.accessTokenIssuer(new JwtCodec(clock), properties, clock);

        assertThat(issuer.ttlSeconds()).isEqualTo(300L);
        AccessTokenIssuer.Issued issued = issuer.issue(1001L, "CONSUMER", false, "fam_1");
        assertThat(issuer.remainingSeconds(FIXED_EPOCH_MILLIS / 1000L)).isEqualTo(300L);
        Map<String, Object> claims = new JwtCodec(clock).verify(issued.token(), FIXTURE_SECRET);
        assertThat(((Number) claims.get("exp")).longValue())
                .isEqualTo(FIXED_EPOCH_MILLIS / 1000L + 300L);
    }

    @Test
    @DisplayName("B6 夹紧下限：access-token-ttl-seconds=10 → 60s（防止短 token 一出即过期）")
    void accessTtlBelowFloorIsClampedUp() {
        AccessTokenIssuer issuer = configuration.accessTokenIssuer(new JwtCodec(clock),
                propertiesWithAccessTtl(10L), clock);

        assertThat(issuer.ttlSeconds()).isEqualTo(60L);
    }

    @Test
    @DisplayName("B6 夹紧上限 + 启动 WARN：access-token-ttl-seconds=5000 → 900s（网关上限不变式）")
    void accessTtlAboveGatewayLimitIsClampedDownAndWarns() {
        List<ILoggingEvent> events = captureConfigurationLogs(() -> {
            AccessTokenIssuer issuer = configuration.accessTokenIssuer(new JwtCodec(clock),
                    propertiesWithAccessTtl(5000L), clock);
            assertThat(issuer.ttlSeconds())
                    .as("超上限必须夹紧到网关上限，绝不签发超长 token")
                    .isEqualTo(AccessTokenIssuer.ACCESS_TOKEN_TTL_SECONDS);
        });

        assertThat(events.stream().filter(event -> event.getLevel() == Level.WARN)
                .map(ILoggingEvent::getFormattedMessage).collect(Collectors.toList()))
                .as("超上限必须启动告警（原实现只在超限时打 error，且对配置值本身无任何效果）")
                .anyMatch(message -> message.contains("access-token-ttl-seconds")
                        && message.contains("5000") && message.contains("900"));
    }

    @Test
    @DisplayName("B6 有效值同时驱动族内绑定：配置 300s 时 bindAccessJti 写入的到期时刻 = now + 300s")
    void effectiveAccessTtlAlsoDrivesFamilyBinding() {
        AccProperties properties = propertiesWithAccessTtl(300L);
        SessionStore store = new InMemorySessionStore(clock::millis);
        RefreshTokenStore refreshStore = configuration.refreshTokenStore(store, new JwtCodec(clock), properties, clock);

        String refreshToken = refreshStore.issueNewFamily(1001L, "CONSUMER", false);
        String familyId = refreshStore.familyIdOf(refreshToken);
        refreshStore.bindAccessJti(familyId, "at-1");

        assertThat(store.find(familyId).accessJtis())
                .as("族记录的短 token 到期时刻必须与实际签发口径同源（否则整族吊销的剩余 TTL 失真）")
                .containsEntry("at-1", FIXED_EPOCH_MILLIS + 300_000L);
    }

    @Test
    @DisplayName("B8 cookie-secure=false 启动 WARN（写明仅本地/测试、生产必须 true），但不下发不带 Secure 以外的行为变化")
    void insecureCookieStartupWarns() {
        List<ILoggingEvent> events = captureConfigurationLogs(() -> {
            AccProperties properties = new AccProperties();
            properties.getSession().setCookieSecure(false);
            SessionCookie cookie = configuration.sessionCookie(properties);

            assertThat(cookie.setCookieValue("v")).doesNotContain("Secure");
        });

        assertThat(events.stream().filter(event -> event.getLevel() == Level.WARN)
                .map(ILoggingEvent::getFormattedMessage).collect(Collectors.toList()))
                .as("误配必须可机器检知（原实现完全静默）")
                .anyMatch(message -> message.contains("cookie-secure") && message.contains("生产必须"));
    }

    @Test
    @DisplayName("B8 未误配（cookie-secure=true）时不打告警，且 Cookie 带 Secure")
    void secureCookieDoesNotWarn() {
        List<ILoggingEvent> events = captureConfigurationLogs(() -> {
            SessionCookie cookie = configuration.sessionCookie(new AccProperties());
            assertThat(cookie.setCookieValue("v")).contains("Secure");
        });

        assertThat(events.stream().filter(event -> event.getLevel() == Level.WARN)
                .map(ILoggingEvent::getFormattedMessage).collect(Collectors.toList()))
                .noneMatch(message -> message.contains("cookie-secure"));
    }

    /** 挂 logback {@code ListAppender} 到真实的 AccConfiguration logger，捕获启动告警。 */
    private static List<ILoggingEvent> captureConfigurationLogs(Runnable action) {
        ch.qos.logback.classic.Logger logger =
                (ch.qos.logback.classic.Logger) org.slf4j.LoggerFactory.getLogger(AccConfiguration.class);
        Level previous = logger.getLevel();
        ListAppender<ILoggingEvent> appender = new ListAppender<>();
        appender.start();
        logger.addAppender(appender);
        logger.setLevel(Level.WARN);
        try {
            action.run();
            return List.copyOf(appender.list);
        } finally {
            logger.setLevel(previous);
            logger.detachAppender(appender);
        }
    }
}
