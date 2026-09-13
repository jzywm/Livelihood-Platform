package com.msz.acc.repository;

import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.sql.Connection;
import java.sql.ResultSet;
import java.sql.Statement;
import java.util.ArrayList;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * IT-06：分表 DDL + 路由就绪——迁移成功、14 张月表存在、wallet_flow_202601 可真实落表。
 */
class FlywayMigrationTest extends AbstractDbTest {

    @Test
    @DisplayName("IT-06: 迁移成功（已应用至 V2）")
    void it06_migrationAppliedToV2() {
        Flyway flyway = Flyway.configure().dataSource(dataSource).load();
        assertThat(flyway.info().current()).isNotNull();
        assertThat(flyway.info().current().getVersion().getVersion()).isEqualTo("2");
    }

    @Test
    @DisplayName("IT-06: 14 张 wallet_flow 月表存在（202507~202608）")
    void it06_fourteenMonthlyTablesExist() throws Exception {
        List<String> tables = listWalletFlowTables();
        assertThat(tables).containsExactlyInAnyOrderElementsOf(WALLET_FLOW_TABLES);
        assertThat(tables).hasSize(14);
    }

    @Test
    @DisplayName("IT-06: 向 wallet_flow_202601 插入后查询落对表")
    void it06_insertIntoJanuaryTableIsVisible() throws Exception {
        try (Connection c = dataSource.getConnection(); Statement s = c.createStatement()) {
            s.executeUpdate("INSERT INTO wallet_flow_202601 "
                    + "(flow_id, account_id, type, direction, amount, status, hash, occurred_at, created_at) VALUES "
                    + "(9001, 1, 'OTHER', 'IN', '1.00', 'SUCCEEDED', 'sha256-dummy', "
                    + "'2026-01-15 00:00:00.000', '2026-01-15 00:00:00.000')");
            try (ResultSet rs = s.executeQuery(
                    "SELECT COUNT(*) FROM wallet_flow_202601 WHERE flow_id = 9001")) {
                assertThat(rs.next()).isTrue();
                assertThat(rs.getInt(1)).isEqualTo(1);
            }
        }
    }

    private List<String> listWalletFlowTables() throws Exception {
        List<String> tables = new ArrayList<>();
        try (Connection c = dataSource.getConnection(); Statement s = c.createStatement();
             ResultSet rs = s.executeQuery(
                     "SELECT table_name FROM information_schema.tables "
                             + "WHERE table_schema = 'acc' AND table_name LIKE 'wallet_flow_%'")) {
            while (rs.next()) {
                tables.add(rs.getString(1));
            }
        }
        return tables;
    }
}
