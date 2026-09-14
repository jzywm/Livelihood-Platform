package com.msz.acc.controller;

import com.msz.acc.application.port.CaptchaPort;
import com.msz.acc.application.port.CaptchaVerifyResult;
import com.msz.acc.domain.support.AccBusinessException;
import com.msz.acc.infrastructure.captcha.CaptchaService;
import com.msz.acc.infrastructure.web.TraceIds;
import com.msz.common.api.Envelope;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.time.Clock;

/**
 * 人机验证接口（openapi /acc/captcha、/acc/captcha/verify）：挑战下发不含答案；
 * 校验错误/过期返回 success=false 不抛异常。
 */
@RestController
public class CaptchaController {

    private final CaptchaPort captchaPort;
    private final Clock clock;

    public CaptchaController(CaptchaPort captchaPort, Clock clock) {
        this.captchaPort = captchaPort;
        this.clock = clock;
    }

    @GetMapping("/acc/captcha")
    public Envelope<CaptchaChallengeView> challenge(@RequestParam(required = false) String type,
                                                    HttpServletRequest request) {
        String resolved = resolveType(type);
        String captchaId = captchaPort.createChallenge(resolved);
        CaptchaChallengeView data = new CaptchaChallengeView(captchaId, resolved,
                clock.instant().plusSeconds(CaptchaService.TTL_SECONDS).toString());
        return Envelope.ok(data, TraceIds.of(request));
    }

    @PostMapping("/acc/captcha/verify")
    public Envelope<CaptchaVerifyView> verify(@RequestBody CaptchaVerifyBody body, HttpServletRequest request) {
        if (body.captchaId() == null || body.captchaId().isBlank()) {
            throw new AccBusinessException(1001, "captchaId 缺失");
        }
        CaptchaVerifyResult result = captchaPort.verify(body.captchaId(), body.offsetX(), body.code());
        return Envelope.ok(new CaptchaVerifyView(result.success(), result.verifyToken()), TraceIds.of(request));
    }

    private static String resolveType(String type) {
        if (type == null || type.isBlank() || "SLIDER".equals(type)) {
            return "SLIDER";
        }
        if ("IMAGE".equals(type)) {
            return "IMAGE";
        }
        throw new AccBusinessException(1003, "验证类型非法（仅 SLIDER/IMAGE）");
    }

    /** openapi CaptchaChallenge（不含 answer）。 */
    public record CaptchaChallengeView(String captchaId, String type, String expireAt) {
    }

    /** openapi CaptchaVerifyResult。 */
    public record CaptchaVerifyView(boolean success, String verifyToken) {
    }

    /** openapi CaptchaVerifyRequest。 */
    public record CaptchaVerifyBody(String captchaId, Integer offsetX, String code) {
    }
}
