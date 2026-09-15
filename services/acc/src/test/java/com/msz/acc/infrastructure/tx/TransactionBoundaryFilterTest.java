package com.msz.acc.infrastructure.tx;

import com.msz.acc.repository.RequestSqlSessionHolder;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.ServletRequest;
import jakarta.servlet.ServletResponse;
import org.apache.ibatis.session.SqlSession;
import org.apache.ibatis.session.SqlSessionFactory;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;

import java.util.concurrent.atomic.AtomicReference;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.anyBoolean;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * TransactionBoundaryFilterTest（tasks 1.3）：请求级事务边界（design D1/D4/D5/D6）。
 *
 * <p>覆盖：成功路径提交并关闭；未捕获 {@link RuntimeException}/{@link Error} 回滚并原样抛出；
 * 未触库的请求不开启会话（D4 硬约束）；受检异常按 D6 口径提交（已在过滤器注释中写明）；
 * 回滚失败或关闭前异常都不改变「请求结束必清理作用域」这一事实。</p>
 */
class TransactionBoundaryFilterTest {

    @Test
    @DisplayName("1.3 成功路径：提交 + 关闭会话 + 清理请求作用域")
    void commitsAndClosesOnSuccess() throws Exception {
        SqlSessionFactory factory = mock(SqlSessionFactory.class);
        SqlSession session = mock(SqlSession.class);
        when(factory.openSession(false)).thenReturn(session);
        RequestSqlSessionHolder holder = new RequestSqlSessionHolder(factory);
        TransactionBoundaryFilter filter = new TransactionBoundaryFilter(holder);

        filter.doFilter(mock(ServletRequest.class), mock(ServletResponse.class), touchingDb(holder));

        assertThat(holder.isRequestActive()).as("请求结束必须清理作用域").isFalse();
        verify(session).commit();
        verify(session).close();
        verify(session, never()).rollback();
    }

    @Test
    @DisplayName("1.3 未捕获 RuntimeException：回滚 + 关闭 + 异常原样抛出")
    void rollsBackOnRuntimeException() throws Exception {
        SqlSessionFactory factory = mock(SqlSessionFactory.class);
        SqlSession session = mock(SqlSession.class);
        when(factory.openSession(false)).thenReturn(session);
        RequestSqlSessionHolder holder = new RequestSqlSessionHolder(factory);
        TransactionBoundaryFilter filter = new TransactionBoundaryFilter(holder);

        IllegalStateException failure = new IllegalStateException("下游失败");
        FilterChain chain = (request, response) -> {
            holder.currentSession();
            throw failure;
        };

        assertThatThrownBy(() -> filter.doFilter(
                mock(ServletRequest.class), mock(ServletResponse.class), chain))
                .as("原始异常必须原样抛出（不得被事务边界改写）")
                .isSameAs(failure);

        assertThat(holder.isRequestActive()).as("失败路径同样必须清理作用域").isFalse();
        verify(session).rollback();
        verify(session).close();
        verify(session, never()).commit();
    }

    @Test
    @DisplayName("1.3 未捕获 Error：同样回滚 + 关闭")
    void rollsBackOnError() throws Exception {
        SqlSessionFactory factory = mock(SqlSessionFactory.class);
        SqlSession session = mock(SqlSession.class);
        when(factory.openSession(false)).thenReturn(session);
        RequestSqlSessionHolder holder = new RequestSqlSessionHolder(factory);
        TransactionBoundaryFilter filter = new TransactionBoundaryFilter(holder);

        AssertionError failure = new AssertionError("OOM 级别错误");
        FilterChain chain = (request, response) -> {
            holder.currentSession();
            throw failure;
        };

        assertThatThrownBy(() -> filter.doFilter(
                mock(ServletRequest.class), mock(ServletResponse.class), chain))
                .isSameAs(failure);
        verify(session).rollback();
        verify(session).close();
    }

    @Test
    @DisplayName("1.3/2.1 显式失败信号：错误 Envelope 置位 rollbackOnly → 边界回滚而非提交")
    void rollbackOnlyMarkerRollsBackInsteadOfCommitting() throws Exception {
        SqlSessionFactory factory = mock(SqlSessionFactory.class);
        SqlSession session = mock(SqlSession.class);
        when(factory.openSession(false)).thenReturn(session);
        RequestSqlSessionHolder holder = new RequestSqlSessionHolder(factory);
        TransactionBoundaryFilter filter = new TransactionBoundaryFilter(holder);

        MockHttpServletRequest request = new MockHttpServletRequest();
        filter.doFilter(request, new MockHttpServletResponse(), (servletRequest, servletResponse) -> {
            holder.currentSession();
            assertThat(servletRequest.getAttribute(TransactionBoundaryFilter.ROLLBACK_ONLY_ATTRIBUTE))
                    .as("正常路径不得带失败信号").isNull();
            // 模拟 GlobalExceptionHandler 产出错误 Envelope 时的标记
            TransactionBoundaryFilter.markRollbackOnly(servletRequest);
        });

        verify(session).rollback();
        verify(session, never()).commit();
        verify(session).close();
        assertThat(holder.isRequestActive()).isFalse();
    }

