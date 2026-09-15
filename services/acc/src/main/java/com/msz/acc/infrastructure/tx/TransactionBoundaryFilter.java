package com.msz.acc.infrastructure.tx;

import com.msz.acc.repository.RequestSqlSessionHolder;
import jakarta.servlet.Filter;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.ServletRequest;
import jakarta.servlet.ServletResponse;

import java.io.IOException;

/**
 * 请求级事务边界过滤器（design D1/D4/D5/D6）：紧随信任头鉴权过滤器（order 1）之后，order 更大，
 * {@code urlPatterns = /acc/*}，在「身份解析之后、控制器之前」承担一个请求 = 一个事务的边界。
 *
 * <p>边界口径：</p>
 * <ul>
 *   <li><b>进入</b>：{@link RequestSqlSessionHolder#beginRequest()} 只标记作用域，**不获取数据库连接**
 *       （design D4 硬约束：占位/不可用数据源下，不触库的请求必须照常可用）；</li>
 *   <li><b>正常返回</b>：{@link RequestSqlSessionHolder#commit()} 提交；本请求未触库时为空操作；</li>
 *   <li><b>未捕获的非受检异常</b>（{@link RuntimeException}/{@link Error}，含业务异常
 *       {@code AccBusinessException}）→ {@link RequestSqlSessionHolder#rollback()} 回滚后原样抛出；
 *       由此**失败的业务操作不再占用幂等槽位**（{@code acc_idempotency_record} 的 INSERT IGNORE 随事务回滚）；</li>
 *   <li><b>结束</b>：{@code finally} 中 {@link RequestSqlSessionHolder#endRequest()} 关闭会话（归还连接）
 *       并清理 ThreadLocal——成功与失败路径同等对待。</li>
 * </ul>
 *
 * <p><b>受检异常口径（与 design D6 的差异，已登记实施报告）</b>：D6 的书面口径是「受检异常
 * （{@code Exception} 非 {@code RuntimeException}）视为正常返回并**提交**」，并自陈「不得默默提交半成品」的
 * 隐患；而行为契约（spec「Request-scoped transaction boundary」）要求「请求因**未捕获异常**失败时必须回滚，
 * 且不得留下对其他连接可见的部分写入」。规格为约束权威，故实现取**回滚**口径：{@link ServletException}、
 * {@link IOException} 等未捕获受检异常与未受检异常同等处理，仅「成功返回」才提交。</p>
 */
public final class TransactionBoundaryFilter implements Filter {

    private final RequestSqlSessionHolder holder;

    public TransactionBoundaryFilter(RequestSqlSessionHolder holder) {
        this.holder = holder;
    }

    @Override
    public void doFilter(ServletRequest request, ServletResponse response, FilterChain chain)
            throws IOException, ServletException {
        holder.beginRequest();
        try {
            chain.doFilter(request, response);
            holder.commit();
        } catch (RuntimeException | Error e) {
            holder.rollback();
            throw e;
        } catch (Exception e) {
            holder.rollback();
            throw e;
        } finally {
            holder.endRequest();
        }
    }
}
