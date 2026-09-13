package com.msz.common.idgen;

/**
 * 时钟源抽象，便于测试注入可控时钟。
 */
public interface TimeSource {

    /** 当前毫秒时间戳。 */
    long millis();
}
