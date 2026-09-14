package com.msz.acc.infrastructure.web;

import jakarta.servlet.http.HttpServletRequest;

import java.util.UUID;

/**
 * traceId 解析（S5）：优先 {@code X-Request-Id} 请求头，否则 UUID；
 * 供 Controller / GlobalExceptionHandler / AuthFilter 统一生成 Envelope.traceId。
 */
public final class TraceIds {

    public static final String REQUEST_ID_HEADER = "X-Request-Id";

    private TraceIds() {
    }

    public static String of(HttpServletRequest request) {
        String value = request == null ? null : request.getHeader(REQUEST_ID_HEADER);
        return value == null || value.isBlank() ? UUID.randomUUID().toString() : value;
    }
}
