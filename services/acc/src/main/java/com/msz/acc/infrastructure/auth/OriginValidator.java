package com.msz.acc.infrastructure.auth;

import java.net.URI;
import java.net.URISyntaxException;
import java.util.LinkedHashSet;
import java.util.Locale;
import java.util.Set;

/**
 * 换发 / 仅凭 Cookie 登出的**来源校验**（R-A3，spec「Refresh token transport and CSRF protection」）。
 *
 * <p>规则（控制器必须在**调用任何会话流程之前**执行）：</p>
 * <ol>
 *   <li>请求**不带** {@code Origin} 且不带 {@code Referer} → 放行（非浏览器客户端：移动端、
 *       服务端到服务端、命令行联调）。</li>
 *   <li>带 {@code Origin} → 取其值比对允许列表（{@code acc.session.allowed-origins}，逗号分隔）。</li>
 *   <li>无 {@code Origin} 但有 {@code Referer} → 取 Referer 的 {@code scheme://host[:port]} 再比对。</li>
 *   <li>不匹配 → 拒绝（401 + 2001）。允许列表为空 = **仅同源**：此时任何显式来源头都不匹配，
 *       因为「同源」需要与请求自身的 Host 比对，而经网关转发后 Host 已被改写、不可信——
 *       无法证明同源时按跨站处置（fail-closed）。</li>
 * </ol>
 *
 * <p>比对**大小写不敏感**并容忍末尾斜杠与首尾空白；端口参与比对（{@code https://a} 与
 * {@code https://a:8443} 不同源）。相对 Referer（非绝对 URI）一律拒绝，不做 Host 反推。</p>
 */
public final class OriginValidator {

    private final Set<String> allowedOrigins;

    public OriginValidator(String allowedOrigins) {
        this.allowedOrigins = parse(allowedOrigins);
    }

    /** 是否放行本次请求的来源。 */
    public boolean isAllowed(String origin, String referer) {
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
        return allowedOrigins.contains(candidate);
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

    /** 归一化配置项/请求 Origin：去末尾斜杠、转小写。 */
    private static String normalizeOrigin(String value) {
        String trimmed = value.trim();
        while (trimmed.endsWith("/")) {
            trimmed = trimmed.substring(0, trimmed.length() - 1);
        }
        return trimmed.toLowerCase(Locale.ROOT);
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