    @Test
    @DisplayName("1.3 未触库的请求：不开启会话、不提交回滚（D4 惰性开启硬约束）")
    void doesNotOpenSessionWithoutDataAccess() throws Exception {
        SqlSessionFactory factory = mock(SqlSessionFactory.class);
        RequestSqlSessionHolder holder = new RequestSqlSessionHolder(factory);
        TransactionBoundaryFilter filter = new TransactionBoundaryFilter(holder);

        filter.doFilter(mock(ServletRequest.class), mock(ServletResponse.class), (request, response) -> {
            // 不触库的请求：链上没有任何 Mapper 调用
        });

        verify(factory, never()).openSession(anyBoolean());
        assertThat(holder.isRequestActive()).isFalse();
    }

    @Test
    @DisplayName("1.3 受检异常同样回滚：spec「未捕获异常 → 不得留下部分写入」优先于 D6 书面口径")
    void checkedExceptionAlsoRollsBack() throws Exception {
        SqlSessionFactory factory = mock(SqlSessionFactory.class);
        SqlSession session = mock(SqlSession.class);
        when(factory.openSession(false)).thenReturn(session);
        RequestSqlSessionHolder holder = new RequestSqlSessionHolder(factory);
        TransactionBoundaryFilter filter = new TransactionBoundaryFilter(holder);

        FilterChain chain = (request, response) -> {
            holder.currentSession();
            throw new ServletException("受检异常：按 spec 口径不得提交半成品");
        };

        assertThatThrownBy(() -> filter.doFilter(
                mock(ServletRequest.class), mock(ServletResponse.class), chain))
                .isInstanceOf(ServletException.class);

        verify(session).rollback();
        verify(session, never()).commit();
        verify(session).close();
    }

    @Test
    @DisplayName("1.3 回滚失败不掩盖原始异常，且会话仍被关闭")
    void rollbackFailureDoesNotMaskOriginalException() throws Exception {
        SqlSessionFactory factory = mock(SqlSessionFactory.class);
        SqlSession session = mock(SqlSession.class);
        when(factory.openSession(false)).thenReturn(session);
        doThrow(new IllegalStateException("回滚时连接已断开")).when(session).rollback();
        RequestSqlSessionHolder holder = new RequestSqlSessionHolder(factory);
        TransactionBoundaryFilter filter = new TransactionBoundaryFilter(holder);

        IllegalStateException failure = new IllegalStateException("业务失败");
        FilterChain chain = (request, response) -> {
            holder.currentSession();
            throw failure;
        };

        assertThatThrownBy(() -> filter.doFilter(
                mock(ServletRequest.class), mock(ServletResponse.class), chain))
                .as("回滚失败不得掩盖调用方原始异常")
                .isSameAs(failure);
        verify(session).close();
        assertThat(holder.isRequestActive()).isFalse();
    }

    @Test
    @DisplayName("1.3 连续请求各用独立会话：上一个请求的会话不会串到下一个请求")
    void consecutiveRequestsUseIndependentSessions() throws Exception {
        SqlSessionFactory factory = mock(SqlSessionFactory.class);
        SqlSession first = mock(SqlSession.class);
        SqlSession second = mock(SqlSession.class);
        when(factory.openSession(false)).thenReturn(first, second);
        RequestSqlSessionHolder holder = new RequestSqlSessionHolder(factory);
        TransactionBoundaryFilter filter = new TransactionBoundaryFilter(holder);

        AtomicReference<SqlSession> seenInSecond = new AtomicReference<>();
        filter.doFilter(mock(ServletRequest.class), mock(ServletResponse.class), touchingDb(holder));
        filter.doFilter(mock(ServletRequest.class), mock(ServletResponse.class), (request, response) ->
                seenInSecond.set(holder.currentSession()));

        verify(factory, times(2)).openSession(false);
        assertThat(seenInSecond.get()).as("第二个请求必须拿到新会话").isSameAs(second);
        verify(first).close();
    }

    private static FilterChain touchingDb(RequestSqlSessionHolder holder) {
        return (request, response) -> holder.currentSession();
    }
}
