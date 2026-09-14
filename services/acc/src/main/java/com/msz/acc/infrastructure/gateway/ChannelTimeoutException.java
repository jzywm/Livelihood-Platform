package com.msz.acc.infrastructure.gateway;

/**
 * 通道调用超时（S5）：由 {@link HttpChannelClient} 抛出，适配层映射为
 * AccBusinessException(5002，依赖超时/熔断) 或 4002（支付通道口径）。
 */
public class ChannelTimeoutException extends RuntimeException {

    public ChannelTimeoutException(String message) {
        super(message);
    }

    public ChannelTimeoutException(String message, Throwable cause) {
        super(message, cause);
    }
}
