package com.msz.acc.infrastructure.logging;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * SEC-08：日志脱敏——证件号(18 位,前4后4)优先 → 卡号(15~19 位,前4后3) → 手机号(11 位,前3后4)；
 * 混合文本全部脱敏，输出不含原明文（Fix round 1：证件号优先，对齐 er.md §6.1/§6.4）。
 */
class LogMaskerTest {

    private final LogMasker masker = new LogMasker();

    @Test
    @DisplayName("SEC-08 混合文本全部脱敏：证件号前4后4、卡号前4后3、手机号前3后4，无明文残留")
    void ut_mixedTextAllMaskedNoPlaintext() {
        String mobile = "13812345678";
        String idNo = "110101199001011234";
        String card = "6222021234567890";
        String text = "注册手机 " + mobile + "，证件号 " + idNo + "，卡号 " + card;

        String masked = masker.mask(text);

        assertThat(masked).doesNotContain(mobile, idNo, card);
        // 18 位证件号：前 4 后 4（不得被卡号前 4 后 3 抢先）
        assertThat(masked).contains("1101**********1234");
        // 16 位卡号：前 4 后 3
        assertThat(masked).contains("6222*********890");
        // 11 位手机号：前 3 后 4
        assertThat(masked).contains("138****5678");
    }

    @Test
    @DisplayName("SEC-08 18 位证件号脱敏为前4后4")
    void ut_idNoMaskedFormat() {
        assertThat(masker.mask("110101199001011234")).isEqualTo("1101**********1234");
    }

    @Test
    @DisplayName("SEC-08 16 位卡号脱敏为前4后3")
    void ut_bankCardMaskedFormat() {
        assertThat(masker.mask("6222021234567890")).isEqualTo("6222*********890");
    }

    @Test
    @DisplayName("SEC-08 11 位手机号脱敏为前3后4（138****8000 格式）")
    void ut_mobileMaskedFormat() {
        assertThat(masker.mask("13812348000")).isEqualTo("138****8000");
    }
}
