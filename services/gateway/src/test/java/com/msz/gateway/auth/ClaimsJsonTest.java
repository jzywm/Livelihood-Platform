package com.msz.gateway.auth;

import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * ClaimsJson:JWT payload 最小 JSON 解析(不引 JSON 库,同 acc 手写口径)。
 */
class ClaimsJsonTest {

    @Test
    void parsesObjectWithAllValueTypes() {
        Map<String, Object> claims = ClaimsJson.parseObject(
                "{\"sub\":\"1001\",\"role\":\"CONSUMER\",\"mfa\":true,\"exp\":1750000000,\"score\":4.5,\"extra\":null,\"tags\":[\"a\",\"b\"],\"nested\":{\"k\":1}}");

        assertThat(claims.get("sub")).isEqualTo("1001");
        assertThat(claims.get("role")).isEqualTo("CONSUMER");
        assertThat(claims.get("mfa")).isEqualTo(true);
        assertThat(claims.get("exp")).isEqualTo(1750000000L);
        assertThat(claims.get("score")).isEqualTo(4.5);
        assertThat(claims).containsKey("extra");
        assertThat(claims.get("extra")).isNull();
        assertThat(claims.get("tags")).isEqualTo(List.of("a", "b"));
        assertThat(claims.get("nested")).isEqualTo(Map.of("k", 1L));
    }

    @Test
    void handlesEscapedCharacters() {
        Map<String, Object> claims = ClaimsJson.parseObject("{\"s\":\"a\\\"b\\\\c\\/d\\u0041\"}");
        assertThat(claims.get("s")).isEqualTo("a\"b\\c/dA");
    }

    @Test
    void rejectsNonObjectTopLevel() {
        assertThatThrownBy(() -> ClaimsJson.parseObject("[1,2]"))
                .isInstanceOf(IllegalArgumentException.class);
    }

    @Test
    void rejectsMalformedJson() {
        assertThatThrownBy(() -> ClaimsJson.parseObject("{\"a\":1,"))
                .isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> ClaimsJson.parseObject("not-json"))
                .isInstanceOf(IllegalArgumentException.class);
    }
}
