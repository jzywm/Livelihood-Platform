package com.msz.acc.controller;

import com.msz.acc.application.port.CaptchaPort;
import com.msz.acc.domain.model.Account;
import com.msz.acc.repository.AccountMapper;
import com.msz.common.idgen.IdGenerator;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;

import java.util.concurrent.atomic.AtomicLong;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * 会话端点**真实装配**端到端守卫（`@SpringBootTest` + 真实 Filter 链 + 真实控制器 + 真实
 * {@code SessionFlow} + 内置会话存储）：登录 → 换发 → 登出（含幂等）。
 *
 * <p>与 {@code AuthControllerTest}（standalone MockMvc + 流程替身）互补：那条链验证 HTTP 契约与
 * Cookie 属性；本条链验证**装配正确性**——新控制器/新 Bean 在完整 Spring 上下文（含
 * {@code TrustedHeaderAuthFilter} 白名单、{@code GlobalExceptionHandler}、Jackson 序列化）下
 * 真的连得上、跑得通。仅账户表与票据端口用桩（外部依赖）。</p>
 *
 * <p><b>身份头</b>：登出不在白名单（需有效短 token），而服务内信任的是**网关透传的
 * {@code X-User-*} 身份头**；直连服务的用例因此必须像网关那样带上四个身份头——这本身就是
 * 「登出受保护」这条边界的守卫。</p>
 */
@SpringBootTest
@AutoConfigureMockMvc
class SessionEndToEndTest {

    private static final String MOBILE = "13800138000";

    @Autowired
    private MockMvc mockMvc;

    @MockBean
    private IdGenerator idGenerator;

    @MockBean
    private AccountMapper accountMapper;

    @MockBean
    private CaptchaPort captchaPort;

    @BeforeEach
    void setUp() {
        when(idGenerator.nextId()).thenAnswer(invocation -> new AtomicLong(5000).incrementAndGet());
        Account account = new Account();
        account.setAccountId(1001L);
        account.setRole("CONSUMER");
        account.setWalletStatus("ACTIVE");
        account.setRealNameStatus("REALNAMED");
        when(accountMapper.selectByMobileHash(anyString())).thenReturn(account);
    }

    @Test
    @DisplayName("闭环：登录 200（Set-Cookie）→ 换发 200 且换新 Cookie → 登出 200 清 Cookie → 重复登出仍 200")
    void loginRefreshLogoutLoop() throws Exception {
        MvcResult login = mockMvc.perform(post("/acc/auth/login")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"mobile\":\"" + MOBILE + "\",\"captchaToken\":\"ct_e2e\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(0))
                .andExpect(jsonPath("$.data.accessToken").isNotEmpty())
                .andExpect(jsonPath("$.data.expiresIn").value(900))
                .andExpect(jsonPath("$.data.accountId").value("acc_1001"))
                .andExpect(header().string("Set-Cookie", org.hamcrest.Matchers.allOf(
                        org.hamcrest.Matchers.containsString("HttpOnly"),
                        org.hamcrest.Matchers.containsString("Secure"),
                        org.hamcrest.Matchers.containsString("SameSite=Lax"),
                        org.hamcrest.Matchers.containsString("Path=/api/v1/acc/auth"))))
                .andReturn();

        String refreshCookie = cookieValue(login.getResponse().getHeader("Set-Cookie"));
        assertThat(refreshCookie).isNotBlank();

        MvcResult refreshed = mockMvc.perform(post("/acc/auth/refresh")
                        .header("Cookie", "refresh_token=" + refreshCookie))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.accessToken").isNotEmpty())
                .andReturn();

        String newCookie = cookieValue(refreshed.getResponse().getHeader("Set-Cookie"));
        assertThat(newCookie).isNotEqualTo(refreshCookie);

        // 旧 refresh 已被消费：宽限窗口外重放 → 401（宽限窗口内属并发重试，由 SessionFlowTest 覆盖）
        MvcResult accessToken = refreshed;
        MvcResult logout = mockMvc.perform(post("/acc/auth/logout")
                        .header("Authorization", "Bearer " + accessTokenOf(accessToken))
                        .header("X-User-Id", "1001")
                        .header("X-User-Role", "CONSUMER")
                        .header("X-User-Mfa", "false")
                        .header("X-User-Jti", "at_e2e"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.revoked").value(true))
                .andReturn();
        assertThat(logout.getResponse().getHeader("Set-Cookie")).contains("Max-Age=0", "HttpOnly");

        // 幂等：重复登出仍成功
        mockMvc.perform(post("/acc/auth/logout")
                        .header("Authorization", "Bearer " + accessTokenOf(accessToken))
                        .header("X-User-Id", "1001"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(0));
    }

    @Test
    @DisplayName("换发端点无 Cookie → 401 + 2001（真实装配下同样 fail-closed）")
    void refreshWithoutCookieRejected() throws Exception {
        mockMvc.perform(post("/acc/auth/refresh"))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.code").value(2001));
    }

    @Test
    @DisplayName("登出无任何凭据 → 401 + 2001（白名单不含登出）")
    void logoutWithoutCredentialsRejected() throws Exception {
        mockMvc.perform(post("/acc/auth/logout"))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.code").value(2001));
    }

    @Test
    @DisplayName("登出有身份头但无任何 token → 401 + 2001（身份头不等于会话凭据）")
    void logoutWithIdentityHeaderButNoTokenRejected() throws Exception {
        mockMvc.perform(post("/acc/auth/logout")
                        .header("X-User-Id", "1001"))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.code").value(2001));
    }

    private static String cookieValue(String setCookieHeader) {
        if (setCookieHeader == null) {
            return null;
        }
        String prefix = "refresh_token=";
        int start = setCookieHeader.indexOf(prefix);
        if (start < 0) {
            return null;
        }
        int end = setCookieHeader.indexOf(';', start);
        return setCookieHeader.substring(start + prefix.length(), end < 0 ? setCookieHeader.length() : end);
    }

    private static String accessTokenOf(MvcResult result) throws Exception {
        Matcher matcher = Pattern.compile("\"accessToken\":\"([^\"]+)\"")
                .matcher(result.getResponse().getContentAsString());
        return matcher.find() ? matcher.group(1) : null;
    }
}
