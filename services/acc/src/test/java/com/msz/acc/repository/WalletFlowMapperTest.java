package com.msz.acc.repository;

import com.msz.acc.domain.model.WalletFlow;
import org.apache.ibatis.session.SqlSession;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Method;
import java.sql.Connection;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;
import java.time.Instant;
import java.util.Arrays;
import java.util.Locale;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * WalletFlowMapperTest（UT-B03 / UT-B08 口径）：写入路由正确、uk_channel_order_no 唯一/NULL 豁免、
 * 库层拒绝 UPDATE/DELETE、mapper 无 update/delete 方法、动态表名白名单。
 */
class WalletFlowMapperTest extends AbstractDbTest {

    @Test
    @DisplayName("UT-B05: createdAt 2026-01-31T23:59:59.999Z 落 wallet_flow_202601，直查可见")
    void insertRoutesByCreatedAtToJanuaryTable() throws Exception {
        WalletFlow flow = flow(7001L, 1L, "CH-7001", Instant.parse("2026-01-31T23:59:59.999Z"));
        try (SqlSession s = openSession()) {
            s.getMapper(WalletFlowMapper.class).insert(flow);
        }

        assertThat(countRows("wallet_flow_202601", 7001L)).isEqualTo(1);
        assertThat(countRows("wallet_flow_202602", 7001L)).isZero();
    }

    @Test
    @DisplayName("UT-B08: uk_channel_order_no 重复被拒")
    void duplicateChannelOrderNoIsRejected() {
        Instant createdAt = Instant.parse("2026-01-10T00:00:00Z");
        try (SqlSession s = openSession()) {
            WalletFlowMapper mapper = s.getMapper(WalletFlowMapper.class);
            mapper.insert(flow(7002L, 1L, "CH-DUP", createdAt));
            assertDuplicateKey(() -> mapper.insert(flow(7003L, 1L, "CH-DUP", createdAt)));
        }
    }

    @Test
    @DisplayName("UT-B08: channel_order_no NULL 多行共存（唯一索引豁免）")
    void nullChannelOrderNoRowsCoexist() throws SQLException {
        Instant createdAt = Instant.parse("2026-01-11T00:00:00Z");
        try (SqlSession s = openSession()) {
            WalletFlowMapper mapper = s.getMapper(WalletFlowMapper.class);
            mapper.insert(flow(7004L, 1L, null, createdAt));
            mapper.insert(flow(7005L, 1L, null, createdAt));
        }
        assertThat(countRows("wallet_flow_202601", 7004L)).isEqualTo(1);
        assertThat(countRows("wallet_flow_202601", 7005L)).isEqualTo(1);
    }

    @Test
    @DisplayName("UT-B03/SEC-09: acc_app 对 wallet_flow 有 SELECT 权限（账号与授权生效）")
    void appAccountCanSelectWalletFlow() throws Exception {
        try (Connection c = openAppConnection(); Statement s = c.createStatement();
             ResultSet rs = s.executeQuery("SELECT COUNT(*) FROM acc.wallet_flow_202601")) {
            assertThat(rs.next()).isTrue();
            assertThat(rs.getInt(1)).isZero();
        }
    }

    @Test
    @DisplayName("UT-B03/SEC-09: acc_app 对 wallet_flow UPDATE 库层拒绝")
    void appAccountCannotUpdateWalletFlow() {
        assertThatThrownBy(() -> {
            try (Connection c = openAppConnection(); Statement s = c.createStatement()) {
                s.executeUpdate("UPDATE acc.wallet_flow_202601 SET amount = '0.01'");
            }
        }).isInstanceOfSatisfying(SQLException.class,
                e -> assertThat(e.getSQLState()).isEqualTo("42000"));
    }

    @Test
    @DisplayName("UT-B03/SEC-09: acc_app 对 wallet_flow DELETE 库层拒绝")
    void appAccountCannotDeleteWalletFlow() {
        assertThatThrownBy(() -> {
            try (Connection c = openAppConnection(); Statement s = c.createStatement()) {
                s.executeUpdate("DELETE FROM acc.wallet_flow_202601");
            }
        }).isInstanceOfSatisfying(SQLException.class,
                e -> assertThat(e.getSQLState()).isEqualTo("42000"));
    }

