package com.msz.acc.application.port;

/**
 * 人机验证端口（S5 提供真实适配）：挑战下发 / 校验下发 verifyToken / 一次性消费 captchaToken。
 * 挑战号使用 {@code cap_} 前缀（er.md §6.6）。
 */
public interface CaptchaPort {

    /** 下发挑战：type 为空时缺省 SLIDER；返回挑战号（cap_ 前缀）。 */
    String createChallenge(String type);

    /** 校验挑战，成功后返回一次性凭证 verifyToken。 */
    CaptchaVerifyResult verify(String captchaId, Integer offsetX, String code);

    /** 一次性消费注册回填的 captchaToken；无效/已用 → AccBusinessException(1003)。 */
    void consumeToken(String captchaToken);
}
