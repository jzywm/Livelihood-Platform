package com.msz.acc.infrastructure.auth;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 换发与「仅凭 Cookie 登出」的来源校验（R-A3，spec「Refresh token transport and CSRF protection」
 * Scenario「Cross-site origin is rejected」）。
 *
 * <p>口径：**带** {@code Origin}/{@code Referer} 且不在允许列表 → 拒绝（401 + 2001，且调用方
 * 不做任何轮换）；**不带**来源头（非浏览器客户端，如移动端/服务端调用）→ 放行；
 * {@code acc.session.allowed-origins} 为空 = **仅同源**（相对来源不做同源推断，一律拒绝——
 * 无法证明同源时按跨站处置）。</p>
 */
class OriginValidatorTest {

    private static final String APP = "https://app.example.com";
    private static final String ADMIN = "https://admin.example.com";

    @Test
    @DisplayName("未配置允许列表：无来源头放行（非浏览器客户端）")
    void noOriginHeaderPassesWhenListEmpty() {
        assertThat(new OriginValidator("").isAllowed(null, null)).isTrue();
        assertThat(new OriginValidator(null).isAllowed("", "  ")).isTrue();
    }

    @Test
    @DisplayName("未配置允许列表：带来源头一律拒绝（默认仅同源，无法证明同源即按跨站处置）")
    void anyOriginRejectedWhenListEmpty() {
        OriginValidator validator = new OriginValidator("");

        assertThat(validator.isAllowed(APP, null)).isFalse();
        assertThat(validator.isAllowed(null, APP + "/me/wallet")).isFalse();
        assertThat(validator.isAllowed("https://app.example.com", null)).isFalse();
    }

    @Test
    @DisplayName("配置允许列表：Origin 命中放行，未命中拒绝")
    void configuredOriginsMatch() {
        OriginValidator validator = new OriginValidator(APP + "," + ADMIN);

        assertThat(validator.isAllowed(APP, null)).isTrue();
        assertThat(validator.isAllowed(ADMIN, null)).isTrue();
        assertThat(validator.isAllowed("https://evil.example.com", null)).isFalse();
    }

    @Test
    @DisplayName("Origin 缺失时回退 Referer：取其 scheme://host[:port] 再比对")
    void refererFallsBackToItsOrigin() {
        OriginValidator validator = new OriginValidator(APP);

        assertThat(validator.isAllowed(null, APP + "/me/wallet?tab=1")).isTrue();
        assertThat(validator.isAllowed(null, "https://evil.example.com/me")).isFalse();
    }

    @Test
    @DisplayName("Origin 优先于 Referer（浏览器实际发送 Origin 时不被伪造 Referer 影响）")
    void originTakesPrecedenceOverReferer() {
        OriginValidator validator = new OriginValidator(APP);

        assertThat(validator.isAllowed("https://evil.example.com", APP + "/x")).isFalse();
    }

    @Test
    @DisplayName("归一化：末尾斜杠、大小写、空白与重复分隔符不影响判定")
    void normalization() {
        OriginValidator validator = new OriginValidator(" https://App.Example.com/ , " + ADMIN + " ");

        assertThat(validator.isAllowed("https://app.example.com", null)).isTrue();
        // scheme/host 大小写不敏感（RFC 3986）；路径与端口仍参与精确比对
        assertThat(validator.isAllowed("HTTPS://APP.EXAMPLE.COM", null)).isTrue();
        assertThat(validator.isAllowed(ADMIN + "/", null)).isTrue();
        assertThat(validator.allowedOrigins()).containsExactlyInAnyOrder("https://app.example.com", ADMIN);
    }

    @Test
    @DisplayName("相对 Referer 无法证明同源 → 拒绝（不尝试用 Host 反推）")
    void relativeRefererRejected() {
        assertThat(new OriginValidator(APP).isAllowed(null, "/me/wallet")).isFalse();
        assertThat(new OriginValidator(APP).isAllowed(null, "not a uri")).isFalse();
    }

    @Test
    @DisplayName("端口参与比对：默认端口与非默认端口不互相等同")
    void portIsPartOfOrigin() {
        OriginValidator validator = new OriginValidator("https://app.example.com:8443");

        assertThat(validator.isAllowed("https://app.example.com:8443", null)).isTrue();
        assertThat(validator.isAllowed("https://app.example.com", null)).isFalse();
    }
}
