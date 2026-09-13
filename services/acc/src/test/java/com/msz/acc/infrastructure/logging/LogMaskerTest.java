package com.msz.acc.infrastructure.logging;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * SEC-08：日志脱敏——混合文本中手机号/证件号/卡号全部脱敏，输出不含原明文。
 */
class LogMaskerTest {

    private final LogMasker masker = new LogMasker();

    @Test
    @DisplayName("SEC-08 混合文本全部脱敏，无明文残留")
    void ut_mixedTextAllMaskedNoPlaintext() {
        String mobile = "13812345678";
        String idNo = "110101199001011234";
        String card = "6222021234567890";
        String text = "注册手机 " + mobile + "，证件号 " + idNo + "，卡号 " + card;

        String masked = masker.mask(text);

        assertThat(masked).doesNotContain(mobile, idNo, card);
        assertThat(masked).contains("138****5678");
        assertThat(masked).contains("6222*********890");
    }

    @Test
    @DisplayName("SEC-08 手机号脱敏格式 138****5678")
    void ut_mobileMaskedFormat() {
        assertThat(masker.mask("13812345678")).isEqualTo("138****5678");
    }

    @Test
    @DisplayName("SEC-08 卡号脱敏格式 6222********890（保留前 4 后 3）")
    void ut_bankCardMaskedFormat() {
        assertThat(masker.mask("6222021234567890")).isEqualTo("6222*********890");
    }
}
