package com.msz.acc.domain.service;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 脱敏策略单元测试 · 对应 test-plan.md UT-F02（脱敏格式对齐 er.md 示例）。
 */
class MaskingPolicyTest {

    private final MaskingPolicy policy = new MaskingPolicy();

    @Test
    @DisplayName("UT-F02: 手机号脱敏 13800138000 → 138****8000")
    void ut_f02_masksMobile() {
        assertThat(policy.maskMobile("13800138000")).isEqualTo("138****8000");
    }

    @Test
    @DisplayName("UT-F02: 姓名脱敏 张三丰 → 张*丰")
    void ut_f02_masksThreeCharName() {
        assertThat(policy.maskName("张三丰")).isEqualTo("张*丰");
    }

    @Test
    @DisplayName("UT-F02: 两字姓名脱敏 张三 → 张*")
    void ut_f02_masksTwoCharName() {
        assertThat(policy.maskName("张三")).isEqualTo("张*");
    }

    @Test
    @DisplayName("UT-F02: 单字姓名原样保留")
    void ut_f02_singleCharNameStaysUnchanged() {
        assertThat(policy.maskName("张")).isEqualTo("张");
    }

    @Test
    @DisplayName("UT-F02: 证件号脱敏 130123199001011234 → 1301**********1234")
    void ut_f02_masksIdNo() {
        assertThat(policy.maskIdNo("130123199001011234")).isEqualTo("1301**********1234");
    }

    @Test
    @DisplayName("UT-F02: 银行卡号脱敏 6222021234567890 → 6222*********890")
    void ut_f02_masksBankCard() {
        assertThat(policy.maskBankCard("6222021234567890")).isEqualTo("6222*********890");
    }

    @Test
    @DisplayName("UT-F02: null 输入安全透传")
    void ut_f02_nullInputIsSafe() {
        assertThat(policy.maskMobile(null)).isNull();
        assertThat(policy.maskName(null)).isNull();
        assertThat(policy.maskIdNo(null)).isNull();
        assertThat(policy.maskBankCard(null)).isNull();
    }

    @Test
    @DisplayName("UT-F02: 空串输入安全透传")
    void ut_f02_emptyInputIsSafe() {
        assertThat(policy.maskMobile("")).isEmpty();
        assertThat(policy.maskName("")).isEmpty();
    }
}
