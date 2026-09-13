package com.msz.acc.application.port;

/**
 * 人机验证校验结果：success 是否通过；verifyToken 通过后下发的一次性凭证（5 分钟有效）。
 */
public record CaptchaVerifyResult(boolean success, String verifyToken) {
}
