package com.msz.gateway.filter;

import org.springframework.cloud.gateway.filter.GatewayFilterChain;
import org.springframework.cloud.gateway.filter.GlobalFilter;
import org.springframework.core.Ordered;
import org.springframework.core.io.buffer.DataBuffer;
import org.springframework.http.server.reactive.ServerHttpRequest;
import org.springframework.http.server.reactive.ServerHttpResponseDecorator;
import org.springframework.web.server.ServerWebExchange;
import reactor.core.publisher.Mono;

import java.util.UUID;

/**
 * traceId 注入(F5):请求缺失 {@code X-Request-Id} 时 UUID 兜底(与 acc TraceIds 同口径),
 * 注入请求并回写响应头,保证全链路日志串链。
 *
 * <p>order = -10:鉴权链最前端,任何后续 Filter/路由抛错时错误响应也携带同一 traceId。</p>
 */
public final class TraceIdFilter implements GlobalFilter, Ordered {

    public static final String TRACE_ID_HEADER = "X-Request-Id";
    public static final int ORDER = -10;

    /** 合法 traceId:1~64 位字母/数字/点/下划线/连字符(与 UUID、SkyWalking 口径兼容)。 */
    private static final java.util.regex.Pattern TRACE_ID_PATTERN =
            java.util.regex.Pattern.compile("[A-Za-z0-9._-]{1,64}");

    @Override
    public Mono<Void> filter(ServerWebExchange exchange, GatewayFilterChain chain) {
        String incoming = exchange.getRequest().getHeaders().getFirst(TRACE_ID_HEADER);
        // 只采纳格式合法的客户端 traceId(审查 I14:避免日志/链路投毒),否则 UUID 兜底
        String traceId = (incoming != null && TRACE_ID_PATTERN.matcher(incoming).matches())
                ? incoming
                : UUID.randomUUID().toString();
        String finalTraceId = traceId;

        ServerHttpRequest mutatedRequest = exchange.getRequest().mutate()
                .header(TRACE_ID_HEADER, finalTraceId)
                .build();
        ServerHttpResponseDecorator decoratedResponse = new ServerHttpResponseDecorator(exchange.getResponse()) {
            @Override
            public Mono<Void> writeWith(org.reactivestreams.Publisher<? extends DataBuffer> body) {
                if (getHeaders().getFirst(TRACE_ID_HEADER) == null) {
                    getHeaders().add(TRACE_ID_HEADER, finalTraceId);
                }
                return super.writeWith(body);
            }

            @Override
            public Mono<Void> writeAndFlushWith(
                    org.reactivestreams.Publisher<? extends org.reactivestreams.Publisher<? extends DataBuffer>> body) {
                if (getHeaders().getFirst(TRACE_ID_HEADER) == null) {
                    getHeaders().add(TRACE_ID_HEADER, finalTraceId);
                }
                return super.writeAndFlushWith(body);
            }
        };

        ServerWebExchange traced = exchange.mutate()
                .request(mutatedRequest)
                .response(decoratedResponse)
                .build();
        // 链最前端落盘原始入口路径(路由 RewritePath 之后仍可读取,见 RequestPaths)
        RequestPaths.preserve(traced);
        return chain.filter(traced);
    }

    @Override
    public int getOrder() {
        return ORDER;
    }
}
