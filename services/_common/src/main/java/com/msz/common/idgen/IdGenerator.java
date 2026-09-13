package com.msz.common.idgen;

/**
 * ID 生成器：雪花 + 号段双轨。
 */
public interface IdGenerator {

    /** 生成一个全局唯一 ID（默认业务标签）。 */
    long nextId();

    /** 按业务标签生成全局唯一 ID（号段轨按 bizTag 分段）。 */
    long nextId(String bizTag);

    /** 当前发号模式：snowflake | segment。 */
    String mode();
}
