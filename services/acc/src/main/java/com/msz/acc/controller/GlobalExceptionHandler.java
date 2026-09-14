package com.msz.acc.controller;

import com.msz.acc.domain.support.AccBusinessException;
import com.msz.acc.infrastructure.auth.AccessDeniedException;
import com.msz.acc.infrastructure.auth.AuthException;
import com.msz.acc.infrastructure.gateway.ChannelTimeoutException;
import com.msz.acc.infrastructure.gateway.ChannelUnavailableException;
import com.msz.acc.infrastructure.web.TraceIds;
import com.msz.common.api.Envelope;
import com.msz.common.api.ErrorCode;
import jakarta.servlet.http.HttpServletRequest;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.dao.DataAccessException;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.MissingServletRequestParameterException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.method.annotation.MethodArgumentTypeMismatchException;

import java.util.concurrent.TimeoutException;

/**
 * 全局异常 → 统一 Envelope/错误码映射（S5）。
 *
 * <p>映射口径（HTTP 状态 × 业务码）：1xxx→400；2001→401；2002/2003→403；3006→404；其余 3xxx→422；
 * 4xxx→502；5xxx→500。5xxx 细节只进日志，响应 message 统一口径（ErrorCode.message）。</p>
 */
@RestControllerAdvice
public class GlobalExceptionHandler {

    private static final Logger log = LoggerFactory.getLogger(GlobalExceptionHandler.class);

    @ExceptionHandler(AccBusinessException.class)
    public ResponseEntity<Envelope<Void>> handleBusiness(AccBusinessException e, HttpServletRequest request) {
        return fail(e.code(), ErrorCode.message(e.code()), statusOf(e.code()), request, e);
    }

    @ExceptionHandler(AuthException.class)
    public ResponseEntity<Envelope<Void>> handleAuth(AuthException e, HttpServletRequest request) {
        return fail(ErrorCode.UNAUTHORIZED, ErrorCode.message(ErrorCode.UNAUTHORIZED), HttpStatus.UNAUTHORIZED,
                request, e);
    }

    @ExceptionHandler(AccessDeniedException.class)
    public ResponseEntity<Envelope<Void>> handleAccessDenied(AccessDeniedException e, HttpServletRequest request) {
        return fail(ErrorCode.FORBIDDEN, ErrorCode.message(ErrorCode.FORBIDDEN), HttpStatus.FORBIDDEN, request, e);
    }

    @ExceptionHandler(MissingServletRequestParameterException.class)
    public ResponseEntity<Envelope<Void>> handleMissingParameter(MissingServletRequestParameterException e,
                                                                 HttpServletRequest request) {
        return fail(ErrorCode.PARAM_MISSING, ErrorCode.message(ErrorCode.PARAM_MISSING), HttpStatus.BAD_REQUEST,
                request, e);
    }

    @ExceptionHandler(MethodArgumentTypeMismatchException.class)
    public ResponseEntity<Envelope<Void>> handleTypeMismatch(MethodArgumentTypeMismatchException e,
                                                             HttpServletRequest request) {
        return fail(ErrorCode.PARAM_FORMAT, ErrorCode.message(ErrorCode.PARAM_FORMAT), HttpStatus.BAD_REQUEST,
                request, e);
    }

    @ExceptionHandler({MethodArgumentNotValidException.class, HttpMessageNotReadableException.class})
    public ResponseEntity<Envelope<Void>> handleInvalidBody(Exception e, HttpServletRequest request) {
        return fail(ErrorCode.PARAM_FORMAT, ErrorCode.message(ErrorCode.PARAM_FORMAT), HttpStatus.BAD_REQUEST,
                request, e);
    }

    @ExceptionHandler(IllegalArgumentException.class)
    public ResponseEntity<Envelope<Void>> handleIllegalArgument(IllegalArgumentException e,
                                                                HttpServletRequest request) {
        return fail(ErrorCode.PARAM_RANGE, ErrorCode.message(ErrorCode.PARAM_RANGE), HttpStatus.BAD_REQUEST,
                request, e);
    }

    @ExceptionHandler(DuplicateKeyException.class)
    public ResponseEntity<Envelope<Void>> handleDuplicateKey(DuplicateKeyException e, HttpServletRequest request) {
        return fail(ErrorCode.IDEMPOTENCY_CONFLICT, ErrorCode.message(ErrorCode.IDEMPOTENCY_CONFLICT),
                HttpStatus.UNPROCESSABLE_ENTITY, request, e);
    }

    @ExceptionHandler(DataAccessException.class)
    public ResponseEntity<Envelope<Void>> handleDataAccess(DataAccessException e, HttpServletRequest request) {
        return fail(ErrorCode.DB_ERROR, ErrorCode.message(ErrorCode.DB_ERROR), HttpStatus.INTERNAL_SERVER_ERROR,
                request, e);
    }

    @ExceptionHandler({TimeoutException.class, ChannelTimeoutException.class})
    public ResponseEntity<Envelope<Void>> handleTimeout(Exception e, HttpServletRequest request) {
        return fail(ErrorCode.DEPENDENCY_TIMEOUT, ErrorCode.message(ErrorCode.DEPENDENCY_TIMEOUT),
                HttpStatus.INTERNAL_SERVER_ERROR, request, e);
    }

    @ExceptionHandler(ChannelUnavailableException.class)
    public ResponseEntity<Envelope<Void>> handleChannelUnavailable(ChannelUnavailableException e,
                                                                   HttpServletRequest request) {
        return fail(ErrorCode.CHANNEL_FAILED, ErrorCode.message(ErrorCode.CHANNEL_FAILED), HttpStatus.BAD_GATEWAY,
                request, e);
    }

    @ExceptionHandler(Exception.class)
    public ResponseEntity<Envelope<Void>> handleUnexpected(Exception e, HttpServletRequest request) {
        String traceId = TraceIds.of(request);
        log.error("未捕获异常 [traceId={}]", traceId, e);
        return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR)
                .body(Envelope.fail(ErrorCode.INTERNAL_ERROR, ErrorCode.message(ErrorCode.INTERNAL_ERROR), traceId));
    }

    private ResponseEntity<Envelope<Void>> fail(int code, String message, HttpStatus status,
                                                HttpServletRequest request, Exception e) {
        String traceId = TraceIds.of(request);
        if (code >= 5000) {
            log.error("映射 5xxx [traceId={}] code={} message={}", traceId, code, e.getMessage(), e);
        } else {
            log.warn("映射业务码 [traceId={}] code={} message={}", traceId, code, e.getMessage());
        }
        return ResponseEntity.status(status).body(Envelope.fail(code, message, traceId));
    }

    private static HttpStatus statusOf(int code) {
        if (code < 2000) {
            return HttpStatus.BAD_REQUEST;
        }
        if (code == ErrorCode.UNAUTHORIZED) {
            return HttpStatus.UNAUTHORIZED;
        }
        if (code < 3000) {
            return HttpStatus.FORBIDDEN;
        }
        if (code == ErrorCode.OBJECT_NOT_FOUND) {
            return HttpStatus.NOT_FOUND;
        }
        if (code < 4000) {
            return HttpStatus.UNPROCESSABLE_ENTITY;
        }
        if (code < 5000) {
            return HttpStatus.BAD_GATEWAY;
        }
        return HttpStatus.INTERNAL_SERVER_ERROR;
    }
}
