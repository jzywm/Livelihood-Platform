package com.msz.common.api;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 1.1 PageResult 分页结果字段装配断言。
 */
class PageResultTest {

    @Test
    @DisplayName("1.1: PageResult 分页字段装配正确")
    void ut_page_result_fields() {
        PageResult<String> page = new PageResult<>(List.of("a", "b"), 42L, 1, 20);
        assertThat(page.list()).containsExactly("a", "b");
        assertThat(page.total()).isEqualTo(42L);
        assertThat(page.page()).isEqualTo(1);
        assertThat(page.pageSize()).isEqualTo(20);
    }
}
