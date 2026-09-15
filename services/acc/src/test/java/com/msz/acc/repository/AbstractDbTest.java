package com.msz.acc.repository;

import com.msz.acc.testsupport.EmbeddedMariaDb;
import org.apache.ibatis.session.SqlSession;
import org.apache.ibatis.session.SqlSessionFactory;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.function.Executable;

import javax.sql.DataSource;
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

    private static EmbeddedMariaDb embedded;

    @BeforeAll
    static synchronized void startDatabase() throws Exception {
        if (embedded != null) {
            return;
        }
        // 库启动逻辑与真实库装配层测试共用 testsupport.EmbeddedMariaDb（避免两处漂移）
        embedded = EmbeddedMariaDb.start();
        dataSource = embedded.dataSource();
        accUrl = embedded.url();
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
