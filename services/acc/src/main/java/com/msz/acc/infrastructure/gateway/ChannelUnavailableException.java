package com.msz.acc.infrastructure.gateway;

/**
 * 通道不可用（S5）：连接失败/非 2xx 响应，由 {@link HttpChannelClient} 抛出，
 * 适配层映射为 AccBusinessException(4001，实名通道不可用) 或 4002（支付通道口径）。
 */
public class ChannelUnavailableException extends RuntimeException {

    public ChannelUnavailableException(String message) {
        super(message);
    }

    public ChannelUnavailableException(String message, Throwable cause) {
        super(message, cause);
    }
}
