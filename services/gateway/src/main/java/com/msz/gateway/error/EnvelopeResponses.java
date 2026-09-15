package com.msz.gateway.error;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.msz.common.api.Envelope;
import com.msz.common.api.ErrorCode;
import com.msz.gateway.filter.TraceIdFilter;
import org.springframework.core.io.buffer.DataBuffer;
import org.springframework.http.HttpStatusCode;
import org.springframework.http.MediaType;
import org.springframework.http.server.reactive.ServerHttpResponse;
import org.springframework.web.server.ServerWebExchange;
import reactor.core.publisher.Mono;

import java.nio.charset.StandardCharsets;
import java.util.UUID;

/**
 * 统一 Envelope 错误响应写出器(F5/D10)。
 *
 * <p>过滤器对「客户端错误」(401/404/429)直接短路写出响应而非抛异常——原因:网关级熔断
 * (CircuitBreaker 过滤器)会把链上任何异常视为下游失败并转入 fallback,把 4xx 误报为 5xx 降级。
 * 直接写响应既能保证错误码语义正确,也不会污染熔断统计。真正的基础设施失败(超时/连接失败/
 * 依赖不可用)仍以异常抛出,由 {@link GatewayErrorWebExceptionHandler} 或熔断 fallback 处理。</p>
 */
public final class EnvelopeResponses {

    private final ObjectMapper mapper;

    public EnvelopeResponses(ObjectMapper mapper) {
        this.mapper = mapper;
    }

    /** 写出 Envelope 失败响应(status + 平台错误码);响应已提交时降级为异常。 */
    public Mono<Void> write(ServerWebExchange exchange, HttpStatusCode status, int code) {
        ServerHttpResponse response = exchange.getResponse();
        if (response.isCommitted()) {
            return Mono.error(new IllegalStateException("响应已提交,无法写出错误响应"));
        }
        response.setStatusCode(status);
        response.getHeaders().setContentType(MediaType.APPLICATION_JSON);
        byte[] body = serialize(Envelope.fail(code, ErrorCode.message(code), traceId(exchange)));
        DataBuffer buffer = response.bufferFactory().wrap(body);
        return response.writeWith(Mono.just(buffer));
    }

    /** traceId 口径:请求头 X-Request-Id(缺失时 UUID 兜底,与 acc TraceIds 一致)。 */
    public static String traceId(ServerWebExchange exchange) {
        String traceId = exchange.getRequest().getHeaders().getFirst(TraceIdFilter.TRACE_ID_HEADER);
        if (traceId == null || traceId.isBlank()) {
            return UUID.randomUUID().toString();
        }
        return traceId;
    }

    private byte[] serialize(Envelope<?> envelope) {
        try {
            return mapper.writeValueAsBytes(envelope);
        } catch (JsonProcessingException e) {
            // 序列化兜底(几乎不可达):最小合法 Envelope 结构
            return ("{\"code\":5000,\"message\":\"内部错误\",\"data\":null,\"traceId\":\""
                    + envelope.traceId() + "\",\"timestamp\":null}").getBytes(StandardCharsets.UTF_8);
        }
    }
}
