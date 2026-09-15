package com.msz.gateway.ratelimit;

import org.springframework.http.HttpMethod;

import java.util.Locale;

/**
 * 限流分级:AI(助手/AI 路径)> 资金(结算/资金路径)> 写 > 读。
 */
public enum Tier {
    AI, FUNDS, WRITE, READ;

    public static Tier of(String path, String method) {
        if (path.startsWith("/api/v1/assist") || path.startsWith("/api/v1/aicore")) {
            return AI;
        }
        if (path.startsWith("/api/v1/settle") || path.startsWith("/api/v1/acc/funds")) {
            return FUNDS;
        }
        if (HttpMethod.POST.matches(method) || HttpMethod.PUT.matches(method)
                || HttpMethod.PATCH.matches(method) || HttpMethod.DELETE.matches(method)) {
            return WRITE;
        }
        return READ;
    }

    public String key() {
        return name().toLowerCase(Locale.ROOT);
    }
}
