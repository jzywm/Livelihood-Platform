package com.msz.acc.repository;

import org.apache.ibatis.session.SqlSession;
import org.apache.ibatis.session.SqlSessionFactory;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * 请求级会话持有器（design D1/D2/D4/D7）：把 {@link SqlSession} 绑定到处理请求的线程，
 * 由事务边界过滤器（{@code infrastructure.tx.TransactionBoundaryFilter}）在请求进入时标记作用域、
 * 结束时提交/回滚并关闭。
 *
 * <p><b>惰性开启（硬约束，design D4）</b>：作用域标记本身**不获取数据库连接**，会话在「本请求第一次真正
 * 访问数据库」时才 {@code openSession(false)} 并绑定；因此不触库的请求（如 {@code /acc/captcha}）在
 * 占位/不可用数据源下仍可正常服务。</p>
 *
 * <p><b>该硬约束的判据（评审 F2 更正，2026-09-15）</b>：判据是**单测对 {@code SqlSessionFactory} 的
 * mock 断言「未触库时 {@code openSession} 零调用」**（{@code RequestSqlSessionHolderTest} 与
 * {@code TransactionBoundaryFilterTest} 各一条）加代码核对——**6 个 {@code @MockBean} 控制器测试不构成
 * 判据**：MyBatis 的 {@code openSession()} 本身不取连接（{@code JdbcTransaction} 构造只赋字段，
 * {@code getConnection()} 才建连，未用时 {@code commit()} 在 {@code connection == null} 时直接返回），
 * 故「入口急切开启会话」不会让那些用例变红；它们只能证明过滤链在占位数据源下可正常工作。</p>
 *
 * <p><b>绑定与清理（design D2）</b>：{@link ThreadLocal} 保证同一 {@link SqlSession} 只被一个请求线程使用；
 * 请求结束必须调用 {@link #endRequest()}——关闭会话（归还连接）并 {@code remove()}，
 * 否则 Tomcat 线程复用时会把上一个请求的会话串给下一个请求。</p>
 *
 * <p><b>无请求上下文的降级（design D7）</b>：非 Web 调用路径（测试夹具、脚本、将来的定时任务）不在过滤器
 * 边界内，{@link #executeStandalone} 为其提供「单次自动提交会话 + 调用后立即关闭」的语义，
 * 既保持这类调用可用，也不再产生「长驻会话」这一缺陷根源。</p>
 */
public final class RequestSqlSessionHolder {

    private static final Logger log = LoggerFactory.getLogger(RequestSqlSessionHolder.class);

    /** 会话工作单元：在持有器给定的会话上执行操作，异常原样透出（供 Mapper 代理透传）。 */
    @FunctionalInterface
    public interface SessionWork<T> {

        T run(SqlSession session) throws Throwable;
    }

    private final SqlSessionFactory factory;
    private final ThreadLocal<RequestScope> scope = new ThreadLocal<>();

    public RequestSqlSessionHolder(SqlSessionFactory factory) {
        this.factory = factory;
    }

    /** 当前线程是否处于请求作用域（与「是否已开会话」无关：未触库的请求也在作用域内）。 */
    public boolean isRequestActive() {
        return scope.get() != null;
    }

    /**
     * 标记请求作用域开始：只建标记，**不获取数据库连接**（design D4）。
     *
     * <p><b>不许重入（FIX-1/F5）</b>：同一线程已有作用域时**显式拒绝**（{@link IllegalStateException}）。
     * 原实现无条件 {@code set(new RequestScope())} 覆盖——一旦容器把事务边界过滤器也挂到
     * {@code FORWARD}/{@code ERROR}/{@code ASYNC} 派发上（或将来有人再注册一个同 urlPatterns 的边界），
     * 内层进入会**静默丢弃外层作用域**：外层会话从不提交/回滚也从不 close（连接泄漏），
     * 外层事务语义被内层顶替。选择「拒绝」而非「复用」的理由：复用会让内层的提交/回滚作用在外层事务上
     * （把外层的边界提前结束），同样是静默的语义破坏；而「同一次请求内两次进入」本身即配置错误，
     * 应当立刻炸出来。两个 {@code FilterRegistrationBean} 已显式声明只服务 {@code REQUEST} 派发
     * （{@code AccConfiguration#trustedHeaderAuthFilterRegistration} /
     * {@code #transactionBoundaryFilterRegistration}），当前不可达——本校验是防配置漂移的兜底。</p>
     */
    public void beginRequest() {
        if (scope.get() != null) {
            throw new IllegalStateException(
                    "当前线程已有请求作用域：beginRequest 不得重入（重复进入会丢弃外层会话/连接）");
        }
        scope.set(new RequestScope());
    }

    /**
     * 当前请求会话：已创建则复用（内层调用等价 Spring 的 {@code REQUIRED} 传播，design D8），
     * 未创建则惰性 {@code openSession(false)}（事务由本持有器所在边界提交/回滚）。
     */
    public SqlSession currentSession() {
        RequestScope current = scope.get();
        if (current == null) {
            throw new IllegalStateException(
                    "当前线程无请求级会话作用域（非 Web 调用路径请用 executeStandalone）");
        }
        if (current.session == null) {
            current.session = factory.openSession(false);
        }
        return current.session;
    }

    /** 提交请求事务：本请求未触库（未创建会话）时为空操作。 */
    public void commit() {
        SqlSession session = boundSession();
        if (session == null) {
            return;
        }
        session.commit();
    }

    /** 回滚请求事务：本请求未触库时为空操作；回滚自身失败只记日志，不掩盖调用方的原始异常。 */
    public void rollback() {
        SqlSession session = boundSession();
        if (session == null) {
            return;
        }
        try {
            session.rollback();
        } catch (RuntimeException e) {
            log.warn("请求事务回滚失败（原始异常优先，连接由 close 收尾）", e);
        }
    }

    /** 结束请求：关闭会话（归还连接）并清理 ThreadLocal；无论成功/失败都必须调用（通常置于 finally）。 */
    public void endRequest() {
        RequestScope current = scope.get();
        scope.remove();
        if (current == null || current.session == null) {
            return;
        }
        try {
            current.session.close();
        } catch (RuntimeException e) {
            log.warn("请求会话关闭失败（连接由数据源/驱动兜底回收）", e);
        }
    }

    /**
     * 无请求上下文时的降级执行（design D7）：单次自动提交会话，调用结束（含异常）即关闭。
     *
     * <p>注意：该路径**不是**请求事务的替代品，同一次调用内的多条语句不会原子提交——仅用于非 Web 调用路径。</p>
     */
    public <T> T executeStandalone(SessionWork<T> work) throws Throwable {
        try (SqlSession session = factory.openSession(true)) {
            return work.run(session);
        }
    }

    private SqlSession boundSession() {
        RequestScope current = scope.get();
        return current == null ? null : current.session;
    }

    /** 请求作用域：仅承载本线程的会话引用（惰性填充）。 */
    private static final class RequestScope {

        private SqlSession session;
    }
}
