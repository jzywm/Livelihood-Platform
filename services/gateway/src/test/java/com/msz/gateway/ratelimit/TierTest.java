package com.msz.gateway.ratelimit;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 限流分级边界:AI / 资金(settle、acc/funds)/ 写 / 读,以及 key 命名。
 */
class TierTest {

    @Test
    void classifiesAiPaths() {
        assertThat(Tier.of("/api/v1/assist/chat", "GET")).isEqualTo(Tier.AI);
        assertThat(Tier.of("/api/v1/aicore/ocr", "POST")).isEqualTo(Tier.AI);
    }

    @Test
    void classifiesFundsPathsBeforeWrite() {
        assertThat(Tier.of("/api/v1/settle/payout", "POST")).isEqualTo(Tier.FUNDS);
        assertThat(Tier.of("/api/v1/acc/funds/audit", "GET")).isEqualTo(Tier.FUNDS);
    }

    @Test
    void classifiesWriteMethods() {
        for (String method : new String[]{"POST", "PUT", "PATCH", "DELETE"}) {
            assertThat(Tier.of("/api/v1/acc/account/close", method)).isEqualTo(Tier.WRITE);
        }
    }

    @Test
    void defaultsToRead() {
        assertThat(Tier.of("/api/v1/acc/me", "GET")).isEqualTo(Tier.READ);
        assertThat(Tier.of("/api/v1/acc/me", "OPTIONS")).isEqualTo(Tier.READ);
        assertThat(Tier.of("/api/v1/acc/me", "")).isEqualTo(Tier.READ);
    }

    @Test
    void exposesLowercaseKey() {
        assertThat(Tier.AI.key()).isEqualTo("ai");
        assertThat(Tier.FUNDS.key()).isEqualTo("funds");
        assertThat(Tier.WRITE.key()).isEqualTo("write");
        assertThat(Tier.READ.key()).isEqualTo("read");
    }
}
