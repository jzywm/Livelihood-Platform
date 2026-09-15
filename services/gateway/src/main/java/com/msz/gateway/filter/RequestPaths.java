package com.msz.gateway.filter;

import org.springframework.web.server.ServerWebExchange;

import java.util.ArrayList;
import java.util.List;

/**
 * 统一入口原始路径保留。
 *
 * <p>路由级 RewritePath 在过滤链中较早执行(把 {@code /api/v1/{svc}/**} 改写成 {@code /{svc}/**}), 而白名单、
 * 限流分级、内部路径守卫都必须按「改写前」的入口路径判断,故由 {@link TraceIdFilter}(order -10,链最前端)
 * 落盘一次,后续读取;与路由过滤器执行顺序解耦。</p>
 */
public final class RequestPaths {

    public static final String ORIGINAL_PATH_ATTR = "gateway.originalPath";

    private RequestPaths() {
    }

    /** 记录原始入口路径(幂等:仅首次写入)。 */
    public static ServerWebExchange preserve(ServerWebExchange exchange) {
        exchange.getAttributes().putIfAbsent(ORIGINAL_PATH_ATTR, exchange.getRequest().getPath().value());
        return exchange;
    }

    /** 读取原始入口路径;未记录时回退为当前请求路径。 */
    public static String of(ServerWebExchange exchange) {
        Object value = exchange.getAttribute(ORIGINAL_PATH_ATTR);
        if (value instanceof String path && !path.isEmpty()) {
            return path;
        }
        return exchange.getRequest().getPath().value();
    }

    /**
     * 路径规范化:拒绝路径混淆(审查 C2)。
     *
     * <p>WebFlux 的 {@code getPath().value()} 保留 {@code /./}、{@code /../}、{@code //} 与百分号编码,
     * 而 SCG 的 {@code Path} 谓词对它们仍然命中路由——若直接用原始路径做守卫/白名单判断,
     * 攻击者可用 {@code /api/v1/acc/./internal/...} 绕过内部接口拦截,或用
     * {@code /api/v1/acc/registerAny} 蹭白名单。故在链最前端统一规范化。</p>
     *
     * @return 规范化路径;返回 {@code null} 表示可疑输入(调用方按 404 处理)
     */
    public static String canonicalize(String rawPath) {
        if (rawPath == null || rawPath.isEmpty() || rawPath.charAt(0) != '/') {
            return null;
        }
        String[] segments = rawPath.split("/", -1);
        List<String> kept = new ArrayList<>();
        for (int i = 0; i < segments.length; i++) {
            String segment = segments[i];
            if (segment.isEmpty()) {
                boolean leading = i == 0;
                boolean trailing = i == segments.length - 1;
                if (leading || trailing) {
                    continue; // 允许首/尾斜杠(尾部斜杠归一化)
                }
                return null; // 中间空段 = "//"
            }
            String decoded;
            try {
                decoded = percentDecode(segment);
            } catch (IllegalArgumentException e) {
                return null; // 非法百分号编码
            }
            if (".".equals(decoded) || "..".equals(decoded)) {
                return null; // 目录穿越
            }
            if (decoded.indexOf('/') >= 0 || decoded.indexOf('\\') >= 0) {
                return null; // 编码斜杠
            }
            kept.add(segment);
        }
        return kept.isEmpty() ? "/" : "/" + String.join("/", kept);
    }

    /**
     * 段边界前缀匹配:命中 {@code prefix} 本身或其子路径,避免 {@code /registerAny} 蹭 {@code /register} 白名单。
     */
    public static boolean matchesPrefix(String path, String prefix) {
        if (path == null || prefix == null || prefix.isEmpty()) {
            return false;
        }
        String base = prefix.endsWith("/") ? prefix.substring(0, prefix.length() - 1) : prefix;
        if (base.isEmpty()) {
            return true; // prefix = "/",匹配全部
        }
        return path.equals(base) || path.startsWith(base + "/");
    }

    private static String percentDecode(String segment) {
        if (segment.indexOf('%') < 0) {
            return segment;
        }
        StringBuilder decoded = new StringBuilder(segment.length());
        for (int i = 0; i < segment.length(); i++) {
            char c = segment.charAt(i);
            if (c != '%') {
                decoded.append(c);
                continue;
            }
            if (i + 2 >= segment.length()) {
                throw new IllegalArgumentException("百分号编码不完整");
            }
            int high = Character.digit(segment.charAt(i + 1), 16);
            int low = Character.digit(segment.charAt(i + 2), 16);
            if (high < 0 || low < 0) {
                throw new IllegalArgumentException("百分号编码非法");
            }
            decoded.append((char) ((high << 4) + low));
            i += 2;
        }
        return decoded.toString();
    }
}
