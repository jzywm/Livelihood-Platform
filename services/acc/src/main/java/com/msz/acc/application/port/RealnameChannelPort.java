package com.msz.acc.application.port;

/**
 * 第三方实名通道端口（S5 提供真实适配，唯一口径 R-02，不静默降级）。
 */
public interface RealnameChannelPort {

    /** 发起实名授权，返回授权页地址 authorizeUrl；通道不可用 → AccBusinessException(4001)。 */
    String requestAuthorization(String bizId, String mobile, String role);

    /** 超时重查 JOB 用（S4 只定义不实现 JOB），按 bizId 回查通道结果。 */
    ChannelQueryResult queryResult(String bizId);
}
