package com.msz.acc.domain.service;

import com.msz.acc.domain.support.AccBusinessException;
import net.jqwik.api.Arbitraries;
import net.jqwik.api.Arbitrary;
import net.jqwik.api.Combinators;
import net.jqwik.api.ForAll;
import net.jqwik.api.Property;
import net.jqwik.api.Provide;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatCode;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * 金额规则单元测试 · 对应 test-plan.md UT-B04：
 * 合法边界通过（0.01/0.10/1.00/最大值），非法（123.456/-1/1e10/超精度/前导零）报 1003；
 * jqwik 属性测试验证「任意合法两位小数金额恒为合法」不变量。
 */
class AmountPolicyTest {

    private final AmountPolicy policy = new AmountPolicy();

    @ParameterizedTest
    @ValueSource(strings = {"0.01", "0.10", "1.00", "3200.00", "9999999999999999.99"})
    @DisplayName("UT-B04: 合法金额边界通过")
    void ut_b04_validBoundariesPass(String amount) {
        assertThat(policy.isValid(amount)).isTrue();
        assertThatCode(() -> policy.validate(amount)).doesNotThrowAnyException();
    }

    @ParameterizedTest
    @ValueSource(strings = {
            "123.456",     // 超两位小数
            "-1",          // 负数
            "-0.01",       // 负数小数
            "1e10",        // 科学计数法
            "0",           // 缺两位小数
            "0.0",         // 缺两位小数
            "00.01",       // 前导零
            "10000000000000000.00", // 17 位整数超 decimal(18,2)
            "99999999999999999.99", // 整数部分超 16 位
            "abc",         // 非数字
            "",            // 空串
            "1,000.00"     // 千分位
    })
    @DisplayName("UT-B04: 非法金额报 1003")
    void ut_b04_invalidAmountsRejected(String amount) {
        assertThat(policy.isValid(amount)).isFalse();
        assertThatThrownBy(() -> policy.validate(amount))
                .isInstanceOfSatisfying(AccBusinessException.class,
                        e -> assertThat(e.code()).isEqualTo(1003));
    }

    @Test
    @DisplayName("UT-B04: null 金额报 1003")
    void ut_b04_nullRejected() {
        assertThat(policy.isValid(null)).isFalse();
        assertThatThrownBy(() -> policy.validate(null))
                .isInstanceOfSatisfying(AccBusinessException.class,
                        e -> assertThat(e.code()).isEqualTo(1003));
    }

    @Property
    boolean ut_b04_anyWellFormedAmountIsValid(@ForAll("twoDecimalAmounts") String amount) {
        return new AmountPolicy().isValid(amount);
    }

    @Provide
    Arbitrary<String> twoDecimalAmounts() {
        Arbitrary<String> integerPart = Arbitraries.longs()
                .between(0L, 9_999_999_999_999_999L)
                .map(String::valueOf);
        Arbitrary<String> decimals = Arbitraries.integers()
                .between(0, 99)
                .map(i -> String.format("%02d", i));
        return Combinators.combine(integerPart, decimals).as((i, d) -> i + "." + d);
    }
}
