package com.msz.acc.infrastructure.tx;

import com.msz.acc.domain.model.Account;
import com.msz.acc.repository.AccountMapper;
import com.msz.acc.repository.RequestSqlSessionHolder;
import org.apache.ibatis.session.SqlSession;
import org.apache.ibatis.session.SqlSessionFactory;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.time.Instant;
import java.util.concurrent.atomic.AtomicInteger;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

/**
 * TransactionalMapperProxyTest（tasks 1.2）：Mapper 事务感知代理的转发语义（design D3/D7）。
 *
 * <p>断言口径：代理每次调用都落在**当前会话**的 Mapper 上；异常解包后类型与消息不变；
 * 无请求上下文时退化为「单次自动提交会话 + 调用后关闭」；{@code Object} 方法与数据库无关。</p>
 */
class TransactionalMapperProxyTest {

    @Test
    @DisplayName("1.2 请求内：调用落在当前绑定会话的 Mapper 上，且不重复开启会话")
    void dispatchesToMapperOfBoundSession() throws Throwable {
        SqlSessionFactory factory = mock(SqlSessionFactory.class);
        SqlSession session = mock(SqlSession.class);
        when(factory.openSession(false)).thenReturn(session);
        RecordingAccountMapper realMapper = new RecordingAccountMapper();
        when(session.getMapper(AccountMapper.class)).thenReturn(realMapper);

        RequestSqlSessionHolder holder = new RequestSqlSessionHolder(factory);
        AccountMapper proxy = new TransactionalMapperProxy(holder).create(AccountMapper.class);

        holder.beginRequest();
        try {
            proxy.insert(account(77001L));
            proxy.selectById(77001L);
        } finally {
            holder.endRequest();
        }

        assertThat(realMapper.insertCalls.get()).as("insert 转发到当前会话的 Mapper").isEqualTo(1);
        assertThat(realMapper.selectCalls.get()).as("后续调用复用同一会话的 Mapper").isEqualTo(1);
        verify(session, times(2)).getMapper(AccountMapper.class);
        verify(factory, times(1)).openSession(false);
    }

    @Test
    @DisplayName("1.2 异常解包：目标异常类型与消息原样抛出（不包装为 InvocationTargetException）")
    void unwrapsInvocationTargetException() {
        SqlSessionFactory factory = mock(SqlSessionFactory.class);
        SqlSession session = mock(SqlSession.class);
        when(factory.openSession(false)).thenReturn(session);
        IllegalStateException failure = new IllegalStateException("账户表不可用");
        when(session.getMapper(AccountMapper.class)).thenReturn(new FailingAccountMapper(failure));

        RequestSqlSessionHolder holder = new RequestSqlSessionHolder(factory);
        AccountMapper proxy = new TransactionalMapperProxy(holder).create(AccountMapper.class);

        holder.beginRequest();
        try {
            assertThatThrownBy(() -> proxy.insert(account(77002L)))
                    .as("异常原样透出（类型 + 消息不变）")
                    .isSameAs(failure)
                    .hasMessage("账户表不可用");
        } finally {
            holder.endRequest();
        }
    }

    @Test
    @DisplayName("1.2 无请求上下文：降级为单次自动提交会话，调用后关闭会话")
    void fallsBackToStandaloneSessionWithoutRequestContext() throws Throwable {
        SqlSessionFactory factory = mock(SqlSessionFactory.class);
        SqlSession session = mock(SqlSession.class);
        when(factory.openSession(true)).thenReturn(session);
        RecordingAccountMapper realMapper = new RecordingAccountMapper();
        when(session.getMapper(AccountMapper.class)).thenReturn(realMapper);

        RequestSqlSessionHolder holder = new RequestSqlSessionHolder(factory);
        AccountMapper proxy = new TransactionalMapperProxy(holder).create(AccountMapper.class);

        proxy.insert(account(77003L));

        assertThat(realMapper.insertCalls.get()).isEqualTo(1);
        verify(factory).openSession(true);
        verify(factory, never()).openSession(false);
        verify(session).close();
    }

    @Test
    @DisplayName("1.2 Object 方法（toString/hashCode/equals）不触会话：日志/容器调用不得占用连接")
    void objectMethodsDoNotTouchSession() {
        SqlSessionFactory factory = mock(SqlSessionFactory.class);
        RequestSqlSessionHolder holder = new RequestSqlSessionHolder(factory);
        AccountMapper proxy = new TransactionalMapperProxy(holder).create(AccountMapper.class);

        assertThat(proxy.toString()).contains("AccountMapper");
        assertThat(proxy.hashCode()).isEqualTo(System.identityHashCode(proxy));
        assertThat(proxy.equals(proxy)).isTrue();
        assertThat(proxy.equals(new Object())).isFalse();
        verifyNoInteractions(factory);
    }

    private static Account account(long accountId) {
        Account account = new Account();
        account.setAccountId(accountId);
        account.setCreatedAt(Instant.parse("2026-01-01T00:00:00Z"));
        return account;
    }

    /** 记录调用次数的真实 Mapper 实现（用于验证代理把调用落到了「当前会话的 Mapper」上）。 */
    private static final class RecordingAccountMapper implements AccountMapper {

        private final AtomicInteger insertCalls = new AtomicInteger();
        private final AtomicInteger selectCalls = new AtomicInteger();

        @Override
        public int insert(Account account) {
            return insertCalls.incrementAndGet();
        }

        @Override
        public Account selectById(long accountId) {
            selectCalls.incrementAndGet();
            return null;
        }

        @Override
        public Account selectByMobileHash(String mobileHash) {
            throw new UnsupportedOperationException();
        }

        @Override
        public int softClose(long accountId, String closeReason, Instant closedAt) {
            throw new UnsupportedOperationException();
        }
    }

    /** 固定抛出指定异常的真实 Mapper 实现（验证代理解包行为）。 */
    private static final class FailingAccountMapper implements AccountMapper {

        private final RuntimeException failure;

        FailingAccountMapper(RuntimeException failure) {
            this.failure = failure;
        }

        @Override
        public int insert(Account account) {
            throw failure;
        }

        @Override
        public Account selectById(long accountId) {
            throw failure;
        }

        @Override
        public Account selectByMobileHash(String mobileHash) {
            throw failure;
        }

        @Override
        public int softClose(long accountId, String closeReason, Instant closedAt) {
            throw failure;
        }
    }
}
