package com.msz.acc.infrastructure.auth;

import java.net.URI;
import java.net.URISyntaxException;
import java.util.LinkedHashSet;
import java.util.Locale;
import java.util.Set;

/**
 * 换发 / 仅凭 Cookie 登出的**来源校验**（R-A3 + R-A15，spec「Refresh token transport and CSRF protection」）。
 *
 * <p>规则（控制器必须在**调用任何会话流程之前**执行）：</p>
 * <ol>
 *   <li>请求**不带** {@code Origin} 且不带 {@code Referer} → 放行（非浏览器客户端：移动端、
 *       服务端到服务端、命令行联调）。</li>
 *   <li>带来源头 → 先与**请求自身的 scheme+host[:port]**（{@code requestOrigin}）比对：
 *       **同源直接放行**（R-A15）——浏览器对 POST 一定发送 {@code Origin}，若同源也要配允许列表，
 *       则默认部署下「登录可用、第一次换发必 401」。</li>
 *   <li>**跨源**才要求出现在允许列表 {@code acc.session.allowed-origins}（逗号分隔）；
 *       不在列表 → 拒绝（401 + 2001）。</li>
 *   <li>无 {@code Origin} 但有 {@code Referer} → 取 Referer 的 {@code scheme://host[:port]}
 *       按上述同源/跨源口径判定。</li>
 *   <li>带着来源头却无法归一化为 origin（相对 Referer / 非法 URI），或**给不出请求自身来源**
 *       （无请求上下文）→ 无法证明同源，按跨站处置（fail-closed）。</li>
 * </ol>
 *
 * <p>比对**大小写不敏感**并容忍末尾斜杠与首尾空白；端口参与比对（{@code https://a} 与
 * {@code https://a:8443} 不同源），默认端口与省略写法等价（{@code https://a:443} == {@code https://a}）。
 * 相对 Referer（非绝对 URI）一律拒绝，不做 Host 反推。</p>
 *
 * <p><b>为什么同源判定不削弱 CSRF 防护</b>：同源与否取决于「浏览器实际发出请求的站点」与
 * 「请求自身来源」是否一致，跨站攻击者无法把受害者站点的 Origin 塞进自己的请求（Origin 由浏览器
 * 按真实发起方设置，页面脚本不可改写）。而 {@code requestOrigin} 由控制器从请求本身
 * （含入口/网关写入的 {@code X-Forwarded-*}}）构造，见 {@code AuthController#requestOrigin}。</p>
 */
public final class OriginValidator {

    private final Set<String> allowedOrigins;

    public OriginValidator(String allowedOrigins) {
        this.allowedOrigins = parse(allowedOrigins);
    }

    /**
     * 是否放行本次请求的来源。
     *
     * @param origin        请求的 {@code Origin} 头（可空）
     * @param referer       请求的 {@code Referer} 头（可空）
     * @param requestOrigin 请求自身来源 {@code scheme://host[:port]}（可空 = 无请求上下文，
     *                      此时无法证明同源，按跨站处置）
     */
    public boolean isAllowed(String origin, String referer, String requestOrigin) {
        boolean originPresent = origin != null && !origin.isBlank();
        boolean refererPresent = referer != null && !referer.isBlank();
        if (!originPresent && !refererPresent) {
            // 既无 Origin 也无 Referer：非浏览器客户端，放行（CSRF 依赖浏览器自动携带 Cookie）
            return true;
        }
        String candidate = resolveCandidate(origin, referer);
        if (candidate == null) {
            // 带了来源头但无法归一化为 origin（相对 Referer / 非法 URI）→ 无法证明同源，按跨站处置
            return false;
        }
        // R-A15：同源默认放行（Origin 与请求自身来源一致时无需配置允许列表）
        if (isSameOrigin(candidate, requestOrigin)) {
            return true;
        }
        return allowedOrigins.contains(candidate);
    }

    /** 同源判定：请求自身来源已知、且与来源头归一化后逐字相等。 */
    private static boolean isSameOrigin(String candidate, String requestOrigin) {
        if (requestOrigin == null || requestOrigin.isBlank()) {
            // 无请求上下文（例如纯函数调用）：无法证明同源 → 交由允许列表判定
            return false;
        }
        String self = normalizeOrigin(requestOrigin);
        return !self.isEmpty() && self.equals(candidate);
    }

    /** 允许列表（归一化后的只读视图，供启动日志/排障）。 */
    public Set<String> allowedOrigins() {
        return Set.copyOf(allowedOrigins);
    }

    /** 解析请求来源：Origin 优先；否则用 Referer 的 origin 部分；无法判定时返回 null。 */
    private static String resolveCandidate(String origin, String referer) {
        if (origin != null && !origin.isBlank()) {
            return normalizeOrigin(origin.trim());
        }
        if (referer == null || referer.isBlank()) {
            return null;
        }
        return originOf(referer.trim());
    }

    /** 从 Referer 提取 origin（相对 URI/非法 URI 返回 null → 调用方按拒绝处置）。 */
    private static String originOf(String referer) {
        try {
            URI uri = new URI(referer);
            if (uri.getScheme() == null || uri.getHost() == null) {
                return null;
            }
            StringBuilder origin = new StringBuilder()
                    .append(uri.getScheme().toLowerCase(Locale.ROOT))
                    .append("://")
                    .append(uri.getHost().toLowerCase(Locale.ROOT));
            if (uri.getPort() > 0) {
                origin.append(':').append(uri.getPort());
            }
            return origin.toString();
        } catch (URISyntaxException e) {
            return null;
        }
    }

    /** 归一化配置项/请求 Origin：去末尾斜杠、转小写、默认端口与省略写法等价。 */
    private static String normalizeOrigin(String value) {
        String trimmed = value.trim();
        while (trimmed.endsWith("/")) {
            trimmed = trimmed.substring(0, trimmed.length() - 1);
        }
        return stripDefaultPort(trimmed.toLowerCase(Locale.ROOT));
    }

    /** 去掉默认端口（https→443、http→80）：{@code https://a:443} 与 {@code https://a} 是同一个来源。 */
    private static String stripDefaultPort(String origin) {
        if (origin.startsWith("https://") && origin.endsWith(":443")) {
            return origin.substring(0, origin.length() - 4);
        }
        if (origin.startsWith("http://") && origin.endsWith(":80")) {
            return origin.substring(0, origin.length() - 3);
        }
        return origin;
    }

    private static Set<String> parse(String configured) {
        Set<String> parsed = new LinkedHashSet<>();
        if (configured == null || configured.isBlank()) {
            return parsed;
        }
        for (String item : configured.split(",")) {
            if (!item.isBlank()) {
                parsed.add(normalizeOrigin(item));
            }
        }
        return parsed;
    }
}
