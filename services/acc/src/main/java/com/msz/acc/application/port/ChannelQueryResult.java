package com.msz.acc.application.port;

/**
 * 通道回查结果（超时重查 JOB 用）：open_id / 姓名 / 证件号 / 是否通过。
 */
public record ChannelQueryResult(String openId, String name, String idNo, boolean passed) {
}
