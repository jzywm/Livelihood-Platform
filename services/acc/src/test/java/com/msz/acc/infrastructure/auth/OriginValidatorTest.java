package com.msz.acc.infrastructure.auth;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 换发与「仅凭 Cookie 登出」的来源校验（R-A3，spec「Refresh token transport and CSRF protection」
 * Scenario「Cross-site origin is rejected」；口径修订 R-A15）。
 *
 * <p>口径（控制器裁定 R-A15「同源默认放行」）：**带** {@code Origin}/{@code Referer} 时，
 * 先与**请求自身的 scheme+host[:port]** 比对——同源直接放行；仅**跨源**才要求出现在
 * {@code acc.session.allowed-origins} 中，不在列表 → 拒绝（401 + 2001，且调用方不做任何轮换）；
 * **不带**来源头（非浏览器客户端，如移动端/服务端调用/curl 演练）→ 放行（R-A3 既有口径）。
 * 无法给出请求自身来源（{@code requestOrigin} 为空）时无法证明同源，按跨站处置（fail-closed）。</p>
 *
 * <p>为什么改口径：浏览器对 POST **一定**发送 {@code Origin}，而 {@code allowed-origins} 默认空
 * ⇒ 按现网部署件配起来「登录可用、第一次换发必 401」。同源判定不引入新的信任假设（跨站攻击者
 * 无法把自己的 Origin 伪装成受害者站点），只把「本就同源」的请求从「必配项」里解放出来。</p>
 */
class OriginValidatorTest {

    private static final String APP = "https://app.example.com";
    private static final String ADMIN = "https://admin.example.com";

    @Test
    @DisplayName("未配置允许列表：无来源头放行（非浏览器客户端）")
    void noOriginHeaderPassesWhenListEmpty() {
        assertThat(new OriginValidator("").isAllowed(null, null, APP)).isTrue();
        assertThat(new OriginValidator(null).isAllowed("", "  ", null)).isTrue();
    }

    @Test
    @DisplayName("R-A15 同源默认放行：Origin = 请求自身来源（含端口/scheme 一致）→ 放行，无需配置允许列表")
    void sameOriginOriginHeaderPassesWithEmptyAllowedList() {
        OriginValidator validator = new OriginValidator("");

        assertThat(validator.isAllowed(APP, null, APP)).isTrue();
        assertThat(validator.isAllowed("https://app.example.com:443", null, APP))
                .as("默认端口与省略写法同源（https 的 443）")
                .isTrue();
        assertThat(validator.isAllowed("HTTPS://APP.EXAMPLE.COM", null, APP + "/"))
                .as("scheme/host 大小写不敏感、末尾斜杠不影响同源判定")
                .isTrue();
        assertThat(new OriginValidator("").isAllowed("http://localhost:8080", null, "http://localhost:8080"))
                .as("本地联调（无 TLS、非默认端口）同样按同源放行")
                .isTrue();
    }

    @Test
    @DisplayName("R-A15 同源默认放行：只有 Referer 时按其 origin 判定同源")
    void sameOriginRefererPassesWithEmptyAllowedList() {
        OriginValidator validator = new OriginValidator("");

        assertThat(validator.isAllowed(null, APP + "/me/wallet", APP)).isTrue();
        assertThat(validator.isAllowed(null, "https://evil.example.com/me", APP)).isFalse();
    }

    @Test
    @DisplayName("R-A15 跨源且不在允许列表 → 拒绝（默认空列表不再拦截同源，但仍拦跨源）")
    void crossOriginRejectedWhenListEmpty() {
        OriginValidator validator = new OriginValidator("");

        assertThat(validator.isAllowed("https://evil.example.com", null, APP)).isFalse();
        assertThat(validator.isAllowed(null, "https://evil.example.com/me", APP)).isFalse();
        assertThat(validator.isAllowed(ADMIN, null, APP))
                .as("别的自有站点也是跨源：未列入允许列表即拒绝")
                .isFalse();
    }

    @Test
    @DisplayName("跨源但已配置允许列表：命中放行，未命中拒绝")
    void configuredOriginsMatchForCrossOrigin() {
        OriginValidator validator = new OriginValidator(APP + "," + ADMIN);

        assertThat(validator.isAllowed(APP, null, "https://portal.example.com")).isTrue();
        assertThat(validator.isAllowed(ADMIN, null, "https://portal.example.com")).isTrue();
        assertThat(validator.isAllowed("https://evil.example.com", null, "https://portal.example.com")).isFalse();
    }

    @Test
    @DisplayName("Origin 优先于 Referer（浏览器实际发送 Origin 时不被伪造 Referer 影响）")
    void originTakesPrecedenceOverReferer() {
        OriginValidator validator = new OriginValidator(APP);

        assertThat(validator.isAllowed("https://evil.example.com", APP + "/x", APP)).isFalse();
    }

    @Test
    @DisplayName("归一化：末尾斜杠、大小写、空白与重复分隔符不影响判定")
    void normalization() {
        OriginValidator validator = new OriginValidator(" https://App.Example.com/ , " + ADMIN + " ");

        assertThat(validator.isAllowed(APP, null, "https://portal.example.com")).isTrue();
        // scheme/host 大小写不敏感（RFC 3986）
        assertThat(validator.isAllowed("HTTPS://APP.EXAMPLE.COM", null, "https://portal.example.com")).isTrue();
        // 默认端口等价（https://a:443 == https://a），非默认端口仍参与精确比对
        assertThat(validator.isAllowed("https://app.example.com:443", null, "https://portal.example.com")).isTrue();
        assertThat(validator.isAllowed(ADMIN + "/", null, "https://portal.example.com")).isTrue();
        assertThat(validator.allowedOrigins()).containsExactlyInAnyOrder("https://app.example.com", ADMIN);
    }

    @Test
    @DisplayName("相对 Referer 无法证明同源 → 拒绝（不尝试用 Host 反推）")
    void relativeRefererRejected() {
        assertThat(new OriginValidator(APP).isAllowed(null, "/me/wallet", APP)).isFalse();
        assertThat(new OriginValidator(APP).isAllowed(null, "not a uri", APP)).isFalse();
    }

    @Test
    @DisplayName("端口参与比对：默认端口与非默认端口不互相等同")
    void portIsPartOfOrigin() {
        OriginValidator validator = new OriginValidator("https://app.example.com:8443");

        assertThat(validator.isAllowed("https://app.example.com:8443", null, "https://portal.example.com")).isTrue();
        assertThat(validator.isAllowed("https://app.example.com", null, "https://portal.example.com")).isFalse();
        assertThat(new OriginValidator("").isAllowed("https://app.example.com:8443", null, APP))
                .as("同源判定同样要求端口一致")
                .isFalse();
    }

    @Test
    @DisplayName("请求自身来源缺失（无请求上下文）→ 无法证明同源，按跨站处置（fail-closed）")
    void unknownRequestOriginFallsBackToAllowList() {
        OriginValidator empty = new OriginValidator("");
        OriginValidator configured = new OriginValidator(APP);

        assertThat(empty.isAllowed(APP, null, null)).isFalse();
        assertThat(empty.isAllowed(APP, null, "   ")).isFalse();
        assertThat(configured.isAllowed(APP, null, null))
                .as("允许列表仍可独立放行（不依赖请求上下文）")
                .isTrue();
    }
}
