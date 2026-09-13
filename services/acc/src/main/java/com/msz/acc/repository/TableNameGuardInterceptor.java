package com.msz.acc.repository;

import org.apache.ibatis.executor.Executor;
import org.apache.ibatis.mapping.MappedStatement;
import org.apache.ibatis.plugin.Interceptor;
import org.apache.ibatis.plugin.Intercepts;
import org.apache.ibatis.plugin.Invocation;
import org.apache.ibatis.plugin.Plugin;
import org.apache.ibatis.plugin.Signature;
import org.apache.ibatis.session.ResultHandler;
import org.apache.ibatis.session.RowBounds;

import java.util.Map;
import java.util.Properties;

/**
 * 查询路径动态表名白名单强制拦截器（防注入）。
 *
 * <p>拦截 {@link WalletFlowMapper#selectByAccountAndRange} 与
 * {@link WalletFlowMapper#countByAccountAndRange} 的 {@link Executor#query}，在 SQL 构建
 * （{@code ${tableName}} 插值）之前从参数中取出 {@code tableName}，经
 * {@link DaoSupport#requireTableName} 校验（{@code ^wallet_flow_\d{6}$}），非法直接抛
 * {@link IllegalArgumentException}，使强制校验自动生效而不依赖调用方手工预校验。</p>
 */
@Intercepts({
        @Signature(type = Executor.class, method = "query",
                args = {MappedStatement.class, Object.class, RowBounds.class, ResultHandler.class})
})
public final class TableNameGuardInterceptor implements Interceptor {

    private static final String SELECT_BY_ACCOUNT_AND_RANGE = "WalletFlowMapper.selectByAccountAndRange";
    private static final String COUNT_BY_ACCOUNT_AND_RANGE = "WalletFlowMapper.countByAccountAndRange";

    @Override
    public Object intercept(Invocation invocation) throws Throwable {
        MappedStatement statement = (MappedStatement) invocation.getArgs()[0];
        String id = statement.getId();
        if (id.endsWith(SELECT_BY_ACCOUNT_AND_RANGE) || id.endsWith(COUNT_BY_ACCOUNT_AND_RANGE)) {
            DaoSupport.requireTableName(resolveTableName(invocation.getArgs()[1]));
        }
        return invocation.proceed();
    }

    @Override
    public Object plugin(Object target) {
        return Plugin.wrap(target, this);
    }

    @Override
    public void setProperties(Properties properties) {
        // 无配置项
    }

    /** 从 @Param 包裹的 ParamMap 中按签名取出 tableName；取不到返回 null（由 requireTableName 拒绝）。 */
    private static String resolveTableName(Object parameter) {
        if (parameter instanceof Map<?, ?> map) {
            Object value = map.get("tableName");
            if (value instanceof String tableName) {
                return tableName;
            }
        }
        return null;
    }
}