    @Test
    @DisplayName("UT-B03: mapper 无 update/delete 方法（反射断言）")
    void mapperHasNoUpdateOrDeleteMethods() {
        assertThat(Arrays.stream(WalletFlowMapper.class.getDeclaredMethods())
                .map(Method::getName)
                .map(name -> name.toLowerCase(Locale.ROOT)))
                .noneMatch(name -> name.contains("update") || name.contains("delete"));
    }

    @Test
    @DisplayName("动态表名白名单：非法表名抛 IllegalArgumentException（防注入）")
    void dynamicTableNameWhitelist() {
        DaoSupport.requireTableName("wallet_flow_202601");
        assertThatThrownBy(() -> DaoSupport.requireTableName("wallet_flow_202601; DROP TABLE account"))
                .isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> DaoSupport.requireTableName("account"))
                .isInstanceOf(IllegalArgumentException.class);
    }

    @Test
    @DisplayName("查询路径白名单拦截器：绕过手工预校验直接调用时非法表名被拦截器拒绝")
    void queryPathTableNameWhitelistEnforcedByInterceptor() {
        Instant from = Instant.parse("2026-01-01T00:00:00Z");
        Instant to = Instant.parse("2026-01-31T23:59:59.999Z");
        try (SqlSession s = openSession()) {
            WalletFlowMapper mapper = s.getMapper(WalletFlowMapper.class);
            // 不预先调用 DaoSupport.requireTableName，直接调 mapper，靠拦截器强制校验。
            // 拦截器抛 IllegalArgumentException，经 MyBatis 包装为 PersistenceException，故断言根因。
            assertThatThrownBy(() -> mapper.selectByAccountAndRange(
                    "wallet_flow_202601; DROP TABLE account", 1L, from, to, 0, 10, null))
                    .hasRootCauseInstanceOf(IllegalArgumentException.class);
            assertThatThrownBy(() -> mapper.countByAccountAndRange(
                    "account", 1L, from, to, null))
                    .hasRootCauseInstanceOf(IllegalArgumentException.class);
            // 合法表名正常返回
            assertThat(mapper.countByAccountAndRange("wallet_flow_202601", 1L, from, to, null)).isZero();
        }
    }

    @Test
    @DisplayName("selectByAccountAndRange / countByAccountAndRange 按 account_id + 日期范围命中")
    void selectByAccountAndRange() {
        Instant createdAt = Instant.parse("2026-01-12T00:00:00Z");
        try (SqlSession s = openSession()) {
            WalletFlowMapper mapper = s.getMapper(WalletFlowMapper.class);
            mapper.insert(flow(7101L, 42L, "CH-7101", createdAt));
            mapper.insert(flow(7102L, 42L, "CH-7102", Instant.parse("2026-01-13T00:00:00Z")));
            mapper.insert(flow(7103L, 99L, "CH-7103", createdAt));
        }

        try (SqlSession s = openSession()) {
            WalletFlowMapper mapper = s.getMapper(WalletFlowMapper.class);
            DaoSupport.requireTableName("wallet_flow_202601");
            assertThat(mapper.countByAccountAndRange("wallet_flow_202601", 42L,
                    Instant.parse("2026-01-01T00:00:00Z"), Instant.parse("2026-01-31T23:59:59.999Z"), null)).isEqualTo(2);
            assertThat(mapper.selectByAccountAndRange("wallet_flow_202601", 42L,
                    Instant.parse("2026-01-01T00:00:00Z"), Instant.parse("2026-01-31T23:59:59.999Z"), 0, 10, null))
                    .hasSize(2)
                    .allSatisfy(f -> assertThat(f.getAccountId()).isEqualTo(42L));
        }
    }

    @Test
    @DisplayName("countByAccountAndRange type 过滤：type 参数下推、null 忽略")
    void countByAccountAndRangeFiltersByType() {
        Instant createdAt = Instant.parse("2026-01-14T00:00:00Z");
        try (SqlSession s = openSession()) {
            WalletFlowMapper mapper = s.getMapper(WalletFlowMapper.class);
            mapper.insert(flow(7201L, 43L, "CH-7201", createdAt));
            mapper.insert(flowOfType(7202L, 43L, "PAYROLL", "CH-7202", createdAt));
        }

        try (SqlSession s = openSession()) {
            WalletFlowMapper mapper = s.getMapper(WalletFlowMapper.class);
            Instant from = Instant.parse("2026-01-01T00:00:00Z");
            Instant to = Instant.parse("2026-01-31T23:59:59.999Z");
            assertThat(mapper.countByAccountAndRange("wallet_flow_202601", 43L, from, to, null)).isEqualTo(2);
            assertThat(mapper.countByAccountAndRange("wallet_flow_202601", 43L, from, to, "PAYROLL")).isEqualTo(1);
            assertThat(mapper.countByAccountAndRange("wallet_flow_202601", 43L, from, to, "REFUND")).isZero();
        }
    }

    @Test
    @DisplayName("selectByAccountAndRange type 过滤：type 参数下推、null 忽略")
    void selectByAccountAndRangeFiltersByType() {
        Instant createdAt = Instant.parse("2026-01-14T00:00:00Z");
        try (SqlSession s = openSession()) {
            WalletFlowMapper mapper = s.getMapper(WalletFlowMapper.class);
            mapper.insert(flow(7301L, 44L, "CH-7301", createdAt));
            mapper.insert(flowOfType(7302L, 44L, "PAYROLL", "CH-7302", createdAt));
        }

        try (SqlSession s = openSession()) {
            WalletFlowMapper mapper = s.getMapper(WalletFlowMapper.class);
            Instant from = Instant.parse("2026-01-01T00:00:00Z");
            Instant to = Instant.parse("2026-01-31T23:59:59.999Z");
            assertThat(mapper.selectByAccountAndRange("wallet_flow_202601", 44L, from, to, 0, 10, null))
                    .hasSize(2);
            assertThat(mapper.selectByAccountAndRange("wallet_flow_202601", 44L, from, to, 0, 10, "PAYROLL"))
                    .hasSize(1)
                    .allSatisfy(f -> assertThat(f.getType()).isEqualTo("PAYROLL"));
            assertThat(mapper.selectByAccountAndRange("wallet_flow_202601", 44L, from, to, 0, 10, "REFUND"))
                    .isEmpty();
        }
    }

    @Test
    @DisplayName("selectAllByRange：跨账户全量读取（审计/对账口径），非法表名被拦截器拒绝")
    void selectAllByRange() {
        Instant createdAt = Instant.parse("2026-01-12T00:00:00Z");
        try (SqlSession s = openSession()) {
            WalletFlowMapper mapper = s.getMapper(WalletFlowMapper.class);
            mapper.insert(flow(7401L, 42L, "CH-7401", createdAt));
            mapper.insert(flow(7402L, 99L, "CH-7402", Instant.parse("2026-01-13T00:00:00Z")));
        }

        try (SqlSession s = openSession()) {
            WalletFlowMapper mapper = s.getMapper(WalletFlowMapper.class);
            Instant from = Instant.parse("2026-01-01T00:00:00Z");
            Instant to = Instant.parse("2026-01-31T23:59:59.999Z");
            assertThat(mapper.selectAllByRange("wallet_flow_202601", from, to, 0, 10))
                    .hasSize(2)
                    .extracting(WalletFlow::getAccountId)
                    .containsExactlyInAnyOrder(42L, 99L);
            assertThatThrownBy(() -> mapper.selectAllByRange(
                    "account", from, to, 0, 10))
                    .hasRootCauseInstanceOf(IllegalArgumentException.class);
        }
    }

    private static WalletFlow flow(long flowId, long accountId, String channelOrderNo, Instant createdAt) {
        WalletFlow flow = new WalletFlow();
        flow.setFlowId(flowId);
        flow.setAccountId(accountId);
        flow.setType("OTHER");
        flow.setDirection("IN");
        flow.setAmount("100.50");
        flow.setStatus("SUCCEEDED");
        flow.setChannelOrderNo(channelOrderNo);
        flow.setBizType("test");
        flow.setHash("sha256-dummy");
        flow.setOccurredAt(createdAt);
        flow.setCreatedAt(createdAt);
        return flow;
    }

    private static WalletFlow flowOfType(long flowId, long accountId, String type, String channelOrderNo, Instant createdAt) {
        WalletFlow flow = flow(flowId, accountId, channelOrderNo, createdAt);
        flow.setType(type);
        return flow;
    }

    private int countRows(String tableName, long flowId) throws SQLException {
        try (Connection c = dataSource.getConnection(); Statement s = c.createStatement();
             ResultSet rs = s.executeQuery("SELECT COUNT(*) FROM " + tableName + " WHERE flow_id = " + flowId)) {
            return rs.next() ? rs.getInt(1) : 0;
        }
    }
}
