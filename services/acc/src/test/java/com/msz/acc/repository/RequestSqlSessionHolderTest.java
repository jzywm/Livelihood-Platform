package com.msz.acc.repository;

import org.apache.ibatis.datasource.unpooled.UnpooledDataSource;
import org.apache.ibatis.session.SqlSession;
import org.apache.ibatis.session.SqlSessionFactory;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.concurrent.atomic.AtomicReference;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.anyBoolean;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * RequestSqlSessionHolderTest（tasks 1.1）：请求级会话持有器的绑定/复用/清理与无上下文降级（design D2/D4/D7）。
 *
 * <p>绑定与复用用**真实** {@link SqlSessionFactory}（{@link DaoSupport} 构建，数据源指向不可达地址）验证——
 * MyBatis 会话的创建/提交/关闭都不触连，只有真正执行语句才需要连接，故这些断言是真实对象行为；
 * 「关闭」类断言用替身会话，直接核验请求结束时的 close 调用（tasks 1.1 判据）。</p>
 */
class RequestSqlSessionHolderTest {

    @Test
    @DisplayName("1.1 请求作用域内：重复获取返回同一会话（隐式 REQUIRED 复用）")
    void reusesBoundSessionWithinRequest() throws Throwable {
        SqlSessionFactory factory = inertFactory();
        RequestSqlSessionHolder holder = new RequestSqlSessionHolder(factory);

        assertThat(holder.isRequestActive()).as("未标记作用域时不在请求中").isFalse();
        holder.beginRequest();
        try {
            SqlSession first = holder.currentSession();
            SqlSession second = holder.currentSession();

            assertThat(first).as("同一请求内复用同一会话（不重复开启）").isSameAs(second);
            assertThat(first.getConfiguration()).as("取到的是本工厂的真实会话").isSameAs(factory.getConfiguration());
            assertThat(holder.isRequestActive()).isTrue();
        } finally {
            holder.endRequest();
        }
    }

    @Test
    @DisplayName("1.1 会话绑定到线程：其它线程拿不到本请求的会话（ThreadLocal 语义）")
    void bindingIsThreadScoped() throws Throwable {
        RequestSqlSessionHolder holder = new RequestSqlSessionHolder(inertFactory());
        holder.beginRequest();
        try {
            AtomicReference<Throwable> other = new AtomicReference<>();
            Thread thread = new Thread(() -> {
                try {
                    holder.currentSession();
                } catch (Throwable e) {
                    other.set(e);
                }
            });
            thread.start();
            thread.join();

            assertThat(other.get())
                    .as("另一线程无请求作用域：不得拿到本线程会话")
                    .isInstanceOf(IllegalStateException.class);
        } finally {
            holder.endRequest();
        }
    }

    @Test
    @DisplayName("1.1 未标记请求作用域：直接取会话被拒（提示走降级路径）")
    void currentSessionWithoutRequestScopeIsRejected() {
        RequestSqlSessionHolder holder = new RequestSqlSessionHolder(inertFactory());

        assertThatThrownBy(holder::currentSession)
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("请求级会话作用域");
    }

    @Test
    @DisplayName("1.1 无请求上下文：降级为单次自动提交会话，调用后立即关闭")
    void standaloneFallsBackToAutocommitSessionAndClosesIt() throws Throwable {
        SqlSessionFactory factory = mock(SqlSessionFactory.class);
        SqlSession session = mock(SqlSession.class);
        when(factory.openSession(true)).thenReturn(session);
        RequestSqlSessionHolder holder = new RequestSqlSessionHolder(factory);

        AtomicReference<SqlSession> used = new AtomicReference<>();
        String result = holder.executeStandalone(given -> {
            used.set(given);
            return "ok";
        });

        assertThat(result).as("降级路径不抛错且返回调用结果").isEqualTo("ok");
        assertThat(used.get()).isSameAs(session);
        verify(factory).openSession(true);
        verify(factory, never()).openSession(false);
        verify(session).close();
    }

    @Test
    @DisplayName("1.1 请求结束：关闭会话并清理 ThreadLocal，新请求不复用旧会话")
    void cleansUpSessionAndThreadLocalAfterRequest() throws Throwable {
        SqlSessionFactory factory = mock(SqlSessionFactory.class);
        SqlSession first = mock(SqlSession.class);
        SqlSession second = mock(SqlSession.class);
        when(factory.openSession(false)).thenReturn(first, second);
        RequestSqlSessionHolder holder = new RequestSqlSessionHolder(factory);

        holder.beginRequest();
        SqlSession bound = holder.currentSession();
        holder.endRequest();

        assertThat(bound).isSameAs(first);
        // 请求结束必须关闭会话（归还连接）
        verify(first).close();
        assertThat(holder.isRequestActive()).as("请求结束必须清理 ThreadLocal").isFalse();

        holder.beginRequest();
        try {
            assertThat(holder.currentSession()).as("新请求必须是新会话").isSameAs(second);
        } finally {
            holder.endRequest();
        }
        verify(second).close();
    }

    @Test
    @DisplayName("1.1/1.3 未触库的请求：提交/回滚/结束都不开启会话（惰性开启硬约束）")
    void commitAndRollbackWithoutTouchingDbOpenNoSession() {
        SqlSessionFactory factory = mock(SqlSessionFactory.class);
        RequestSqlSessionHolder holder = new RequestSqlSessionHolder(factory);

        holder.beginRequest();
        holder.commit();
        holder.rollback();
        holder.endRequest();

        verify(factory, never()).openSession(anyBoolean());
    }

    @Test
    @DisplayName("1.1 回滚失败不向调用方抛出（不得掩盖原始异常），会话仍被关闭")
    void rollbackFailureIsSwallowed() throws Throwable {
        SqlSessionFactory factory = mock(SqlSessionFactory.class);
        SqlSession session = mock(SqlSession.class);
        when(factory.openSession(false)).thenReturn(session);
        doThrow(new IllegalStateException("连接已断开")).when(session).rollback();
        RequestSqlSessionHolder holder = new RequestSqlSessionHolder(factory);

        holder.beginRequest();
        holder.currentSession();
        holder.rollback();
        holder.endRequest();

        verify(session).close();
        assertThat(holder.isRequestActive()).isFalse();
    }

    /** 真实工厂 + 不可达数据源：会话创建/提交/关闭均不触连（只有执行语句才需要连接）。 */
    private static SqlSessionFactory inertFactory() {
        return new DaoSupport().factory(new UnpooledDataSource(
                "org.mariadb.jdbc.Driver", "jdbc:mariadb://127.0.0.1:1/acc", "root", ""));
    }
}
