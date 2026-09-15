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
 *   <li><b>未捕获的异常（含受检）</b>（{@link RuntimeException}/{@link Error} 及未捕获受检异常，含业务异常
 *       {@code AccBusinessException}）→ {@link RequestSqlSessionHolder#rollback()} 回滚后原样抛出；
 *       由此**失败的业务操作不再占用幂等槽位**（{@code acc_idempotency_record} 的 INSERT IGNORE 随事务回滚）；</li>
 *   <li><b>结束</b>：{@code finally} 中 {@link RequestSqlSessionHolder#endRequest()} 关闭会话（归还连接）
 *       并清理 ThreadLocal——成功与失败路径同等对待。</li>
 * </ul>
 *
 * <p><b>失败信号口径（实施期发现，补 design D5/D6 未覆盖的一环）</b>：Spring MVC 的
 * {@code @RestControllerAdvice}（{@code GlobalExceptionHandler}）会把控制器抛出的异常转换成
 * 错误 Envelope 返回，异常**不会**抵达过滤器——若只看 {@code catch} 分支，失败请求会被当成正常返回提交，
 * 半成品与幂等占位都会留存。故本过滤器额外承认一个显式失败信号：{@link #markRollbackOnly} 置位的请求属性
 * （由 {@code GlobalExceptionHandler} 在产出错误 Envelope 时调用），边界见属性即回滚而不提交。</p>
 *
 * <p><b>受检异常口径（已生效口径 = design D6 实施期修订 R-7，2026-09-15）</b>：D6 现定档
 * 「**未捕获的异常（含受检）一律回滚**，仅正常返回才提交」，与 spec「Request-scoped transaction boundary」
 * 的「请求因未捕获异常失败时必须回滚，且不得留下对其他连接可见的部分写入」一致——{@link ServletException}、
 * {@link IOException} 等未捕获受检异常与 {@link RuntimeException}/{@link Error} 同等处理。
 * 实现与该口径**无偏差**，有意偏离 Spring 默认（受检异常返回时提交）的理由见 design D6：ACC 现有异常
 * 全为非受检，而「受检异常默默提交半成品」是更危险的失败模式。</p>
 */
public final class TransactionBoundaryFilter implements Filter {

    /** 失败信号：置位即表示本请求以错误 Envelope 结束，边界必须回滚。 */
    public static final String ROLLBACK_ONLY_ATTRIBUTE = "acc.transaction.rollbackOnly";

    private final RequestSqlSessionHolder holder;

    public TransactionBoundaryFilter(RequestSqlSessionHolder holder) {
        this.holder = holder;
    }

    /**
     * 标记「本请求失败，禁止提交」：由错误 Envelope 的产出方
     * （{@code com.msz.acc.controller.GlobalExceptionHandler}）调用。
     */
    public static void markRollbackOnly(ServletRequest request) {
        request.setAttribute(ROLLBACK_ONLY_ATTRIBUTE, Boolean.TRUE);
    }

    @Override
    public void doFilter(ServletRequest request, ServletResponse response, FilterChain chain)
            throws IOException, ServletException {
        holder.beginRequest();
        try {
            chain.doFilter(request, response);
            if (isRollbackOnly(request)) {
                holder.rollback();
            } else {
                holder.commit();
            }
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

    private static boolean isRollbackOnly(ServletRequest request) {
        return Boolean.TRUE.equals(request.getAttribute(ROLLBACK_ONLY_ATTRIBUTE));
    }
}
