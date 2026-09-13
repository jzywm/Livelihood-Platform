package com.msz.acc.infrastructure.auth;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletRequest;
import jakarta.servlet.ServletResponse;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.io.PrintWriter;
import java.io.StringWriter;
import java.lang.reflect.Proxy;
import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * SEC-07：鉴权 Filter 最小版——无 token / 坏签名 / 吊销 → 401+2001；通过 → attribute 透传 + 放行。
 */
class AuthFilterTest {

    private static final String SECRET = "filter-secret-0123456789";
    private static final String ATTR = "authContext";

    private final JwtCodec codec = new JwtCodec();

    @Test
    @DisplayName("SEC-07 无 Authorization 头 → 401 + code 2001")
    void ut_noTokenReturns401Code2001() throws Exception {
        CapturedResponse response = runFilter(null, new NoopRevocationStore(), new AtomicBoolean());

        assertThat(response.status).isEqualTo(401);
        assertThat(response.body).contains("\"code\":2001");
    }

    @Test
    @DisplayName("SEC-07 非 Bearer → 401 + code 2001")
    void ut_nonBearerReturns401Code2001() throws Exception {
        CapturedResponse response = runFilter("Basic abc", new NoopRevocationStore(), new AtomicBoolean());

        assertThat(response.status).isEqualTo(401);
        assertThat(response.body).contains("\"code\":2001");
    }

    @Test
    @DisplayName("SEC-07 坏签名 → 401 + code 2001")
    void ut_badSignatureReturns2001() throws Exception {
        String token = codec.sign(Map.of("sub", "1001", "role", "CONSUMER", "jti", "jti-1"), SECRET, 300);
        String tampered = tamperPayloadMiddle(token);

        CapturedResponse response = runFilter("Bearer " + tampered, new NoopRevocationStore(), new AtomicBoolean());

        assertThat(response.status).isEqualTo(401);
        assertThat(response.body).contains("\"code\":2001");
    }

    @Test
    @DisplayName("SEC-07 已吊销 → 401 + code 2001")
    void ut_revokedReturns2001() throws Exception {
        String token = codec.sign(Map.of("sub", "1001", "role", "CONSUMER", "jti", "revoked-jti"), SECRET, 300);

        CapturedResponse response = runFilter("Bearer " + token, jti -> true, new AtomicBoolean());

        assertThat(response.status).isEqualTo(401);
        assertThat(response.body).contains("\"code\":2001");
    }

    @Test
    @DisplayName("SEC-07 通过 → authContext 属性写入 + 放行")
    void ut_validTokenSetsAttributeAndChains() throws Exception {
        String token = codec.sign(Map.of("sub", "1001", "role", "REGULATOR", "jti", "jti-ok"), SECRET, 300);
        AtomicBoolean chained = new AtomicBoolean(false);
        Map<String, Object> attributes = new HashMap<>();

        CapturedResponse response = runFilter("Bearer " + token, new NoopRevocationStore(), chained, attributes);

        assertThat(chained).isTrue();
        AuthContext ctx = (AuthContext) attributes.get(ATTR);
        assertThat(ctx).isNotNull();
        assertThat(ctx.accountId()).isEqualTo("1001");
        assertThat(ctx.role()).isEqualTo("REGULATOR");
        assertThat(ctx.jti()).isEqualTo("jti-ok");
    }

    private CapturedResponse runFilter(String authHeader, RevocationStore revocation, AtomicBoolean chained) throws Exception {
        return runFilter(authHeader, revocation, chained, new HashMap<>());
    }

    /**
     * 确定性篡改：改 payload 段（第 2 段）中间某字符。JwtCodec.verify 的签名输入为原始字符串
     * {@code header + "." + payload}，任何字符变化必导致重算 HMAC 失配（不依赖 base64url 解码差异）。
     */
    private static String tamperPayloadMiddle(String token) {
        String[] parts = token.split("\\.");
        String payload = parts[1];
        int idx = payload.length() / 2;
        char original = payload.charAt(idx);
        char changed = original == 'A' ? 'B' : 'A';
        return parts[0] + "." + payload.substring(0, idx) + changed + payload.substring(idx + 1) + "." + parts[2];
    }

    private CapturedResponse runFilter(String authHeader, RevocationStore revocation, AtomicBoolean chained,
                                       Map<String, Object> attributes) throws Exception {
        AuthFilter filter = new AuthFilter(codec, SECRET, revocation);

        StringWriter sw = new StringWriter();
        AtomicInteger status = new AtomicInteger();
        PrintWriter writer = new PrintWriter(sw);

        HttpServletRequest request = fakeRequest(authHeader, attributes);
        HttpServletResponse response = fakeResponse(status, writer);

        FilterChain chain = (req, res) -> chained.set(true);

        filter.doFilter(request, response, chain);
        writer.flush();

        return new CapturedResponse(status.get(), sw.toString());
    }

    private static HttpServletRequest fakeRequest(String authHeader, Map<String, Object> attributes) {
        return (HttpServletRequest) Proxy.newProxyInstance(
                HttpServletRequest.class.getClassLoader(),
                new Class<?>[]{HttpServletRequest.class},
                (proxy, method, args) -> {
                    switch (method.getName()) {
                        case "getHeader" -> {
                            return "Authorization".equals(args[0]) ? authHeader : null;
                        }
                        case "setAttribute" -> {
                            attributes.put((String) args[0], args[1]);
                            return null;
                        }
                        case "getAttribute" -> {
                            return attributes.get(args[0]);
                        }
                        default -> {
                            return defaultReturn(method.getReturnType());
                        }
                    }
                });
    }

    private static HttpServletResponse fakeResponse(AtomicInteger status, PrintWriter writer) {
        return (HttpServletResponse) Proxy.newProxyInstance(
                HttpServletResponse.class.getClassLoader(),
                new Class<?>[]{HttpServletResponse.class},
                (proxy, method, args) -> {
                    switch (method.getName()) {
                        case "setStatus" -> {
                            status.set((Integer) args[0]);
                            return null;
                        }
                        case "setContentType" -> {
                            return null;
                        }
                        case "getWriter" -> {
                            return writer;
                        }
                        default -> {
                            return defaultReturn(method.getReturnType());
                        }
                    }
                });
    }

    private static Object defaultReturn(Class<?> type) {
        if (!type.isPrimitive()) {
            return null;
        }
        if (type == boolean.class) {
            return false;
        }
        if (type == int.class || type == long.class || type == short.class || type == byte.class) {
            return 0;
        }
        if (type == double.class || type == float.class) {
            return 0.0;
        }
        if (type == char.class) {
            return '\0';
        }
        return null;
    }

    private record CapturedResponse(int status, String body) {
    }
}
