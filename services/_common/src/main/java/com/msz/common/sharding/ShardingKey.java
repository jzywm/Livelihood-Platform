package com.msz.common.sharding;

import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;

/**
 * 分表路由声明注解（标注在 Mapper 方法上）：声明分片键对应业务字段。
 * 本 S1 仅落地注解 + 按月路由拦截器（以 created_at 为准）。
 */
@Retention(RetentionPolicy.RUNTIME)
@Target(ElementType.METHOD)
public @interface ShardingKey {

    /** 账户维度分片字段名（预留，账户维度路由）。 */
    String accountIdField() default "accountId";

    /** 创建时间业务字段名（按月路由依据）。 */
    String createdAtField() default "createdAt";
}
