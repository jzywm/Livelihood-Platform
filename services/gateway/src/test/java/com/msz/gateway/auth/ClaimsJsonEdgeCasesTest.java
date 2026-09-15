package com.msz.gateway.auth;

import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * ClaimsJson 边界分支:空容器、空白、数字形态(负数/指数/溢出)、转义、语法错误。
 */
class ClaimsJsonEdgeCasesTest {

    @Test
    void parsesEmptyContainersAndWhitespace() {
        assertThat(ClaimsJson.parseObject("{}")).isEmpty();
        assertThat(ClaimsJson.parseObject("  {  }  ")).isEmpty();
        assertThat(ClaimsJson.parseObject("{\"a\":[]}").get("a")).isEqualTo(List.of());
        assertThat(ClaimsJson.parseObject("{\"a\":{\"b\":{}}}"))
                .containsEntry("a", Map.of("b", Map.of()));
    }

    @Test
    void parsesNumberShapes() {
        Map<String, Object> claims = ClaimsJson.parseObject(
                "{\"neg\":-42,\"exp\":1e3,\"frac\":0.5,\"big\":99999999999999999999,\"zero\":0}");

        assertThat(claims.get("neg")).isEqualTo(-42L);
        assertThat(claims.get("exp")).isEqualTo(1000.0);
        assertThat(claims.get("frac")).isEqualTo(0.5);
        assertThat(claims.get("big")).isInstanceOf(Double.class);
        assertThat(claims.get("zero")).isEqualTo(0L);
    }

    @Test
    void parsesControlEscapes() {
        assertThat(ClaimsJson.parseObject("{\"s\":\"a\\nb\\tc\\bd\\fe\\rf\"}").get("s"))
                .isEqualTo("a\nb\tc\bd\fe\rf");
    }

    @Test
    void rejectsSyntaxErrors() {
        assertThatThrownBy(() -> ClaimsJson.parseObject("{\"a\" 1}"))            // 缺冒号
                .isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> ClaimsJson.parseObject("{\"a\":1 \"b\":2}"))     // 缺逗号
                .isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> ClaimsJson.parseObject("{\"a\":[1 2]}"))        // 数组缺逗号
                .isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> ClaimsJson.parseObject("{\"a\":\"unterminated}")) // 字符串未闭合
                .isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> ClaimsJson.parseObject("{1:2}"))                 // 键非字符串
                .isInstanceOf(IllegalArgumentException.class);
    }

    @Test
    void rejectsBadLiteralsAndEscapes() {
        assertThatThrownBy(() -> ClaimsJson.parseObject("{\"a\":tru}"))
                .isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> ClaimsJson.parseObject("{\"a\":nul}"))
                .isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> ClaimsJson.parseObject("{\"a\":\"\\x\"}"))
                .isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> ClaimsJson.parseObject("{\"a\":\"\\u12\"}"))
                .isInstanceOf(IllegalArgumentException.class);
    }

    @Test
    void rejectsTrailingContentAndLoneMinus() {
        assertThatThrownBy(() -> ClaimsJson.parseObject("{} trailing"))
                .isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> ClaimsJson.parseObject("{\"a\":-}"))
                .isInstanceOf(IllegalArgumentException.class);
    }
}
