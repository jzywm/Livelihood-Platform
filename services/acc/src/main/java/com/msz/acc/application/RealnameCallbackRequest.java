package com.msz.acc.application;

/**
 * 第三方实名回调请求（外部回调，验签 + 幂等）。
 *
 * @param timestamp epoch 秒（±300s 窗口）
 * @param nonce     随机串（长度 8~64）
 */
public record RealnameCallbackRequest(String bizId, String openId, String name, String idNo,
                                      boolean pass, String sign, long timestamp, String nonce) {
}
