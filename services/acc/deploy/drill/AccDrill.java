package drill;

import ch.vorburger.mariadb4j.DB;
import ch.vorburger.mariadb4j.DBConfigurationBuilder;
import com.msz.acc.AccApplication;
import com.msz.acc.config.AccProperties;
import com.msz.acc.domain.model.Account;
import com.msz.acc.infrastructure.auth.JwtCodec;
import com.msz.acc.repository.AccountMapper;
import com.msz.acc.repository.DaoSupport;
import org.apache.ibatis.datasource.unpooled.UnpooledDataSource;
import org.apache.ibatis.session.SqlSession;
import org.flywaydb.core.Flyway;
import org.springframework.boot.SpringApplication;
import org.springframework.context.ConfigurableApplicationContext;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Primary;

import javax.sql.DataSource;
import java.io.File;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.Statement;
import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * ACC 真机联调桩（drill，非生产代码，不参与 Maven 构建）。
 *
 * <p>用途：以**真实进程 + 真实数据库**形态启动 ACC，供网关「双进程联调」（任务组 10.2）与手工验证使用，
 * 取代此前的 Node 下游桩（桩只能证明转发，不能证明 SQL 与字段加解密链路）。</p>
 *
 * <p>组成：嵌入式 MariaDB（mariaDB4j，与 {@code repository.AbstractDbTest} 同一底座）→ Flyway 迁移
 * V1/V2 → 以 {@code @Primary} 真实 DataSource 覆盖 {@code AccConfiguration} 的 M1 占位数据源
 * → 启动 {@link AccApplication} → 用 ACC 自身 Mapper（真实加密链路）灌入演练夹具账户。</p>
 *
 * <p>用法：</p>
 * <pre>
 *   # 1) 编译（需 test 作用域依赖：mariaDB4j / mariadb-java-client）
 *   mvn -f services/acc/pom.xml -q test-compile dependency:build-classpath \
 *       -Dmdep.includeScope=test -Dmdep.outputFile=target/drill-cp.txt
 *   javac -encoding UTF-8 -cp "target/classes;$(cat target/drill-cp.txt)" \
 *       -d target/drill-classes deploy/drill/AccDrill.java
 *
 *   # 2) 起 ACC 真机（默认 8080；数据库默认 33061，可用外部 mysql 客户端直连核验）
 *   java -cp "target/classes;target/drill-classes;$(cat target/drill-cp.txt)" drill.AccDrill
 *
 *   # 3) 用 ACC 自身 JwtCodec 签发演练 token（与 ACC 配置的 acc.jwt-secret 同密钥）
 *   java -cp "<同上>" drill.AccDrill token 1001 CONSUMER
 * </pre>
 *
 * <p>注意：只用于演练/联调环境，绝不打包进生产物（{@code deploy/} 不在 Maven 源根下）。</p>
 */
public final class AccDrill {

    /** 演练夹具账户 ID（与网关侧 token 的 sub 对齐）。 */
    private static final long FIXTURE_ACCOUNT_ID = 1001L;

    private static DataSource dataSource;
    private static DB db;

    /** 真实 DataSource 覆盖 M1 占位实现：两个 DataSource 候选时由 @Primary 优先注入 SqlSessionFactory。 */
    @Configuration
    public static class RealDbConfig {

        @Bean
        @Primary
        public DataSource drillDataSource() {
            return dataSource;
        }
    }

    private AccDrill() {
    }

    public static void main(String[] args) throws Exception {
        if (args.length > 0 && "token".equals(args[0])) {
            System.out.println(mintToken(args));
            return;
        }
        startEmbeddedDb();
        SpringApplication app = new SpringApplication(AccApplication.class, RealDbConfig.class);
        app.setDefaultProperties(Map.of("server.port", System.getProperty("drill.acc.port", "8080")));
        ConfigurableApplicationContext context = app.run(args);
        seedFixture();
        System.out.println("[drill] ACC 已就绪: http://127.0.0.1:"
                + context.getEnvironment().getProperty("local.server.port", "8080"));
    }

