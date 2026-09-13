package com.msz.common.sharding;

import org.apache.ibatis.executor.statement.StatementHandler;
import org.apache.ibatis.mapping.BoundSql;
import org.apache.ibatis.plugin.Invocation;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.time.Instant;
import java.time.LocalDateTime;
import java.util.HashMap;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 按月分表路由拦截器单测 · 对应 test-plan.md UT-B05~B07：
 * 路由以业务字段 created_at 为准（UTC），wallet_flow 词边界替换为 wallet_flow_YYYYMM，
 * 已带后缀不重复替换，参数缺失/非法抛 IllegalStateException。
 */
class MonthlyShardingInterceptorTest {

    private final MonthlyShardingInterceptor interceptor = new MonthlyShardingInterceptor();

    @Test
    @DisplayName("UT-B05: createdAt=2026-01-31T23:59:59.999Z 替换为 wallet_flow_202601")
    void ut_b05_januaryLastMillisRewritesToJanuary() {
        String sql = "INSERT INTO wallet_flow (id, account_id, amount, created_at) VALUES (?, ?, ?, ?)";
        Map<String, Object> params = new HashMap<>();
        params.put("createdAt", Instant.parse("2026-01-31T23:59:59.999Z"));
        assertThat(interceptor.rewrite(sql, params))
                .isEqualTo("INSERT INTO wallet_flow_202601 (id, account_id, amount, created_at) VALUES (?, ?, ?, ?)");
    }

    @Test
    @DisplayName("UT-B05: createdAt=2026-02-01T00:00:00Z 替换为 wallet_flow_202602")
    void ut_b05_februaryFirstMillisRewritesToFebruary() {
        String sql = "INSERT INTO wallet_flow (id, account_id, amount, created_at) VALUES (?, ?, ?, ?)";
        Map<String, Object> params = new HashMap<>();
        params.put("createdAt", Instant.parse("2026-02-01T00:00:00Z"));
        assertThat(interceptor.rewrite(sql, params))
                .isEqualTo("INSERT INTO wallet_flow_202602 (id, account_id, amount, created_at) VALUES (?, ?, ?, ?)");
    }

    @Test
    @DisplayName("UT-B05: LocalDateTime 兼容按 UTC 月份路由")
    void ut_b05_local_date_time_routes_by_utc_month() {
        String sql = "SELECT * FROM wallet_flow WHERE account_id = ?";
        Map<String, Object> params = new HashMap<>();
        params.put("createdAt", LocalDateTime.of(2026, 1, 15, 10, 30));
        assertThat(interceptor.rewrite(sql, params))
                .isEqualTo("SELECT * FROM wallet_flow_202601 WHERE account_id = ?");
    }

    @Test
    @DisplayName("UT-B05~B07: wallet_flow_202601 已带后缀不重复替换")
    void ut_already_suffixed_table_not_rewritten() {
        String sql = "SELECT * FROM wallet_flow_202601 WHERE id = ?";
        Map<String, Object> params = new HashMap<>();
        params.put("createdAt", Instant.parse("2026-01-15T10:30:00Z"));
        assertThat(interceptor.rewrite(sql, params)).isEqualTo(sql);
    }

    @Test
    @DisplayName("UT-B05~B07: 无 createdAt 参数抛 IllegalStateException")
    void ut_missing_created_at_throws() {
        String sql = "INSERT INTO wallet_flow (id, account_id, amount, created_at) VALUES (?, ?, ?, ?)";
        assertThatThrownBy(() -> interceptor.rewrite(sql, Map.of()))
                .isInstanceOf(IllegalStateException.class);
    }

    @Test
    @DisplayName("UT-B05~B07: intercept 读取 BoundSql 改写后 proceed")
    void ut_intercept_rewrites_and_proceeds() throws Throwable {
        StatementHandler handler = mock(StatementHandler.class);
        BoundSql boundSql = mock(BoundSql.class);
        Invocation invocation = mock(Invocation.class);

        when(invocation.getTarget()).thenReturn(handler);
        when(handler.getBoundSql()).thenReturn(boundSql);
        when(boundSql.getSql()).thenReturn("SELECT * FROM wallet_flow_202601 WHERE id = ?");
        when(boundSql.getParameterObject()).thenReturn(Map.of());
        when(invocation.proceed()).thenReturn("OK");

        Object result = interceptor.intercept(invocation);

        assertThat(result).isEqualTo("OK");
        verify(invocation).proceed();
    }

    @Test
    @DisplayName("UT-B05~B07: 无 createdAt 时 intercept 抛 IllegalStateException 且不 proceed")
    void ut_intercept_missing_created_at_throws_before_proceed() throws Throwable {
        StatementHandler handler = mock(StatementHandler.class);
        BoundSql boundSql = mock(BoundSql.class);
        Invocation invocation = mock(Invocation.class);

        when(invocation.getTarget()).thenReturn(handler);
        when(handler.getBoundSql()).thenReturn(boundSql);
        when(boundSql.getSql()).thenReturn("INSERT INTO wallet_flow (id) VALUES (?)");
        when(boundSql.getParameterObject()).thenReturn(Map.of());

        assertThatThrownBy(() -> interceptor.intercept(invocation))
                .isInstanceOf(IllegalStateException.class);
        verify(invocation, never()).proceed();
    }
}
