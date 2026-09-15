package com.msz.gateway.error;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.msz.common.api.ErrorCode;
import org.springframework.boot.web.reactive.error.ErrorWebExceptionHandler;
import org.springframework.core.Ordered;
import org.springframework.http.HttpStatusCode;
import org.springframework.http.server.reactive.ServerHttpResponse;
import org.springframework.web.reactive.function.client.WebClientRequestException;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.web.server.ServerWebExchange;
import reactor.core.publisher.Mono;

import java.net.ConnectException;
import java.util.concurrent.TimeoutException;

/**
 * 网关全局错误处理(D10/F5):基础设施类错误统一 Envelope 输出,禁用默认 whitelabel。
 *
 * <p>映射:AuthException→401/2001 · RateLimitedException→429/2004 ·
 * 超时/连接失败/下游 5xx→503/5002 · GatewayUnavailableException→503/5003 ·
 * 404→3006 · 未知→500/5000。客户端错误(401/404/429)通常由过滤器经
 * {@link EnvelopeResponses} 直接短路写出(避免被熔断视为下游失败),本处理器兜底其余异常。</p>
 */
public final class GatewayErrorWebExceptionHandler implements ErrorWebExceptionHandler, Ordered {

    public static final int ORDER = -1;

    private final EnvelopeResponses responses;

    public GatewayErrorWebExceptionHandler(ObjectMapper mapper) {
        this.responses = new EnvelopeResponses(mapper);
    }

    @Override
    public Mono<Void> handle(ServerWebExchange exchange, Throwable ex) {
        ServerHttpResponse response = exchange.getResponse();
        if (response.isCommitted()) {
            return Mono.error(ex);
        }
        Mapping mapping = map(ex);
        return responses.write(exchange, mapping.status(), mapping.code());
    }

    static Mapping map(Throwable ex) {
        if (ex instanceof AuthException) {
            return new Mapping(HttpStatusCode.valueOf(401), ErrorCode.UNAUTHORIZED);
        }
        if (ex instanceof RateLimitedException) {
            return new Mapping(HttpStatusCode.valueOf(429), ErrorCode.RATE_LIMITED);
        }
        if (ex instanceof TimeoutException || ex instanceof ConnectException || ex instanceof WebClientRequestException) {
            return new Mapping(HttpStatusCode.valueOf(503), ErrorCode.DEPENDENCY_TIMEOUT);
        }
        if (ex instanceof GatewayUnavailableException) {
            return new Mapping(HttpStatusCode.valueOf(503), ErrorCode.GATEWAY_UNAVAILABLE);
        }
        if (ex instanceof ResponseStatusException rse) {
            if (rse.getStatusCode().value() == 404) {
                return new Mapping(rse.getStatusCode(), ErrorCode.OBJECT_NOT_FOUND);
            }
            if (rse.getStatusCode().is5xxServerError()) {
                return new Mapping(rse.getStatusCode(), ErrorCode.DEPENDENCY_TIMEOUT);
            }
            return new Mapping(rse.getStatusCode(), ErrorCode.INTERNAL_ERROR);
        }
        return new Mapping(HttpStatusCode.valueOf(500), ErrorCode.INTERNAL_ERROR);
    }

    @Override
    public int getOrder() {
        return ORDER;
    }

    /** 错误映射:HTTP 状态 + 平台业务码。 */
    public record Mapping(HttpStatusCode status, int code) {
    }
}
