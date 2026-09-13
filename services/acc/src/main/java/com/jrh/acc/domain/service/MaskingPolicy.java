package com.msz.acc.domain.service;

/**
 * 脱敏策略。
 * 口径：er.md §3/§6.1/§7.4 脱敏示例（138****8000 / 张*三 / 1301**********1234 / 6222********890）
 * + test-plan.md UT-F02。
 */
public final class MaskingPolicy {

    /** 手机号：138****8000（保留前 3 后 4）。 */
    public String maskMobile(String mobile) {
        if (mobile == null || mobile.isEmpty()) {
            return mobile;
        }
        if (mobile.length() >= 7) {
            return mobile.substring(0, 3) + "****" + mobile.substring(mobile.length() - 4);
        }
        return maskMiddle(mobile);
    }

    /** 姓名：张*三（3 字及以上）/ 张*（2 字）/ 单字原样。 */
    public String maskName(String name) {
        if (name == null || name.isEmpty()) {
            return name;
        }
        return maskMiddle(name);
    }

    /** 证件号：1301**********1234（保留前 4 后 4）。 */
    public String maskIdNo(String idNo) {
        if (idNo == null || idNo.isEmpty()) {
            return idNo;
        }
        if (idNo.length() >= 8) {
            return idNo.substring(0, 4)
                    + "*".repeat(idNo.length() - 8)
                    + idNo.substring(idNo.length() - 4);
        }
        return maskMiddle(idNo);
    }

    /** 银行卡号：6222*********890（保留前 4 后 3）。 */
    public String maskBankCard(String card) {
        if (card == null || card.isEmpty()) {
            return card;
        }
        if (card.length() >= 7) {
            return card.substring(0, 4)
                    + "*".repeat(card.length() - 7)
                    + card.substring(card.length() - 3);
        }
        return maskMiddle(card);
    }

    /** 通用中段脱敏：2 字 → 首字+*；3 字及以上 → 首字 + *(len-2) + 尾字。 */
    private String maskMiddle(String value) {
        if (value.length() == 1) {
            return value;
        }
        if (value.length() == 2) {
            return value.charAt(0) + "*";
        }
        return value.charAt(0) + "*".repeat(value.length() - 2) + value.charAt(value.length() - 1);
    }
}
