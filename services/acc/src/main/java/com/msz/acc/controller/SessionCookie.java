package com.msz.acc.controller;

import jakarta.servlet.http.Cookie;
import jakarta.servlet.http.HttpServletRequest;

/**
 * 会话 Cookie 的读写与属性口径（R-A7，design D6、PDD v1.18 §8.4.1）。
 *
 * <p><b>属性</b>：`HttpOnly; Secure; SameSite=<配置>; Path=/api/v1/acc/auth; Max-Age=<refresh 有效期>`——
 * Path 限定在会话端点，使**业务接口完全不携带该 Cookie**（因此不需要全站 CSRF Token）；
 * HttpOnly 使页面脚本读不到（缓解 XSS）；Secure 使明文链路不发送；SameSite（默认 Lax）
 * 缓解 CSRF 且不打断跨站回跳。</p>
 *
 * <p><b>路径口径</b>：Path 使用**网关改写前的对外路径**（`/api/v1/acc/auth`），
 * 与 openapi 文档一致；浏览器按对外路径决定是否携带。</p>
 *
 * <p><b>手工拼 Set-Cookie</b>：Servlet 的 {@code Cookie} 不提供 SameSite，故用响应头直接写，
 * 避免为同一属性引入额外依赖。</p>
 */
public final class SessionCookie {

    /** 会话端点对外路径（网关改写前，与 openapi `Set-Cookie` 描述一致）。 */
    public static final String SESSION_PATH = "/api/v1/acc/auth";

    private final String name;
    private final boolean secure;
    private final String sameSite;
    private final String path;
    private final long maxAgeSeconds;

    private SessionCookie(String name, boolean secure, String sameSite, String path, long maxAgeSeconds) {
        this.name = name;
        this.secure = secure;
        this.sameSite = sameSite;
        this.path = path;
        this.maxAgeSeconds = maxAgeSeconds;
    }

    /** 会话端点口径（Path = {@value #SESSION_PATH}）。 */
    public static SessionCookie forSessionEndpoints(String name, boolean secure, String sameSite, String path,
                                                   long maxAgeSeconds) {
        return new SessionCookie(name == null || name.isBlank() ? "refresh_token" : name.trim(), secure,
                sameSite == null || sameSite.isBlank() ? "Lax" : sameSite.trim(), path, maxAgeSeconds);
    }

    /** 下发/覆盖长 token。 */
    public String setCookieValue(String refreshToken) {
        return build(refreshToken, maxAgeSeconds);
    }

    /** 清除长 token（登出）。 */
    public String clearCookieValue() {
        return build("", 0L);
    }

    /**
     * 从请求取长 token；缺失返回 null（只认配置的 Cookie 名，不解析其它 Cookie）。
     *
     * <p>容器在**首次访问时惰性解析** {@code Cookie} 头：Servlet 规范下即便有 Cookie 头，
     * 直接 {@code getCookies()} 也可能拿到 null（MockMvc、部分容器/异步路径均如此）。
     * 故此处以 {@code getCookies()} 为主、缺失时回退手工解析请求头——否则「有 Cookie 却判为未登录」
     * 会在换发与仅凭 Cookie 的登出上表现为随机 401（真实缺陷，由组件测试发现）。</p>
     */
    public String refreshTokenOf(HttpServletRequest request) {
        Cookie[] cookies = request.getCookies();
        if (cookies != null) {
            for (Cookie cookie : cookies) {
                if (name.equals(cookie.getName()) && cookie.getValue() != null && !cookie.getValue().isBlank()) {
                    return cookie.getValue();
                }
            }
        }
        return fromCookieHeader(request.getHeader("Cookie"));
    }

    /** 手工解析 {@code Cookie} 头（仅取配置名，不做 URL 解码——refresh 是 JWT，不含 Cookie 特殊字符）。 */
    private String fromCookieHeader(String header) {
        if (header == null || header.isBlank()) {
            return null;
        }
        for (String pair : header.split(";")) {
            String trimmed = pair.trim();
            int separator = trimmed.indexOf('=');
            if (separator <= 0) {
                continue;
            }
            if (name.equals(trimmed.substring(0, separator).trim())) {
                String value = trimmed.substring(separator + 1).trim();
                return value.isEmpty() ? null : value;
            }
        }
        return null;
    }

    /** Cookie 名（日志/排障用，不涉值）。 */
    public String name() {
        return name;
    }

    private String build(String value, long maxAge) {
        StringBuilder header = new StringBuilder()
                .append(name).append('=').append(value == null ? "" : value)
                .append("; Max-Age=").append(maxAge)
                .append("; Path=").append(path)
                .append("; HttpOnly");
        if (secure) {
            header.append("; Secure");
        }
        return header.append("; SameSite=").append(sameSite).toString();
    }
}
