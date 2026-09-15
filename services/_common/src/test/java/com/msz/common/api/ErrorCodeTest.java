package com.msz.common.api;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 1.1 错误码常量表单测：与 services/_common/openapi.yaml 错误码权威源逐一一致。
 */
class ErrorCodeTest {

    @Test
    @DisplayName("1.1: ErrorCode 常量与 openapi.yaml 码值逐一一致")
    void ut_error_code_constants_match_openapi() {
        assertThat(ErrorCode.OK).isEqualTo(0);
        assertThat(ErrorCode.PARAM_MISSING).isEqualTo(1001);
        assertThat(ErrorCode.PARAM_FORMAT).isEqualTo(1002);
        assertThat(ErrorCode.PARAM_RANGE).isEqualTo(1003);
        assertThat(ErrorCode.UNAUTHORIZED).isEqualTo(2001);
        assertThat(ErrorCode.FORBIDDEN).isEqualTo(2002);
        assertThat(ErrorCode.MFA_REQUIRED).isEqualTo(2003);
        assertThat(ErrorCode.REALNAME_INCOMPLETE).isEqualTo(3001);
        assertThat(ErrorCode.REALNAME_MISMATCH).isEqualTo(3002);
        assertThat(ErrorCode.LICENSE_FAILED).isEqualTo(3003);
        assertThat(ErrorCode.CREDIT_INSUFFICIENT).isEqualTo(3004);
        assertThat(ErrorCode.MERCHANT_NOT_ONBOARDED).isEqualTo(3005);
        assertThat(ErrorCode.OBJECT_NOT_FOUND).isEqualTo(3006);
        assertThat(ErrorCode.STATUS_NOT_ALLOWED).isEqualTo(3007);
        assertThat(ErrorCode.IDEMPOTENCY_CONFLICT).isEqualTo(3008);
        assertThat(ErrorCode.RECONCILE_DIFF).isEqualTo(3009);
        assertThat(ErrorCode.MINOR_VIOLATION).isEqualTo(3010);
        assertThat(ErrorCode.CONTENT_VIOLATION).isEqualTo(3011);
        assertThat(ErrorCode.THIRD_PARTY_REALNAME_FAILED).isEqualTo(4001);
        assertThat(ErrorCode.CHANNEL_FAILED).isEqualTo(4002);
        assertThat(ErrorCode.AI_API_FAILED).isEqualTo(4003);
        assertThat(ErrorCode.SMS_FAILED).isEqualTo(4004);
        assertThat(ErrorCode.INTERNAL_ERROR).isEqualTo(5000);
        assertThat(ErrorCode.DB_ERROR).isEqualTo(5001);
        assertThat(ErrorCode.DEPENDENCY_TIMEOUT).isEqualTo(5002);
        assertThat(ErrorCode.RATE_LIMITED).isEqualTo(2004);
        assertThat(ErrorCode.GATEWAY_UNAVAILABLE).isEqualTo(5003);
    }

    @Test
    @DisplayName("1.1: message(int) 默认文案与 openapi.yaml 口径一致")
    void ut_error_code_message_matches_openapi() {
        assertThat(ErrorCode.message(ErrorCode.OK)).isEqualTo("成功");
        assertThat(ErrorCode.message(ErrorCode.PARAM_MISSING)).isEqualTo("参数缺失");
        assertThat(ErrorCode.message(ErrorCode.PARAM_FORMAT)).isEqualTo("参数格式错误");
        assertThat(ErrorCode.message(ErrorCode.PARAM_RANGE)).isEqualTo("枚举/范围非法");
        assertThat(ErrorCode.message(ErrorCode.UNAUTHORIZED)).isEqualTo("未登录 / Token 失效");
        assertThat(ErrorCode.message(ErrorCode.FORBIDDEN)).isEqualTo("无权限 / 越权");
        assertThat(ErrorCode.message(ErrorCode.OBJECT_NOT_FOUND)).isEqualTo("对象不存在");
        assertThat(ErrorCode.message(ErrorCode.IDEMPOTENCY_CONFLICT)).isEqualTo("幂等键冲突");
        assertThat(ErrorCode.message(ErrorCode.CHANNEL_FAILED)).isEqualTo("支付通道失败 / 超时");
        assertThat(ErrorCode.message(ErrorCode.INTERNAL_ERROR)).isEqualTo("内部错误");
        assertThat(ErrorCode.message(ErrorCode.DB_ERROR)).isEqualTo("数据库错误");
        assertThat(ErrorCode.message(ErrorCode.DEPENDENCY_TIMEOUT)).isEqualTo("依赖超时 / 熔断");
        assertThat(ErrorCode.message(ErrorCode.RATE_LIMITED)).isEqualTo("请求过于频繁");
        assertThat(ErrorCode.message(ErrorCode.GATEWAY_UNAVAILABLE)).isEqualTo("网关暂不可用");
    }

    @Test
    @DisplayName("1.1: message(3009) 含「对账」口径抽查")
    void ut_error_code_message_3009_contains_reconcile() {
        assertThat(ErrorCode.message(ErrorCode.RECONCILE_DIFF)).contains("对账");
    }
}
