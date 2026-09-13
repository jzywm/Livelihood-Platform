package com.msz.common.idgen;

/**
 * 号段源抽象：按 bizTag 领取一段连续 ID 区间 [start, end]（含端点）。
 */
public interface SegmentSource {

    long[] nextRange(String bizTag);
}
