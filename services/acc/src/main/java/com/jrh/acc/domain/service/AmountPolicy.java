package com.msz.acc.domain.service;

import com.msz.acc.domain.support.AccBusinessException;

import java.util.regex.Pattern;

/**
 * 金额规则：decimal(18,2) 字符串小数，防浮点误差。
 * 口径：er.md §6 通用约定（decimal(18,2) 存储、API 输出字符串小数）+ test-plan.md UT-B04。
 * 合法格式：整数部分 0 或 1~16 位（无前导零）+ "." + 恰好 2 位小数；
 * 最大 9999999999999999.99，非法报 1003（枚举或范围非法）。
 */
public final class AmountPolicy {

    private static final Pattern VALID = Pattern.compile("^(0|[1-9][0-9]{0,15})\\.[0-9]{2}$");

    /** 校验金额，非法抛 AccBusinessException(1003，枚举或范围非法)。 */
    public void validate(String amount) {
        if (!isValid(amount)) {
            throw new AccBusinessException(1003, "金额格式非法，须为两位小数且不超过 decimal(18,2)");
        }
    }

    /** 是否合法 decimal(18,2) 字符串小数。 */
    public boolean isValid(String amount) {
        return amount != null && VALID.matcher(amount).matches();
    }
}
