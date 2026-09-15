package com.msz.acc.config;

import com.msz.acc.AccApplication;
import com.msz.acc.domain.model.Account;
import com.msz.acc.repository.AccountMapper;
import com.msz.acc.repository.DaoSupport;
import com.msz.acc.testsupport.EmbeddedMariaDb;
import org.apache.ibatis.session.SqlSession;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.web.context.WebServerApplicationContext;
import org.springframework.context.ConfigurableApplicationContext;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Primary;

import javax.sql.DataSource;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.time.Duration;
import java.time.Instant;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 真实库装配层回归测试（2026-09-15 真机联调缺陷防线）。
 *
 * <p>背景：控制器测试全部 mock Mapper、DAO 测试直接用自动提交会话，导致
 * {@code AccConfiguration} 的**会话语义**从未被真实库验证过，真实库下暴露两个缺陷：</p>
 * <ul>
 *   <li><b>写不落库</b>：会话 {@code autoCommit=false} 且永不提交——{@code POST /acc/account/close}
 *       返回 200 但 {@code closed_at} 仍为 NULL；</li>
 *   <li><b>读陈旧</b>：长事务快照（REPEATABLE READ）——外部已提交的 {@code wallet_status} 变更查不到。</li>
 * </ul>
 *
 * <p>本测试以「真实库 + 真实 Web 容器 + 真实 HTTP」装配 ACC，从**应用外部视角**核验读写语义：
 * 用例 1 防「读陈旧」回归，用例 2 防「写不落库」回归。</p>
 */
class RealDbAssemblyTest {

    private static final long ACCOUNT_ID = 77001L;
    private static final Duration TIMEOUT = Duration.ofSeconds(10);

    private static EmbeddedMariaDb db;
    private static ConfigurableApplicationContext context;
    private static HttpClient http;
    private static String baseUrl;

    /**
     * 真实 DataSource 覆盖 M1 占位实现（{@code @Primary} 优先注入 SqlSessionFactory）。
     *
     * <p>本类位于 {@code com.msz.acc} 扫描路径下，故加条件开关：仅本测试启动的应用生效，
     * 不影响其它 {@code @SpringBootTest} 用例（它们不设 {@code acc.test.realdb}）。</p>
     */
    @Configuration
    @ConditionalOnProperty(name = "acc.test.realdb", havingValue = "true")
    public static class RealDbConfig {

        @Bean
        @Primary
        public DataSource realDataSource() {
            return db.dataSource();
        }
    }

    @BeforeAll
    static void start() throws Exception {
        db = EmbeddedMariaDb.start();
        seedAccount();

        SpringApplication app = new SpringApplication(AccApplication.class, RealDbConfig.class);
        app.setDefaultProperties(java.util.Map.of("server.port", "0", "acc.test.realdb", "true"));
        context = app.run();
        int port = ((WebServerApplicationContext) context).getWebServer().getPort();
        baseUrl = "http://127.0.0.1:" + port;
        http = HttpClient.newBuilder().connectTimeout(TIMEOUT).build();
    }

    @AfterAll
    static void stop() {
        if (context != null) {
            context.close();
        }
    }

    @Test
    @DisplayName("真实库读路径：外部已提交的变更必须立即可见（防「读陈旧」回归）")
    void readsCommittedChangesFromOtherConnections() throws Exception {
        assertThat(get("/acc/me")).contains("\"walletStatus\":\"ACTIVE\"");

        // 应用外部连接提交变更（模拟运营侧/其它服务写库）
        try (Connection c = db.openExternalConnection();
             PreparedStatement ps = c.prepareStatement(
                     "UPDATE account SET wallet_status = 'FROZEN' WHERE account_id = ?")) {
            ps.setLong(1, ACCOUNT_ID);
            ps.executeUpdate();
        }

        assertThat(get("/acc/me"))
                .as("长驻未提交会话会造成 REPEATABLE READ 快照陈旧（2026-09-15 真机联调缺陷）")
                .contains("\"walletStatus\":\"FROZEN\"");
    }

    @Test
    @DisplayName("真实库写路径：接口返回 200 后变更必须已落库（防「写不落库」回归）")
    void persistsWritesAfterSuccessfulResponse() throws Exception {
        HttpResponse<String> response = post("/acc/account/close", "{\"reason\":\"real-db-assembly-test\"}");
        assertThat(response.statusCode()).isEqualTo(200);

        try (Connection c = db.openExternalConnection();
             PreparedStatement ps = c.prepareStatement(
                     "SELECT closed_at, close_reason FROM account WHERE account_id = ?")) {
            ps.setLong(1, ACCOUNT_ID);
            try (ResultSet rs = ps.executeQuery()) {
                assertThat(rs.next()).isTrue();
                assertThat(rs.getTimestamp("closed_at"))
                        .as("会话未提交会造成「接口报成功但数据丢失」（2026-09-15 真机联调缺陷）")
                        .isNotNull();
                assertThat(rs.getString("close_reason")).isEqualTo("real-db-assembly-test");
            }
        }
    }

    // ---------- 支撑 ----------

    /** 灌入夹具账户：走 ACC 自身 DaoSupport + AccountMapper（真实 AES-GCM 加密落库，自动提交）。 */
    private static void seedAccount() {
        try (SqlSession session = new DaoSupport().factory(db.dataSource()).openSession(true)) {
            Account account = new Account();
            account.setAccountId(ACCOUNT_ID);
            account.setMobile("13900139000");
            account.setRole("CONSUMER");
            account.setRealNameStatus("REALNAMED");
            account.setWalletStatus("ACTIVE");
            account.setRealName("李四");
            account.setIdNo("110101199001011234");
            account.setMobileHash("real-db-assembly-" + ACCOUNT_ID);
            account.setCreatedAt(Instant.parse("2026-01-01T00:00:00Z"));
            session.getMapper(AccountMapper.class).insert(account);
        }
    }

    private static String get(String path) throws Exception {
        HttpResponse<String> response = http.send(
                HttpRequest.newBuilder(URI.create(baseUrl + path))
                        .timeout(TIMEOUT)
                        .header("X-User-Id", String.valueOf(ACCOUNT_ID))
                        .header("X-User-Role", "CONSUMER")
                        .header("X-User-Mfa", "true")
                        .header("X-User-Jti", "jti-" + ACCOUNT_ID)
                        .GET()
                        .build(),
                HttpResponse.BodyHandlers.ofString());
        assertThat(response.statusCode()).as("GET %s 应 200", path).isEqualTo(200);
        return response.body();
    }

    private static HttpResponse<String> post(String path, String body) throws Exception {
        return http.send(HttpRequest.newBuilder(URI.create(baseUrl + path))
                        .timeout(TIMEOUT)
                        .header("Content-Type", "application/json")
                        .header("X-User-Id", String.valueOf(ACCOUNT_ID))
                        .header("X-User-Role", "CONSUMER")
                        .header("X-User-Mfa", "true")
                        .header("X-User-Jti", "jti-" + ACCOUNT_ID)
                        .POST(HttpRequest.BodyPublishers.ofString(body))
                        .build(),
                HttpResponse.BodyHandlers.ofString());
    }
}
