package com.msz.acc.repository;

import ch.vorburger.mariadb4j.DB;
import ch.vorburger.mariadb4j.DBConfigurationBuilder;
import org.apache.ibatis.datasource.unpooled.UnpooledDataSource;
import org.apache.ibatis.session.SqlSession;
import org.apache.ibatis.session.SqlSessionFactory;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.function.Executable;

import javax.sql.DataSource;
import java.io.File;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.SQLException;
import java.sql.Statement;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.junit.jupiter.api.Assertions.assertThrows;

/**
 * DAO 测试基类：MariaDB4j 嵌入式真实 MariaDB（MySQL 兼容语义）+ Flyway 迁移。
 *
 * <p>每次测试类起一次库（@BeforeAll 惰性启动、JVM 级共享）、@BeforeEach 清表；未来 CI 可换 Testcontainers。</p>
 */
abstract class AbstractDbTest {

    protected static final List<String> WALLET_FLOW_TABLES = List.of(
            "wallet_flow_202507", "wallet_flow_202508", "wallet_flow_202509", "wallet_flow_202510",
            "wallet_flow_202511", "wallet_flow_202512", "wallet_flow_202601", "wallet_flow_202602",
            "wallet_flow_202603", "wallet_flow_202604", "wallet_flow_202605", "wallet_flow_202606",
            "wallet_flow_202607", "wallet_flow_202608");

    protected static DataSource dataSource;
    protected static SqlSessionFactory sqlSessionFactory;
    protected static String accUrl;

    private static DB db;

    @BeforeAll
    static synchronized void startDatabase() throws Exception {
        if (db != null) {
            return;
        }
        DBConfigurationBuilder builder = DBConfigurationBuilder.newBuilder();
        builder.setPort(0);
        // 关闭 --skip-grant-tables：V2 需要真实执行 CREATE USER / GRANT（最小权限账号），
        // 否则 GRANT 报 1290（服务器以 skip-grant-tables 运行）。
        builder.setSecurityDisabled(false);
        // Windows 下 java.io.tmpdir 含非 ASCII（用户名）会令 MariaDB 二进制解析参数失败，
        // 故强制 base/data/tmp 落到 ASCII 的工作区 target 目录（每 JVM 唯一后缀避免脏数据）。
        String root = System.getProperty("user.dir") + File.separator + "target"
                + File.separator + "mariadb4j-" + System.nanoTime();
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

        int port = db.getConfiguration().getPort();
        String bootstrapUrl = "jdbc:mariadb://localhost:" + port + "/mysql";
        try (Connection c = DriverManager.getConnection(bootstrapUrl, "root", "");
             Statement s = c.createStatement()) {
            s.executeUpdate("CREATE DATABASE IF NOT EXISTS acc DEFAULT CHARACTER SET utf8mb4");
        }

        accUrl = "jdbc:mariadb://localhost:" + port + "/acc";
        dataSource = new UnpooledDataSource("org.mariadb.jdbc.Driver", accUrl, "root", "");
        Flyway.configure().dataSource(dataSource).load().migrate();
        sqlSessionFactory = new DaoSupport().factory(dataSource);
    }

    @AfterAll
    static void noopAfterAll() {
        // 数据库生命周期由 JVM shutdown hook 统一收尾，测试类间共享，不做逐类启停。
    }

    @BeforeEach
    void cleanTables() throws Exception {
        try (Connection c = dataSource.getConnection(); Statement s = c.createStatement()) {
            for (String table : WALLET_FLOW_TABLES) {
                s.executeUpdate("DELETE FROM " + table);
            }
            s.executeUpdate("DELETE FROM account");
            s.executeUpdate("DELETE FROM realname_record");
            s.executeUpdate("DELETE FROM wallet_binding");
            s.executeUpdate("DELETE FROM reconcile_task");
            s.executeUpdate("DELETE FROM acc_idempotency_record");
        }
    }

    protected static SqlSession openSession() {
        return sqlSessionFactory.openSession(true);
    }

    /** 以 acc_app 账号（最小权限）连接，供库层权限拒绝测试（UT-B03 / SEC-09）。 */
    protected static Connection openAppConnection() throws SQLException {
        return DriverManager.getConnection(accUrl, "acc_app", "acc_app_pwd");
    }

    /** 断言唯一键冲突被库层拒绝（MyBatis 包装为 PersistenceException，根因为 SQLState 23000）。 */
    protected static void assertDuplicateKey(Executable executable) {
        Throwable thrown = assertThrows(RuntimeException.class, executable);
        SQLException sqlException = findSqlException(thrown);
        org.assertj.core.api.Assertions.assertThatObject(sqlException)
                .as("应抛出 SQLException（唯一键冲突）")
                .isNotNull();
        assertThat(sqlException.getSQLState()).isEqualTo("23000");
    }

    private static SQLException findSqlException(Throwable t) {
        Throwable cursor = t;
        while (cursor != null) {
            if (cursor instanceof SQLException se) {
                return se;
            }
            cursor = cursor.getCause();
        }
        return null;
    }
}
