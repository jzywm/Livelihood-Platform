package com.msz.acc.application.port;

/**
 * 支付通道端口（S5 提供真实适配）：收款账户校验。
 */
public interface PaymentChannelPort {

    /** 校验收款账户；失败/超时 → AccBusinessException(4002)。 */
    void verifyPayee(long accountId, String channel, String payeeAccount, String realName);
}
