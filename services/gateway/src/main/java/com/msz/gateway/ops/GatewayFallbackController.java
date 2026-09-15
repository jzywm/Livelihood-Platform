package com.msz.gateway.ops;

import com.msz.common.api.Envelope;
import com.msz.common.api.ErrorCode;
import com.msz.gateway.filter.TraceIdFilter;
import org.springframework.cloud.gateway.support.ServerWebExchangeUtils;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ServerWebExchange;
import reactor.core.publisher.Mono;

import java.util.UUID;

/**
 * 熔断降级端点(F4):Spring Cloud Gateway CircuitBreaker 过滤器经
 * {@code fallbackUri: forward:/gateway-fallback} 指向本端点——下游熔断打开时快速失败
 * 503+5002,并带 {@link #FALLBACK_HEADER} 标记头(与普通错误响应区分,便于运维识别降级)。
 */
@RestController
public class GatewayFallbackController {

    public static final String FALLBACK_HEADER = "X-Gateway-Fallback";
    public static final String PATH = "/gateway-fallback";

    private static final org.slf4j.Logger log = org.slf4j.LoggerFactory.getLogger(GatewayFallbackController.class);

    @GetMapping(PATH)
    public Mono<ResponseEntity<Envelope<Void>>> fallback(ServerWebExchange exchange) {
        // 仅接受网关内部的 forward(熔断过滤器 fallbackUri=forward:/gateway-fallback);
        // 外部直接 GET 该路径不得伪造"降级"响应(审查 Minor)
        if (!isInternalForward(exchange)) {
            return Mono.just(ResponseEntity.status(HttpStatus.NOT_FOUND)
                    .body(Envelope.fail(ErrorCode.OBJECT_NOT_FOUND,
                            ErrorCode.message(ErrorCode.OBJECT_NOT_FOUND), traceId(exchange))));
        }
        Envelope<Void> body = Envelope.fail(ErrorCode.DEPENDENCY_TIMEOUT,
                ErrorCode.message(ErrorCode.DEPENDENCY_TIMEOUT), traceId(exchange));
        log.warn("网关级熔断降级:快速失败 503/5002(下游连续失败)");
        return Mono.just(ResponseEntity.status(HttpStatus.SERVICE_UNAVAILABLE)
                .header(FALLBACK_HEADER, "true")
                .body(body));
    }

    /**
     * 判定是否为网关内部的熔断回退请求:SCG 的 CircuitBreaker 过滤器触发 fallback 时会写入
     * {@code CIRCUITBREAKER_EXECUTION_EXCEPTION_ATTR}(回退目标 URI 在转发过程中已被 ForwardRoutingFilter
     * 改写,不能作为判据)。
     */
    private boolean isInternalForward(ServerWebExchange exchange) {
        return exchange.getAttribute(ServerWebExchangeUtils.CIRCUITBREAKER_EXECUTION_EXCEPTION_ATTR) != null;
    }

    private String traceId(ServerWebExchange exchange) {
        String traceId = exchange.getRequest().getHeaders().getFirst(TraceIdFilter.TRACE_ID_HEADER);
        return (traceId == null || traceId.isBlank()) ? UUID.randomUUID().toString() : traceId;
    }
}
