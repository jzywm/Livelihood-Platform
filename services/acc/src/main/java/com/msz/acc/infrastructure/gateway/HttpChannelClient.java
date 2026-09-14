package com.msz.acc.infrastructure.gateway;

import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.net.http.HttpTimeoutException;
import java.nio.charset.StandardCharsets;
import java.time.Duration;

/**
 * 极简 HTTP 通道客户端（S5）：JDK 内置 HttpClient，POST JSON / GET。
 *
 * <p>超时（请求级 timeoutMillis）→ {@link ChannelTimeoutException}；连接失败/中断/非 2xx →
 * {@link ChannelUnavailableException}。非 final：测试可用 Mockito 子类替身。</p>
 */
public class HttpChannelClient {

    private static final long CONNECT_TIMEOUT_MILLIS = 3000;

    private final HttpClient http;

    public HttpChannelClient() {
        this.http = HttpClient.newBuilder()
                .connectTimeout(Duration.ofMillis(CONNECT_TIMEOUT_MILLIS))
                .build();
    }

    /** POST JSON，2xx 返回响应体；超时/失败抛对应通道异常。 */
    public String postJson(String url, String jsonBody, long timeoutMillis) {
        HttpRequest request = HttpRequest.newBuilder(URI.create(url))
                .timeout(Duration.ofMillis(timeoutMillis))
                .header("Content-Type", "application/json;charset=UTF-8")
                .POST(HttpRequest.BodyPublishers.ofString(jsonBody, StandardCharsets.UTF_8))
                .build();
        return send(request);
    }

    /** GET，2xx 返回响应体；超时/失败抛对应通道异常。 */
    public String get(String url, long timeoutMillis) {
        HttpRequest request = HttpRequest.newBuilder(URI.create(url))
                .timeout(Duration.ofMillis(timeoutMillis))
                .GET()
                .build();
        return send(request);
    }

    private String send(HttpRequest request) {
        HttpResponse<String> response;
        try {
            response = http.send(request, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
        } catch (HttpTimeoutException e) {
            throw new ChannelTimeoutException("通道响应超时: " + request.uri(), e);
        } catch (IOException e) {
            throw new ChannelUnavailableException("通道连接失败: " + request.uri(), e);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new ChannelUnavailableException("通道调用被中断: " + request.uri(), e);
        }
        if (response.statusCode() < 200 || response.statusCode() >= 300) {
            throw new ChannelUnavailableException(
                    "通道返回非 2xx: " + response.statusCode() + " " + request.uri());
        }
        return response.body();
    }
}
