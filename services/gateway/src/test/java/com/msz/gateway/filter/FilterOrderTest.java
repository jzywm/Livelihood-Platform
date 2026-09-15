package com.msz.gateway.filter;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.msz.gateway.auth.InMemoryRevocationStore;
import com.msz.gateway.auth.JwtVerifier;
import com.msz.gateway.config.GatewayProperties;
import com.msz.gateway.error.EnvelopeResponses;
import com.msz.gateway.ratelimit.InMemoryRateLimiter;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Set;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 过滤器顺序契约(I12④):<b>全部路径判断都依赖这个顺序</b>——
 * 前门净化最先(traceId 之前)、鉴权先于守卫与限流、限流先于超时。
 */
class FilterOrderTest {

    private final EnvelopeResponses responses = new EnvelopeResponses(new ObjectMapper());

    private GatewayProperties props() {
        return new GatewayProperties(
                GatewayProperties.Auth.of(List.of(), "s3cret"),
                GatewayProperties.RateLimit.defaults(),
                GatewayProperties.Store.MEMORY,
                List.of("/api/v1/acc/internal/"));
    }

    @Test
    void ordersAreAscendingAndMatchDocumentedChain() {
        int sanitizer = new RequestSanitizerFilter(responses).getOrder();
        int traceId = new TraceIdFilter().getOrder();
        int jwt = new JwtAuthFilter(new JwtVerifier(), "s3cret", new InMemoryRevocationStore(),
                Set.of(), responses).getOrder();
        int guard = new InternalPathGuardFilter(props(), responses).getOrder();
        int rateLimit = new RateLimitFilter(new InMemoryRateLimiter(), props(), responses).getOrder();
        int timeout = new TimeoutFilter().getOrder();

        assertThat(sanitizer).isEqualTo(RequestSanitizerFilter.ORDER);
        assertThat(traceId).isEqualTo(TraceIdFilter.ORDER);
        assertThat(jwt).isEqualTo(JwtAuthFilter.ORDER);
        assertThat(guard).isEqualTo(InternalPathGuardFilter.ORDER);
        assertThat(rateLimit).isEqualTo(RateLimitFilter.ORDER);
        assertThat(timeout).isEqualTo(TimeoutFilter.ORDER);

        assertThat(sanitizer).isLessThan(traceId);
        assertThat(traceId).isLessThan(jwt);
        assertThat(jwt).isLessThan(guard);
        assertThat(guard).isLessThan(rateLimit);
        assertThat(rateLimit).isLessThan(timeout);
    }
}
