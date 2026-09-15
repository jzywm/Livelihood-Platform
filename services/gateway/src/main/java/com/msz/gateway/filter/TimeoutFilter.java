package com.msz.gateway.filter;

import com.msz.gateway.config.GatewayProperties;
import org.springframework.cloud.gateway.filter.GatewayFilterChain;
import org.springframework.cloud.gateway.filter.GlobalFilter;
import org.springframework.cloud.gateway.route.Route;
import org.springframework.cloud.gateway.support.ServerWebExchangeUtils;
import org.springframework.core.Ordered;
import org.springframework.web.server.ServerWebExchange;
import reactor.core.publisher.Mono;

import java.time.Duration;
import java.util.concurrent.TimeoutException;

/**
 * 路由级超时(F4,order 100):读取路由 metadata.timeout(毫秒)对下游链路施加超时,
 * 缺省用 GatewayProperties.DEFAULT_TIMEOUT_MS(内部服务 1s 分级);
 * 超时 → TimeoutException → 统一 503+5002(由 GlobalErrorWebExceptionHandler 映射)。
 */
public final class TimeoutFilter implements GlobalFilter, Ordered {

    public static final int ORDER = 100;
    public static final String METADATA_TIMEOUT = "timeout";

    private static final org.slf4j.Logger log = org.slf4j.LoggerFactory.getLogger(TimeoutFilter.class);

    @Override
    public Mono<Void> filter(ServerWebExchange exchange, GatewayFilterChain chain) {
        long timeoutMillis = timeoutMillis(exchange);
        return chain.filter(exchange)
                .timeout(Duration.ofMillis(timeoutMillis),
                        Mono.error(new TimeoutException("路由超时 " + timeoutMillis + "ms")));
    }

    private long timeoutMillis(ServerWebExchange exchange) {
        Route route = exchange.getAttribute(ServerWebExchangeUtils.GATEWAY_ROUTE_ATTR);
        if (route == null || route.getMetadata() == null) {
            return GatewayProperties.DEFAULT_TIMEOUT_MS;
        }
        Object value = route.getMetadata().get(METADATA_TIMEOUT);
        if (value == null) {
            return GatewayProperties.DEFAULT_TIMEOUT_MS;
        }
        long parsed = parseTimeout(value);
        if (parsed <= 0) {
            // 值域非法(非数字 / 0 / 负数)→ 回退默认,绝不因配置错误让某条路由全量立即超时或 500
            log.warn("路由 [{}] metadata.timeout 非法({}),回退默认 {}ms",
                    route.getId(), value, GatewayProperties.DEFAULT_TIMEOUT_MS);
            return GatewayProperties.DEFAULT_TIMEOUT_MS;
        }
        return parsed;
    }

    private long parseTimeout(Object value) {
        if (value instanceof Number number) {
            return number.longValue();
        }
        try {
            return Long.parseLong(String.valueOf(value).trim());
        } catch (NumberFormatException e) {
            return -1;
        }
    }

    @Override
    public int getOrder() {
        return ORDER;
    }
}
