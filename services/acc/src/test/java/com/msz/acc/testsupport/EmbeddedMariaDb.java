package com.msz.acc.testsupport;

import ch.vorburger.mariadb4j.DB;
import ch.vorburger.mariadb4j.DBConfigurationBuilder;
import org.apache.ibatis.datasource.unpooled.UnpooledDataSource;
import org.flywaydb.core.Flyway;

import javax.sql.DataSource;
import java.io.File;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.Statement;

/**
 * 嵌入式真实 MariaDB 测试支撑（MariaDB4j，MySQL 兼容语义）+ Flyway 迁移。
 *
 * <p>用途：DAO 层测试（{@code repository.AbstractDbTest}）与**真实库装配层测试**
 * （{@code config.RealDbAssemblyTest}）共用同一套启动逻辑，避免两处漂移。</p>
 *
 * <p>要点：① 关闭 {@code --skip-grant-tables}——V2 需真实执行 CREATE USER / GRANT；
 * ② 库目录落在 ASCII 的 {@code target/} 下（Windows 下 {@code java.io.tmpdir} 可能含非 ASCII，
 * 会让 MariaDB 二进制解析参数失败），每次启动用唯一后缀避免脏数据；
 * ③ 数据库生命周期由 JVM shutdown hook 统一收尾。</p>
 */
public final class EmbeddedMariaDb {

    private static final String DRIVER = "org.mariadb.jdbc.Driver";

    private final DB db;
    private final DataSource dataSource;
    private final String url;

    private EmbeddedMariaDb(DB db, DataSource dataSource, String url) {
        this.db = db;
        this.dataSource = dataSource;
        this.url = url;
    }

    /** 起库（port=0 表示随机端口）+ 建库 acc + Flyway 迁移，返回可直连的 DataSource。 */
    public static EmbeddedMariaDb start() throws Exception {
        return start(0);
    }

    /** 起库（指定端口，便于外部客户端核验）+ 建库 acc + Flyway 迁移。 */
    public static EmbeddedMariaDb start(int port) throws Exception {
        DBConfigurationBuilder builder = DBConfigurationBuilder.newBuilder();
        builder.setPort(port);
        builder.setSecurityDisabled(false);
        String root = System.getProperty("user.dir") + File.separator + "target"
                + File.separator + "mariadb4j-" + System.nanoTime();
        builder.setBaseDir(root + File.separator + "base");
        builder.setDataDir(root + File.separator + "data");

        DB db = DB.newEmbeddedDB(builder.build());
        db.start();
        Runtime.getRuntime().addShutdownHook(new Thread(() -> {
            try {
                db.stop();
            } catch (Exception ignored) {
                // JVM 退出阶段清理，忽略
            }
        }));

        int actualPort = db.getConfiguration().getPort();
        try (Connection c = DriverManager.getConnection(
                "jdbc:mariadb://127.0.0.1:" + actualPort + "/mysql", "root", "");
             Statement s = c.createStatement()) {
            s.executeUpdate("CREATE DATABASE IF NOT EXISTS acc DEFAULT CHARACTER SET utf8mb4");
        }

        String url = "jdbc:mariadb://127.0.0.1:" + actualPort + "/acc";
        DataSource dataSource = new UnpooledDataSource(DRIVER, url, "root", "");
        Flyway.configure().dataSource(dataSource).load().migrate();
        return new EmbeddedMariaDb(db, dataSource, url);
    }

    public DataSource dataSource() {
        return dataSource;
    }

    public String url() {
        return url;
    }

    /** 以 acc_app 账号（最小权限）新建独立连接，用于「应用外部视角」的落库核验。 */
    public Connection openExternalConnection() throws Exception {
        return DriverManager.getConnection(url, "acc_app", "acc_app_pwd");
    }
}
