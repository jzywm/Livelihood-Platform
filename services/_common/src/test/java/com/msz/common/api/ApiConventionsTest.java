package com.msz.common.api;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 1.1 幂等键与分页约定常量断言。
 */
class ApiConventionsTest {

    @Test
    @DisplayName("1.1: 幂等键头与分页常量")
    void ut_api_conventions_constants() {
        assertThat(ApiConventions.IDEMPOTENCY_KEY_HEADER).isEqualTo("Idempotency-Key");
        assertThat(ApiConventions.DEFAULT_PAGE).isEqualTo(1);
        assertThat(ApiConventions.DEFAULT_PAGE_SIZE).isEqualTo(20);
        assertThat(ApiConventions.MAX_PAGE_SIZE).isEqualTo(100);
    }
}
