package com.msz.acc.config;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.github.tomakehurst.wiremock.WireMockServer;
import com.github.tomakehurst.wiremock.client.WireMock;
import com.github.tomakehurst.wiremock.core.WireMockConfiguration;
import com.msz.acc.AccApplication;
import com.msz.acc.domain.model.Account;
import com.msz.acc.domain.model.RealnameRecord;
import com.msz.acc.infrastructure.crypto.HmacSignatureVerifier;
import com.msz.acc.repository.AccountMapper;
import com.msz.acc.repository.DaoSupport;
import com.msz.acc.repository.RealnameRecordMapper;
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
import java.sql.DriverManager;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.Callable;
import java.util.concurrent.CyclicBarrier;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 真实库装配层回归测试（2026-09-15 真机联调缺陷防线 + 请求级事务边界）。
 *
 * <p>背景：控制器测试全部 mock Mapper、DAO 测试直接用自动提交会话，导致
 * {@code AccConfiguration} 的**会话语义**从未被真实库验证过，真实库下暴露两个缺陷：</p>
 * <ul>
 *   <li><b>写不落库</b>：会话 {@code autoCommit=false} 且永不提交——{@code POST /acc/account/close}
 *       返回 200 但 {@code closed_at} 仍为 NULL；</li>
 *   <li><b>读陈旧</b>：长事务快照（REPEATABLE READ）——外部已提交的 {@code wallet_status} 变更查不到。</li>
 * </ul>
 *
 * <p>本测试以「真实库 + 真实 Web 容器 + 真实 HTTP」装配 ACC，从**应用外部视角**核验读写语义与事务边界：
 * 用例 1/2 防既有缺陷回归；用例 3.1~3.8 覆盖 {@code fix-acc-transaction-boundary} 的行为契约
 * （跨表回滚 / 并发隔离 / 提交可见 / 幂等槽位释放 / 读路径契约 / 连接释放 / 并发同 key 竞态 /
 * 未提交写对其它请求不可见）。
 * 失败的注入一律走真实 HTTP 入口与真实库约束（唯一键冲突、通道不可用），不新增测试专用端点；
 * 造数据用的自动提交会话（{@link #seedAccount} / {@link #seedRealnameRecord}）只用于准备夹具，
 * **不作为事务语义证据**（design D10）。</p>
 */
class RealDbAssemblyTest {

    private static final long ACCOUNT_ID = 77001L;
    private static final long CONCURRENT_ACCOUNT_ID = 77002L;
    private static final long COMMIT_VISIBILITY_ACCOUNT_ID = 77003L;
    private static final long UNCOMMITTED_WRITE_ACCOUNT_ID = 77004L;
    private static final long UNKNOWN_ACCOUNT_ID = 77999L;

    private static final Duration TIMEOUT = Duration.ofSeconds(10);
    private static final String INTERNAL_TOKEN = "acc-internal-test-token";
    private static final String CALLBACK_SECRET = "acc-callback-test-secret";
    private static final String ROLE_CONSUMER = "CONSUMER";
    private static final String ROLE_REGULATOR = "REGULATOR";

    /** 账单通道桩的故障注入口径：{@code to=该日期} 的账单请求返回 503（流程在占用幂等槽位后失败）。 */
    private static final String CHANNEL_DOWN_TO = "2044-01-31";
    private static final String RECONCILE_FROM = "2026-01-01";
    private static final String RECONCILE_TO = "2026-01-31";

    private static final ObjectMapper JSON = new ObjectMapper();

    private static EmbeddedMariaDb db;
    private static WireMockServer channelStub;
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
        seedFixtures();

        channelStub = new WireMockServer(WireMockConfiguration.options().dynamicPort());
        channelStub.start();
        stubStatementChannel();

        SpringApplication app = new SpringApplication(AccApplication.class, RealDbConfig.class);
        app.setDefaultProperties(Map.of(
                "server.port", "0",
                "acc.test.realdb", "true",
                "acc.channel.statement-base-url", channelStub.baseUrl()));
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
        if (channelStub != null) {
            channelStub.stop();
        }
    }

    // ---------- 既有防线（2026-09-15 缺陷回归） ----------

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
        HttpResponse<String> response = post("/acc/account/close",
                "{\"reason\":\"real-db-assembly-test\"}", ACCOUNT_ID);
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

    // ---------- 任务组 3：请求级事务边界（真实库 + 真实 HTTP + 外部连接视角） ----------

    @Test
    @DisplayName("3.1 跨表原子性：实名回调建户后回写业务单失败 → 两表均无变化")
    void realnameCallbackRollsBackBothTablesOnFailure() throws Exception {
        long accountsBefore = countRows("account");

        // 失败注入：回写目标 open_id 已被 rz_rollback_2 占用 → UPDATE 触发 uk_open_id 唯一键冲突
        // （建户已成功、回写失败，正是 spec「Account creation and business-record update roll back together」场景）
        HttpResponse<String> response = callback("rz_rollback_1", "openid-dup-1", "张三丰", "130123199001011234");

        assertThat(response.statusCode()).as("回写冲突必须失败（不得静默成功）").isEqualTo(500);
        assertThat(countRows("account"))
                .as("失败请求不得留下已建账户（跨表写入必须原子回滚）")
                .isEqualTo(accountsBefore);

        try (Connection c = db.openExternalConnection();
             PreparedStatement ps = c.prepareStatement(
                     "SELECT account_id, status, open_id FROM realname_record WHERE biz_id = ?")) {
            ps.setString(1, "rz_rollback_1");
            try (ResultSet rs = ps.executeQuery()) {
                assertThat(rs.next()).as("业务单必须仍然存在").isTrue();
                assertThat(rs.getLong("account_id")).as("业务单不得被回填 account_id").isZero();
                assertThat(rs.wasNull()).as("account_id 必须仍为 NULL").isTrue();
                assertThat(rs.getString("status")).as("状态不得被改为 REALNAMED").isEqualTo("REALNAMING");
                assertThat(rs.getString("open_id")).as("open_id 不得被改写").isEqualTo("openid-rollback-1");
            }
        }
    }

    @Test
    @DisplayName("3.2 并发隔离：10 个混合读写请求各自正确，无会话/连接串扰")
    void concurrentRequestsAreIsolated() throws Exception {
        int parallelism = 10;
        CyclicBarrier barrier = new CyclicBarrier(parallelism);
        ExecutorService pool = Executors.newFixedThreadPool(parallelism);
        List<HttpResponse<String>> responses = new ArrayList<>();
        try {
            List<Callable<HttpResponse<String>>> tasks = new ArrayList<>();
            for (int i = 0; i < parallelism; i++) {
                String reason = "concurrent-close-" + i;
                Callable<HttpResponse<String>> task;
                if (i % 2 == 0) {
                    task = () -> {
                        barrier.await(30, TimeUnit.SECONDS);
                        return getRaw("/acc/me", CONCURRENT_ACCOUNT_ID);
                    };
                } else {
                    task = () -> {
                        barrier.await(30, TimeUnit.SECONDS);
                        return post("/acc/account/close", "{\"reason\":\"" + reason + "\"}", CONCURRENT_ACCOUNT_ID);
                    };
                }
                tasks.add(task);
            }
            for (Future<HttpResponse<String>> future : pool.invokeAll(tasks, 60, TimeUnit.SECONDS)) {
                responses.add(future.get());
            }
        } finally {
            pool.shutdownNow();
        }

        assertThat(responses).hasSize(parallelism);
        assertThat(responses).allSatisfy(response -> assertThat(response.statusCode())
                .as("并发请求必须各自成功（共享会话会造成串行化/串扰异常）")
                .isEqualTo(200));
        assertThat(responses).allSatisfy(response -> assertThat(response.body())
                .as("每个请求必须只看到自己的账户（不得串到其它请求的会话）")
                .contains("acc_" + CONCURRENT_ACCOUNT_ID));
    }

    @Test
    @DisplayName("3.3 提交可见性：写请求返回 200 后，外部连接立即读到新值（写后读闭环）")
    void successfulWriteIsCommittedAndExternallyVisible() throws Exception {
        String reason = "commit-visibility-" + System.nanoTime();
        HttpResponse<String> response = post("/acc/account/close",
                "{\"reason\":\"" + reason + "\"}", COMMIT_VISIBILITY_ACCOUNT_ID);
        assertThat(response.statusCode()).isEqualTo(200);

        try (Connection c = db.openExternalConnection();
             PreparedStatement ps = c.prepareStatement(
                     "SELECT closed_at, close_reason FROM account WHERE account_id = ?")) {
            ps.setLong(1, COMMIT_VISIBILITY_ACCOUNT_ID);
            try (ResultSet rs = ps.executeQuery()) {
                assertThat(rs.next()).isTrue();
                assertThat(rs.getString("close_reason"))
                        .as("提交后外部连接必须立即读到本次写入（请求结束即提交）")
                        .isEqualTo(reason);
                assertThat(rs.getTimestamp("closed_at")).isNotNull();
            }
        }
    }

    @Test
    @DisplayName("3.4 幂等槽位随事务释放：失败不留占位、同 key 重试真正执行、成功后回放首次结果")
    void failedRequestReleasesIdempotencyClaim() throws Exception {
        String key = "idem-release-" + System.nanoTime();
        long tasksBefore = countRows("reconcile_task");

        HttpResponse<String> failed = reconcile(key, RECONCILE_FROM, CHANNEL_DOWN_TO);
        assertThat(failed.statusCode()).as("账单通道不可用 → 4002/502").isEqualTo(502);
        assertThat(failed.body()).contains("\"code\":4002");
        assertThat(countIdempotencyClaims(key))
                .as("失败请求必须释放幂等槽位（acc_idempotency_record 不得残留占位）")
                .isZero();
        assertThat(countRows("reconcile_task"))
                .as("失败请求的写入（建任务）必须一并回滚")
                .isEqualTo(tasksBefore);

        HttpResponse<String> retried = reconcile(key, RECONCILE_FROM, RECONCILE_TO);
        assertThat(retried.statusCode()).as("同 key 重试必须真正执行（不得判定为重复）").isEqualTo(200);
        String reconcileId = dataField(retried.body(), "reconcileId");
        assertThat(dataField(retried.body(), "status")).isEqualTo("DONE");
        assertThat(dataField(retried.body(), "diffCount")).isEqualTo("0");
        assertThat(countRows("reconcile_task")).as("重试确实执行并落库").isEqualTo(tasksBefore + 1);
        assertThat(countIdempotencyClaims(key)).as("成功后重新占用槽位").isEqualTo(1);

        HttpResponse<String> replay = reconcile(key, RECONCILE_FROM, RECONCILE_TO);
        assertThat(replay.statusCode()).isEqualTo(200);
        assertThat(dataField(replay.body(), "reconcileId"))
                .as("成功后重复请求必须回放首次结果")
                .isEqualTo(reconcileId);
        assertThat(countRows("reconcile_task"))
                .as("成功后重复请求不得重复执行")
                .isEqualTo(tasksBefore + 1);
    }

    @Test
    @DisplayName("3.5 读路径契约：读不存在的对象仍返回既有业务错误（3006/404），不得变 5xx")
    void readPathsKeepDocumentedBusinessErrors() throws Exception {
        HttpResponse<String> me = getRaw("/acc/me", UNKNOWN_ACCOUNT_ID);
        assertThat(me.statusCode()).as("账户不存在 → 404（既有契约）").isEqualTo(404);
        assertThat(me.body()).contains("\"code\":3006");

        HttpResponse<String> status = getPublic("/acc/realname/status?bizId=rz_not_exists");
        assertThat(status.statusCode()).as("实名业务单不存在 → 404（既有契约）").isEqualTo(404);
        assertThat(status.body()).contains("\"code\":3006");
    }

    @Test
    @DisplayName("3.6 连接释放：连续 12 次失败请求后连接数回落，后续请求仍成功")
    void connectionsAreReleasedAfterRepeatedFailures() throws Exception {
        int baseline = threadsConnected();
        for (int i = 0; i < 12; i++) {
            HttpResponse<String> failed = reconcile("idem-leak-" + i + "-" + System.nanoTime(),
                    RECONCILE_FROM, CHANNEL_DOWN_TO);
            assertThat(failed.statusCode()).isEqualTo(502);
        }

        assertThat(awaitConnectionsReleased(baseline + 2))
                .as("失败请求必须归还连接（不得泄漏；基线连接数 %s）", baseline)
                .isTrue();

        assertThat(get("/acc/me"))
                .as("连续失败之后服务仍可正常响应（未因连接耗尽失败）")
                .contains("acc_" + ACCOUNT_ID);
    }

    @Test
    @DisplayName("3.7 并发同 key 竞态：等待方不拿悬空占位，失败后同 key 重试真正执行")
    void concurrentSameKeyRaceNeverYieldsDanglingClaim() throws Exception {
        String key = "idem-race-" + System.nanoTime();
        long tasksBefore = countRows("reconcile_task");
        CyclicBarrier barrier = new CyclicBarrier(2);
        ExecutorService pool = Executors.newFixedThreadPool(2);
        List<HttpResponse<String>> responses = new ArrayList<>();
        try {
            Callable<HttpResponse<String>> sameKeyRequest = () -> {
                barrier.await(30, TimeUnit.SECONDS);
                return reconcile(key, RECONCILE_FROM, CHANNEL_DOWN_TO);
            };
            for (Future<HttpResponse<String>> future
                    : pool.invokeAll(List.of(sameKeyRequest, sameKeyRequest), 60, TimeUnit.SECONDS)) {
                responses.add(future.get());
            }
        } finally {
            pool.shutdownNow();
        }

        // 观测口径：首个请求抢占槽位后失败回滚；等待方要么阻塞到回滚后自行执行（同样失败），
        // 要么按重复处理——无论哪种时序，都不得把「悬空占位（空 payload）」当作首次结果回放给客户端。
        assertThat(responses).hasSize(2);
        assertThat(responses).allSatisfy(response -> assertThat(response.body())
                .as("不得把悬空占位当作首次结果回放（code=0 即为回放）")
                .doesNotContain("\"code\":0"));
        assertThat(countIdempotencyClaims(key)).as("失败事务不得留下占位").isZero();
        assertThat(countRows("reconcile_task")).as("失败事务不得留下半成品任务").isEqualTo(tasksBefore);

        HttpResponse<String> retried = reconcile(key, RECONCILE_FROM, RECONCILE_TO);
        assertThat(retried.statusCode()).as("失败后同 key 重试必须真正执行").isEqualTo(200);
        assertThat(countRows("reconcile_task")).isEqualTo(tasksBefore + 1);
    }

    /**
     * 3.8 未提交写隔离（spec「Uncommitted work of one request is invisible to another」）：
     * 外部连接显式构造「在途未提交写」，其未提交期间发起一次真实 HTTP 读请求，断言读请求只看到
     * **已提交状态**；随后外部提交，再读一次断言看到新值。
     *
     * <p><b>守卫用例声明</b>：本条为守卫用例，<b>未观测到 RED</b>——当前实现（请求级会话 + 请求级
     * 事务边界）本身已满足该契约，故它不能像 3.1 那样反向验证出旧缺陷。其判别力在于锁定
     * 「未提交写对其它请求不可见」这一隔离语义：若将来出现「多请求共享同一会话/连接」「读请求挂到
     * 外部写事务上」或退回长驻会话导致读路径复用未提交写会话等回归，本条即会变红。</p>
     *
     * <p>观测口径：① 外部连接 {@code setAutoCommit(false)} + {@code UPDATE} 后**不提交**，并在写方
     * 连接上确认该值确为在途（FROZEN），保证「确有未提交写」而非断言空转；② 未提交期间的 HTTP 读必须
     * 返回旧值（ACTIVE，非锁定读不吃未提交版本、也不阻塞）；③ 提交后新请求必须立即返回新值。
     * 收尾把数据改回原值并提交，使用例可重复运行且不影响同类中其它用例（同类用例顺序执行、共享同一嵌入库）。</p>
     */
    @Test
    @DisplayName("3.8 未提交写隔离：外部未提交期间读请求只见已提交值，提交后立即可见")
    void uncommittedExternalWriteStaysInvisibleToConcurrentRead() throws Exception {
        assertThat(meBody(UNCOMMITTED_WRITE_ACCOUNT_ID))
                .as("前置：夹具账户的已提交状态为 ACTIVE")
                .contains("\"accountId\":\"acc_" + UNCOMMITTED_WRITE_ACCOUNT_ID + "\"")
                .contains("\"walletStatus\":\"ACTIVE\"");

        Connection external = db.openExternalConnection();
        try {
            external.setAutoCommit(false);
            updateWalletStatus(external, UNCOMMITTED_WRITE_ACCOUNT_ID, "FROZEN");
            assertThat(walletStatusOf(external, UNCOMMITTED_WRITE_ACCOUNT_ID))
                    .as("写方自身可见未提交值（确认确有在途未提交写，避免断言空转）")
                    .isEqualTo("FROZEN");

            // 未提交期间的真实 HTTP 读请求：必须只看到已提交状态（旧值）
            assertThat(meBody(UNCOMMITTED_WRITE_ACCOUNT_ID))
                    .as("未提交写对其它请求必须不可见：读请求只见已提交状态")
                    .contains("\"walletStatus\":\"ACTIVE\"")
                    .doesNotContain("FROZEN");

            external.commit();

            assertThat(meBody(UNCOMMITTED_WRITE_ACCOUNT_ID))
                    .as("外部提交后，下一次读请求必须立即看到新值")
                    .contains("\"walletStatus\":\"FROZEN\"");
        } finally {
            // 放弃在途写（未提交则回滚；已提交亦为无害空操作，连接关闭时同样隐式回滚）
            if (!external.getAutoCommit()) {
                external.rollback();
            }
            external.close();
        }

        restoreWalletStatusActive(UNCOMMITTED_WRITE_ACCOUNT_ID);
        assertThat(meBody(UNCOMMITTED_WRITE_ACCOUNT_ID))
                .as("收尾后数据恢复为 ACTIVE（用例可重复运行）")
                .contains("\"walletStatus\":\"ACTIVE\"");
    }

    // ---------- 支撑：夹具 ----------

    /** 灌入夹具：四个账户（既有回归 / 并发 / 提交可见 / 未提交写隔离）+ 两张实名业务单（3.1 唯一键冲突注入）。 */
    private static void seedFixtures() {
        seedAccount(ACCOUNT_ID);
        seedAccount(CONCURRENT_ACCOUNT_ID);
        seedAccount(COMMIT_VISIBILITY_ACCOUNT_ID);
        seedAccount(UNCOMMITTED_WRITE_ACCOUNT_ID);
        seedRealnameRecord("rz_rollback_1", "openid-rollback-1");
        seedRealnameRecord("rz_rollback_2", "openid-dup-1");
    }

    /** 灌入夹具账户：走 ACC 自身 DaoSupport + AccountMapper（真实 AES-GCM 加密落库，自动提交）。 */
    private static void seedAccount(long accountId) {
        try (SqlSession session = new DaoSupport().factory(db.dataSource()).openSession(true)) {
            Account account = new Account();
            account.setAccountId(accountId);
            account.setMobile("13900139000");
            account.setRole(ROLE_CONSUMER);
            account.setRealNameStatus("REALNAMED");
            account.setWalletStatus("ACTIVE");
            account.setRealName("李四");
            account.setIdNo("110101199001011234");
            account.setMobileHash("real-db-assembly-" + accountId);
            account.setCreatedAt(Instant.parse("2026-01-01T00:00:00Z"));
            session.getMapper(AccountMapper.class).insert(account);
        }
    }

    /** 灌入实名业务单（REALNAMING）：自动提交会话，仅用于造夹具（不作为事务语义证据）。 */
    private static void seedRealnameRecord(String bizId, String openId) {
        try (SqlSession session = new DaoSupport().factory(db.dataSource()).openSession(true)) {
            RealnameRecord record = new RealnameRecord();
            record.setBizId(bizId);
            record.setChannel("WECHAT");
            record.setOpenId(openId);
            record.setName("张三丰");
            record.setIdNo("130123199001011234");
            record.setStatus("REALNAMING");
            record.setLevel("BASE");
            record.setCreatedAt(Instant.parse("2026-01-01T00:00:00Z"));
            session.getMapper(RealnameRecordMapper.class).insert(record);
        }
    }

    /** 账单通道桩：默认返回空账单（对账成功）；{@code to=CHANNEL_DOWN_TO} 返回 503（模拟通道不可用）。 */
    private static void stubStatementChannel() {
        channelStub.stubFor(WireMock.get(WireMock.urlPathEqualTo("/statements"))
                .withQueryParam("to", WireMock.equalTo(CHANNEL_DOWN_TO))
                .atPriority(1)
                .willReturn(WireMock.aResponse().withStatus(503)));
        channelStub.stubFor(WireMock.get(WireMock.urlPathEqualTo("/statements"))
                .atPriority(10)
                .willReturn(WireMock.okJson("[]")));
    }

    // ---------- 支撑：HTTP ----------

    private static String get(String path) throws Exception {
        HttpResponse<String> response = getRaw(path, ACCOUNT_ID);
        assertThat(response.statusCode()).as("GET %s 应 200", path).isEqualTo(200);
        return response.body();
    }

    /** 指定账户的真实 HTTP 读请求（GET /acc/me，断言 200），返回响应体。 */
    private static String meBody(long accountId) throws Exception {
        HttpResponse<String> response = getRaw("/acc/me", accountId);
        assertThat(response.statusCode()).as("GET /acc/me 应 200").isEqualTo(200);
        return response.body();
    }

    /** 受保护接口读取（不断言状态码，供契约/并发用例自行断言）。 */
    private static HttpResponse<String> getRaw(String path, long accountId) throws Exception {
        return send(identity(accountId, ROLE_CONSUMER).uri(URI.create(baseUrl + path)).GET());
    }

    /** 白名单路径读取（无身份头）。 */
    private static HttpResponse<String> getPublic(String path) throws Exception {
        return send(HttpRequest.newBuilder(URI.create(baseUrl + path)).GET());
    }

    private static HttpResponse<String> post(String path, String body, long accountId) throws Exception {
        return send(identity(accountId, ROLE_CONSUMER)
                .uri(URI.create(baseUrl + path))
                .header("Content-Type", "application/json")
                .POST(HttpRequest.BodyPublishers.ofString(body)));
    }

    /** 监管端对账请求（REGULATOR + Idempotency-Key），失败/成功均由账单通道桩决定。 */
    private static HttpResponse<String> reconcile(String idempotencyKey, String from, String to) throws Exception {
        return send(identity(ACCOUNT_ID, ROLE_REGULATOR)
                .uri(URI.create(baseUrl + "/acc/funds/reconcile"))
                .header("Content-Type", "application/json")
                .header("Idempotency-Key", idempotencyKey)
                .POST(HttpRequest.BodyPublishers.ofString(
                        "{\"from\":\"" + from + "\",\"to\":\"" + to + "\"}")));
    }

    /** 实名回调（内部 Token + HMAC 签名，签名口径与 RealnameCallbackFlow 的规范化 payload 一致）。 */
    private static HttpResponse<String> callback(String bizId, String openId, String name, String idNo)
            throws Exception {
        long timestamp = Instant.now().getEpochSecond();
        String nonce = "nonce-real-db-01";
        String payload = bizId + "|" + openId + "|" + name + "|" + idNo + "|true|" + timestamp + "|" + nonce;
        String sign = new HmacSignatureVerifier(CALLBACK_SECRET).sign(payload);
        String body = "{\"bizId\":\"" + bizId + "\",\"openId\":\"" + openId + "\",\"name\":\"" + name
                + "\",\"idNo\":\"" + idNo + "\",\"pass\":true,\"sign\":\"" + sign + "\",\"timestamp\":"
                + timestamp + ",\"nonce\":\"" + nonce + "\"}";
        return send(HttpRequest.newBuilder(URI.create(baseUrl + "/acc/realname/callback"))
                .header("Content-Type", "application/json")
                .header("X-Internal-Token", INTERNAL_TOKEN)
                .POST(HttpRequest.BodyPublishers.ofString(body)));
    }

    private static HttpRequest.Builder identity(long accountId, String role) {
        return HttpRequest.newBuilder()
                .header("X-User-Id", String.valueOf(accountId))
                .header("X-User-Role", role)
                .header("X-User-Mfa", "true")
                .header("X-User-Jti", "jti-" + accountId);
    }

    private static HttpResponse<String> send(HttpRequest.Builder builder) throws Exception {
        return http.send(builder.timeout(TIMEOUT).build(), HttpResponse.BodyHandlers.ofString());
    }

    // ---------- 支撑：外部连接视角核验 ----------

    /** 外部连接读取单个标量（COUNT 等），用于与应用无关的落库核验。 */
    private static long countRows(String table) throws Exception {
        return scalar("SELECT COUNT(*) FROM " + table);
    }

    private static long countIdempotencyClaims(String idempotencyKey) throws Exception {
        return scalar("SELECT COUNT(*) FROM acc_idempotency_record WHERE idempotency_key = ?", idempotencyKey);
    }

    private static long scalar(String sql, Object... args) throws Exception {
        try (Connection c = db.openExternalConnection();
             PreparedStatement ps = c.prepareStatement(sql)) {
            for (int i = 0; i < args.length; i++) {
                ps.setObject(i + 1, args[i]);
            }
            try (ResultSet rs = ps.executeQuery()) {
                assertThat(rs.next()).isTrue();
                return rs.getLong(1);
            }
        }
    }

    /** 在给定连接上更新钱包状态（是否提交由调用方决定：3.8 用它显式控制事务边界）。 */
    private static void updateWalletStatus(Connection c, long accountId, String status) throws Exception {
        try (PreparedStatement ps = c.prepareStatement(
                "UPDATE account SET wallet_status = ? WHERE account_id = ?")) {
            ps.setString(1, status);
            ps.setLong(2, accountId);
            assertThat(ps.executeUpdate()).as("钱包状态更新必须命中夹具账户").isEqualTo(1);
        }
    }

    /** 在给定连接上读取钱包状态（3.8 用它确认写方自身可见的未提交值）。 */
    private static String walletStatusOf(Connection c, long accountId) throws Exception {
        try (PreparedStatement ps = c.prepareStatement(
                "SELECT wallet_status FROM account WHERE account_id = ?")) {
            ps.setLong(1, accountId);
            try (ResultSet rs = ps.executeQuery()) {
                assertThat(rs.next()).isTrue();
                return rs.getString("wallet_status");
            }
        }
    }

    /** 用独立自动提交连接把夹具账户钱包状态改回 ACTIVE（3.8 收尾，保证用例可重复运行）。 */
    private static void restoreWalletStatusActive(long accountId) throws Exception {
        try (Connection c = db.openExternalConnection()) {
            updateWalletStatus(c, accountId, "ACTIVE");
        }
    }

    /** 取响应 Envelope 的 data 字段（字符串化），避免在用例里写正则。 */
    private static String dataField(String body, String name) throws Exception {
        return JSON.readTree(body).path("data").path(name).asText();
    }

    /** 当前数据库连接线程数（root 视角，全局状态）。 */
    private static int threadsConnected() throws Exception {
        try (Connection c = DriverManager.getConnection(db.url(), "root", "");
             PreparedStatement ps = c.prepareStatement("SHOW STATUS LIKE 'Threads_connected'");
             ResultSet rs = ps.executeQuery()) {
            assertThat(rs.next()).isTrue();
            return rs.getInt(2);
        }
    }

    /** 等待连接数回落到阈值以内（服务端回收线程有毫秒级延迟，故轮询）。 */
    private static boolean awaitConnectionsReleased(int limit) throws Exception {
        long deadline = System.nanoTime() + Duration.ofSeconds(10).toNanos();
        int observed = threadsConnected();
        while (observed > limit && System.nanoTime() < deadline) {
            Thread.sleep(200L);
            observed = threadsConnected();
        }
        return observed <= limit;
    }
}