    /** 起嵌入式 MariaDB（固定端口，供外部客户端核验）+ 建库 + Flyway 迁移。 */
    private static void startEmbeddedDb() throws Exception {
        int port = Integer.getInteger("drill.db.port", 33061);
        // 与 AbstractDbTest 同因：Windows 下 java.io.tmpdir 可能含非 ASCII，base/data 必须落在 ASCII 路径。
        String root = System.getProperty("user.dir") + File.separator + "target" + File.separator + "drill-mariadb";
        DBConfigurationBuilder builder = DBConfigurationBuilder.newBuilder();
        builder.setPort(port);
        // 关闭 --skip-grant-tables：V2 需真实执行 CREATE USER / GRANT（最小权限账号 acc_app）
        builder.setSecurityDisabled(false);
        builder.setBaseDir(root + File.separator + "base");
        builder.setDataDir(root + File.separator + "data");
        db = DB.newEmbeddedDB(builder.build());
        db.start();
        Runtime.getRuntime().addShutdownHook(new Thread(() -> {
            try {
                db.stop();
            } catch (Exception ignored) {
                // JVM 退出阶段清理，忽略
            }
        }));

        String bootstrapUrl = "jdbc:mariadb://127.0.0.1:" + port + "/mysql";
        try (Connection c = DriverManager.getConnection(bootstrapUrl, "root", "");
             Statement s = c.createStatement()) {
            // 每次演练从空库开始：结果可复现（V2 的 CREATE USER IF NOT EXISTS 保证授权脚本可重跑）
            s.executeUpdate("DROP DATABASE IF EXISTS acc");
            s.executeUpdate("CREATE DATABASE acc DEFAULT CHARACTER SET utf8mb4");
        }
        dataSource = new UnpooledDataSource("org.mariadb.jdbc.Driver",
                "jdbc:mariadb://127.0.0.1:" + port + "/acc", "root", "");
        Flyway.configure().dataSource(dataSource).load().migrate();
        System.out.println("[drill] 嵌入式 MariaDB 已启动: 127.0.0.1:" + port + " (Flyway V1/V2 已迁移)");
    }

    /**
     * 灌入演练夹具账户：走 ACC 自身 DaoSupport + AccountMapper（真实 EncryptedStringTypeHandler 加密落库），
     * 显式 autocommit，保证其它连接（含外部 mysql 客户端）可见。
     */
    private static void seedFixture() {
        try (SqlSession session = new DaoSupport().factory(dataSource).openSession(true)) {
            Account account = new Account();
            account.setAccountId(FIXTURE_ACCOUNT_ID);
            account.setMobile("13800138000");
            account.setRole("CONSUMER");
            account.setRealNameStatus("REALNAMED");
            account.setWalletStatus("ACTIVE");
            account.setRealName("张三丰");
            account.setIdNo("130101199001011234");
            account.setMobileHash("drill-mobile-hash-1001");
            account.setCreatedAt(Instant.parse("2026-01-01T00:00:00Z"));
            session.getMapper(AccountMapper.class).insert(account);
        }
        System.out.println("[drill] 夹具账户已灌入: account_id=" + FIXTURE_ACCOUNT_ID
                + " (mobile/real_name/id_no 经 AES-GCM 加密落库)");
    }

    /**
     * 用 ACC 自身 JwtCodec 签发演练 token：{@code token <sub|-> [role] [secret] [jti] [ttlSeconds]}。
     * {@code sub} 传 {@code -} 表示**故意不带 sub**（用于验证网关 I9 拒绝无 sub 的 token）。
     */
    private static String mintToken(String[] args) {
        String sub = args.length > 1 ? args[1] : String.valueOf(FIXTURE_ACCOUNT_ID);
        String role = args.length > 2 ? args[2] : "CONSUMER";
        String fixtureSecret = args.length > 3 ? args[3] : new AccProperties().getJwtSecret();
        String jti = args.length > 4 ? args[4] : "drill-jti-" + sub;
        long ttlSeconds = args.length > 5 ? Long.parseLong(args[5]) : 900;

        Map<String, Object> claims = new LinkedHashMap<>();
        if (!"-".equals(sub)) {
            claims.put("sub", sub);
        }
        claims.put("role", role);
        claims.put("mfa", true);
        claims.put("jti", jti);
        // 缺省短 token 口径 15 分钟:网关侧 access-token-max-ttl=15m(超长 token 一律拒绝,见审查 I9)
        return new JwtCodec().sign(claims, fixtureSecret, ttlSeconds);
    }
}
