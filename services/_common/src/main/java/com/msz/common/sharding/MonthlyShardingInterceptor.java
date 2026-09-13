package com.msz.common.sharding;

import org.apache.ibatis.executor.statement.StatementHandler;
import org.apache.ibatis.mapping.BoundSql;
import org.apache.ibatis.plugin.Interceptor;
import org.apache.ibatis.plugin.Intercepts;
import org.apache.ibatis.plugin.Invocation;
import org.apache.ibatis.plugin.Plugin;
import org.apache.ibatis.plugin.Signature;

import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.sql.Connection;
import java.time.Instant;
import java.time.LocalDateTime;
import java.time.YearMonth;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;
import java.util.Map;
import java.util.Properties;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * 按月分表路由拦截器（MyBatis Interceptor，拦截 StatementHandler.prepare）。
 *
 * <p>识别 SQL 中的 {@code wallet_flow}（词边界），按绑定参数 {@code createdAt}
 * （{@link Instant} 或 {@link LocalDateTime}，兼容两者）的 UTC 月份替换为
 * {@code wallet_flow_YYYYMM}；已带后缀（如 wallet_flow_202601）不重复替换；
 * 参数取不到或类型非法 → 抛 {@link IllegalStateException}（1003 口径由上层处理）。</p>
 *
 * <p>依赖选型：{@code org.mybatis:mybatis} 3.5.x。理由：本拦截器只依赖
 * {@link Interceptor}/{@link StatementHandler}/{@link BoundSql} 等标准 MyBatis SPI，
 * 不涉及 MyBatis-Plus 特有类，引入 mybatis-plus-core 会带入无谓的传递依赖（YAGNI）。</p>
 */
@Intercepts({
        @Signature(type = StatementHandler.class, method = "prepare", args = {Connection.class, Integer.class})
})
public final class MonthlyShardingInterceptor implements Interceptor {

    /** 词边界：匹配独立的 wallet_flow（其后跟非单词字符）；wallet_flow_202601 因 "_" 为单词字符不会命中。 */
    private static final Pattern WALLET_FLOW = Pattern.compile("\\bwallet_flow\\b");
    private static final String TABLE_PREFIX = "wallet_flow_";
    private static final DateTimeFormatter MONTH_FORMAT = DateTimeFormatter.ofPattern("yyyyMM");
    private static final Field SQL_FIELD = sqlField();

    private final String createdAtField;

    public MonthlyShardingInterceptor() {
        this("createdAt");
    }

    public MonthlyShardingInterceptor(String createdAtField) {
        this.createdAtField = createdAtField;
    }

    @Override
    public Object intercept(Invocation invocation) throws Throwable {
        StatementHandler handler = (StatementHandler) invocation.getTarget();
        BoundSql boundSql = handler.getBoundSql();
        String sql = boundSql.getSql();
        String rewritten = rewrite(sql, boundSql.getParameterObject());
        if (!rewritten.equals(sql)) {
            setSql(boundSql, rewritten);
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

    /** 包内可见，供单测直接断言改写结果。 */
    String rewrite(String sql, Object parameterObject) {
        if (sql == null || !WALLET_FLOW.matcher(sql).find()) {
            return sql;
        }
        Object createdAt = resolve(parameterObject, createdAtField);
        if (createdAt == null) {
            throw new IllegalStateException(
                    "按月分表缺少 createdAt 参数，无法路由（1003 口径由上层处理）");
        }
        String table = TABLE_PREFIX + utcMonth(createdAt);
        return WALLET_FLOW.matcher(sql).replaceAll(Matcher.quoteReplacement(table));
    }

    private static Object resolve(Object parameterObject, String field) {
        if (parameterObject == null) {
            return null;
        }
        if (parameterObject instanceof Map<?, ?> map) {
            return map.get(field);
        }
        // POJO：优先 getter，其次字段。
        String getter = "get" + Character.toUpperCase(field.charAt(0)) + field.substring(1);
        try {
            Method m = parameterObject.getClass().getMethod(getter);
            return m.invoke(parameterObject);
        } catch (ReflectiveOperationException ignored) {
            // 回退到字段读取
        }
        try {
            Field f = parameterObject.getClass().getDeclaredField(field);
            f.setAccessible(true);
            return f.get(parameterObject);
        } catch (ReflectiveOperationException e) {
            return null;
        }
    }

    private static String utcMonth(Object createdAt) {
        Instant instant;
        if (createdAt instanceof Instant i) {
            instant = i;
        } else if (createdAt instanceof LocalDateTime ldt) {
            instant = ldt.toInstant(ZoneOffset.UTC);
        } else {
            throw new IllegalStateException(
                    "createdAt 类型非法（需 Instant 或 LocalDateTime）: " + createdAt.getClass().getName());
        }
        YearMonth month = YearMonth.from(instant.atZone(ZoneOffset.UTC));
        return month.format(MONTH_FORMAT);
    }

    private static Field sqlField() {
        try {
            Field f = BoundSql.class.getDeclaredField("sql");
            f.setAccessible(true);
            return f;
        } catch (NoSuchFieldException e) {
            throw new ExceptionInInitializerError(e);
        }
    }

    private static void setSql(BoundSql boundSql, String sql) {
        try {
            SQL_FIELD.set(boundSql, sql);
        } catch (IllegalAccessException e) {
            throw new IllegalStateException("无法改写 BoundSql.sql", e);
        }
    }
}
