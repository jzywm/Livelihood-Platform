package com.msz.acc.controller;

import com.msz.common.api.Envelope;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.ConstraintViolationException;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;

import java.util.Set;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * GlobalExceptionHandler 单元测试（Fix round 1）：简报 line 47 逐字要求
 * ConstraintViolationException 映射 1002/400——直接调用 handler 断言（全站无 @Valid，
 * 该异常今日不可由控制器触发，此处证明映射本身生效）。
 */
class GlobalExceptionHandlerTest {

    private final GlobalExceptionHandler handler = new GlobalExceptionHandler();

    @Test
    @DisplayName("ConstraintViolationException → 400 + code 1002 + message 口径 + traceId 必带")
    void constraintViolationMapsTo1002BadRequest() {
        HttpServletRequest request = mock(HttpServletRequest.class);
        when(request.getHeader(anyString())).thenReturn(null);

        ResponseEntity<Envelope<Void>> response = handler.handleInvalidBody(
                new ConstraintViolationException("校验失败", Set.of()), request);

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.BAD_REQUEST);
        assertThat(response.getBody()).isNotNull();
        assertThat(response.getBody().code()).isEqualTo(1002);
        assertThat(response.getBody().message()).isEqualTo("参数格式错误");
        assertThat(response.getBody().data()).isNull();
        assertThat(response.getBody().traceId()).isNotBlank();
    }
}
