package com.msz.acc.infrastructure.logging;

import com.msz.acc.domain.service.MaskingPolicy;

import java.util.function.Function;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * 日志脱敏工具（2.3，SEC-08）：对文本中的卡号/证件号/手机号脱敏，输出无明文残留。
 *
 * <p>替换顺序（按简报口径）：先 16~19 位卡号（maskBankCard），再 18 位证件号（maskIdNo），
 * 最后 11 位手机号（maskMobile）——先匹配长位段，避免手机号规则误伤长数字中的 11 位子串。
 */
public final class LogMasker {

    private static final Pattern CARD = Pattern.compile("\\d{16,19}");
    private static final Pattern ID_NO = Pattern.compile("\\d{18}");
    private static final Pattern MOBILE = Pattern.compile("\\d{11}");

    private final MaskingPolicy policy = new MaskingPolicy();

    public String mask(String text) {
        if (text == null || text.isEmpty()) {
            return text;
        }
        String result = text;
        result = replaceAll(result, CARD, policy::maskBankCard);
        result = replaceAll(result, ID_NO, policy::maskIdNo);
        result = replaceAll(result, MOBILE, policy::maskMobile);
        return result;
    }

    private static String replaceAll(String text, Pattern pattern, Function<String, String> masker) {
        Matcher matcher = pattern.matcher(text);
        StringBuilder sb = new StringBuilder();
        while (matcher.find()) {
            matcher.appendReplacement(sb, Matcher.quoteReplacement(masker.apply(matcher.group())));
        }
        matcher.appendTail(sb);
        return sb.toString();
    }
}
