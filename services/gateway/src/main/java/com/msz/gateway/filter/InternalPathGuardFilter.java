package com.msz.gateway.filter;

import com.msz.common.api.ErrorCode;
import com.msz.gateway.config.GatewayProperties;
import com.msz.gateway.error.EnvelopeResponses;
import org.springframework.cloud.gateway.filter.GatewayFilterChain;
import org.springframework.cloud.gateway.filter.GlobalFilter;
import org.springframework.core.Ordered;
import org.springframework.http.HttpStatus;
import org.springframework.web.server.ServerWebExchange;
import reactor.core.publisher.Mono;

import java.util.List;

/**
 * 内部接口守卫(order 5):服务端间接口(x-external-interfaces,内部 Token 鉴权)
 * 不暴露于网关——命中 {@code gateway.internal-paths} 前缀直接 404(错误码 3006)。
 * 注:SCG 4.3 路由定义不支持 negate 谓词,故用显式守卫实现"天然不可达";
 * 路径按「改写前」原始入口路径判断(见 {@link RequestPaths})。
 */
public final class InternalPathGuardFilter implements GlobalFilter, Ordered {

    public static final int ORDER = 5;

    private static final org.slf4j.Logger log = org.slf4j.LoggerFactory.getLogger(InternalPathGuardFilter.class);

    private final List<String> internalPaths;
    private final EnvelopeResponses responses;

    public InternalPathGuardFilter(GatewayProperties properties, EnvelopeResponses responses) {
        this.internalPaths = properties.internalPaths() == null
                ? List.of() : List.copyOf(properties.internalPaths());
        this.responses = responses;
    }

    @Override
    public Mono<Void> filter(ServerWebExchange exchange, GatewayFilterChain chain) {
        String path = RequestPaths.of(exchange);
        if (internalPaths.stream().anyMatch(prefix -> RequestPaths.matchesPrefix(path, prefix))) {
            // 直接写出 404+3006(短路,不抛异常——避免被网关级熔断计为下游失败)
            log.warn("内部接口经网关访问被拒 uri={}", path);
            return responses.write(exchange, HttpStatus.NOT_FOUND, ErrorCode.OBJECT_NOT_FOUND);
        }
        return chain.filter(exchange);
    }

    @Override
    public int getOrder() {
        return ORDER;
    }
}
