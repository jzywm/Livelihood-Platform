package com.msz.gateway.error;

import org.junit.jupiter.api.Test;
import org.springframework.http.HttpMethod;
import org.springframework.http.HttpStatus;
import org.springframework.web.reactive.function.client.WebClientRequestException;
import org.springframework.web.server.ResponseStatusException;

import java.net.ConnectException;
import java.net.URI;
import java.util.concurrent.TimeoutException;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 网关错误映射表(D10):异常 → HTTP 状态 + 平台错误码 全分支。
 */
class ErrorMappingTest {

    @Test
    void mapsClientAndInfrastructureErrors() {
        assertThat(GatewayErrorWebExceptionHandler.map(new AuthException("x")).code()).isEqualTo(2001);
        assertThat(GatewayErrorWebExceptionHandler.map(new AuthException("x")).status().value()).isEqualTo(401);

        assertThat(GatewayErrorWebExceptionHandler.map(new RateLimitedException()).code()).isEqualTo(2004);
        assertThat(GatewayErrorWebExceptionHandler.map(new RateLimitedException()).status().value()).isEqualTo(429);

        assertThat(GatewayErrorWebExceptionHandler.map(new TimeoutException()).code()).isEqualTo(5002);
        assertThat(GatewayErrorWebExceptionHandler.map(new ConnectException()).status().value()).isEqualTo(503);
        assertThat(GatewayErrorWebExceptionHandler.map(new WebClientRequestException(
                new RuntimeException("x"), HttpMethod.GET, URI.create("http://acc:8080"),
                org.springframework.http.HttpHeaders.EMPTY)).code())
                .isEqualTo(5002);

        assertThat(GatewayErrorWebExceptionHandler.map(new GatewayUnavailableException("down")).code())
                .isEqualTo(5003);
    }

    @Test
    void mapsResponseStatusExceptions() {
        assertThat(GatewayErrorWebExceptionHandler.map(
                new ResponseStatusException(HttpStatus.NOT_FOUND)).code()).isEqualTo(3006);
        assertThat(GatewayErrorWebExceptionHandler.map(
                new ResponseStatusException(HttpStatus.BAD_GATEWAY)).code()).isEqualTo(5002);
        assertThat(GatewayErrorWebExceptionHandler.map(
                new ResponseStatusException(HttpStatus.BAD_REQUEST)).code()).isEqualTo(5000);
    }

    @Test
    void mapsUnknownToInternalError() {
        assertThat(GatewayErrorWebExceptionHandler.map(new IllegalStateException("boom")).code()).isEqualTo(5000);
        assertThat(GatewayErrorWebExceptionHandler.map(new IllegalStateException("boom")).status().value())
                .isEqualTo(500);
    }
}
