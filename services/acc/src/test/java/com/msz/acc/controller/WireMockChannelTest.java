package com.msz.acc.controller;

import com.github.tomakehurst.wiremock.WireMockServer;
import com.github.tomakehurst.wiremock.core.WireMockConfiguration;
import com.msz.acc.domain.model.Account;
import com.msz.acc.domain.model.RealnameRecord;
import com.msz.acc.domain.model.WalletBinding;
import com.msz.acc.infrastructure.crypto.HmacSignatureVerifier;
import com.msz.acc.repository.AccountMapper;
import com.msz.acc.repository.IdempotencyRecordMapper;
import com.msz.acc.repository.RealnameRecordMapper;
import com.msz.acc.repository.ReconcileTaskMapper;
import com.msz.acc.repository.WalletBindingMapper;
import com.msz.acc.repository.WalletFlowMapper;
import com.msz.common.idgen.IdGenerator;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.http.MediaType;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.web.servlet.MockMvc;

import java.time.Instant;
import java.util.concurrent.atomic.AtomicLong;

import static com.github.tomakehurst.wiremock.client.WireMock.aResponse;
import static com.github.tomakehurst.wiremock.client.WireMock.okJson;
import static com.github.tomakehurst.wiremock.client.WireMock.stubFor;
import static com.github.tomakehurst.wiremock.client.WireMock.urlEqualTo;
import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.isNull;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * WireMockChannelTest（S4 裁决 #16）：wiremock-standalone 随机端口 stub 通道——
 * 实名通道：成功回调全链路（register→回调→status→me）/ 验签篡改 4001 / pass=false 保持 REALNAMING / 通道 500 → 4001；
 * 支付通道：verify 成功 → bind 200 / 超时 → 4002。通道真实 stub（HttpChannelClient 真实 HTTP 调用）。
 */
@SpringBootTest
@AutoConfigureMockMvc
class WireMockChannelTest {

    private static final String INTERNAL_TOKEN = "acc-internal-test-token";
    private static final String CONSUMER = "Bearer " + TestJwt.token("1002", "CONSUMER", true);

    private static WireMockServer wireMockServer;

    @Autowired
    private MockMvc mockMvc;

    @MockBean
    private IdGenerator idGenerator;

    @MockBean
    private AccountMapper accountMapper;

    @MockBean
    private RealnameRecordMapper realnameRecordMapper;

    @MockBean
    private WalletFlowMapper walletFlowMapper;

    @MockBean
    private WalletBindingMapper walletBindingMapper;

    @MockBean
    private ReconcileTaskMapper reconcileTaskMapper;

    @MockBean
    private IdempotencyRecordMapper idempotencyRecordMapper;

    private final AtomicLong seq = new AtomicLong(1000);

    @BeforeAll
    static void startWireMock() {
        wireMockServer = new WireMockServer(WireMockConfiguration.options().dynamicPort());
        wireMockServer.start();
    }

    @AfterAll
    static void stopWireMock() {
        wireMockServer.stop();
    }

    @DynamicPropertySource
    static void wireMockBaseUrls(DynamicPropertyRegistry registry) {
        registry.add("acc.channel.realname-base-url", wireMockServer::baseUrl);
        registry.add("acc.channel.payment-base-url", wireMockServer::baseUrl);
    }

    @BeforeEach
    void setUp() {
        wireMockServer.resetAll();
        when(idGenerator.nextId()).thenAnswer(invocation -> seq.incrementAndGet());
        when(accountMapper.selectByMobileHash(anyString())).thenReturn(null);
    }

    @Test
    @DisplayName("全链路：register→通道 stub 授权→验签回调→status 轮询→me（实名成功）")
    void fullChainRegisterCallbackStatusMe() throws Exception {
        wireMockServer.stubFor(com.github.tomakehurst.wiremock.client.WireMock.post(urlEqualTo("/realname/authorize"))
                .willReturn(okJson("{\"ok\":true}")));

        // ① register：真实通道 stub 授权成功，authorizeUrl 由模板拼接 bizId
        mockMvc.perform(post("/acc/register")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"mobile\":\"13800138000\",\"role\":\"CONSUMER\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(0))
                .andExpect(jsonPath("$.data.bizId").value("rz_1001"))
                .andExpect(jsonPath("$.data.authorizeUrl").value(org.hamcrest.Matchers.containsString("bizId=rz_1001")))
                .andExpect(jsonPath("$.data.realNameStatus").value("REALNAMING"));

        // ② 回调：验签通过 → 建户（accountId=1002，idGen 第二次发号）+ REALNAMED
        RealnameRecord realnaming = record("rz_1001", "REALNAMING", null);
        RealnameRecord realnamed = record("rz_1001", "REALNAMED", 1002L);
        when(realnameRecordMapper.selectByBizId("rz_1001")).thenReturn(realnaming, realnamed);
        when(realnameRecordMapper.selectByOpenId("openid-1")).thenReturn(null);

        mockMvc.perform(post("/acc/realname/callback")
                        .header("X-Internal-Token", INTERNAL_TOKEN)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(callbackJson("rz_1001", true)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(0))
                .andExpect(jsonPath("$.data.status").value("REALNAMED"))
                .andExpect(jsonPath("$.data.accountId").value("acc_1002"));

        ArgumentCaptor<Account> captor = ArgumentCaptor.forClass(Account.class);
        verify(accountMapper).insert(captor.capture());
        assertThat(captor.getValue().getAccountId()).isEqualTo(1002L);
        assertThat(captor.getValue().getRealNameStatus()).isEqualTo("REALNAMED");

        // ③ status 轮询
        mockMvc.perform(get("/acc/realname/status").param("bizId", "rz_1001"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.realNameStatus").value("REALNAMED"))
                .andExpect(jsonPath("$.data.accountId").value("acc_1002"))
                .andExpect(jsonPath("$.data.realName").value("张*丰"));

        // ④ me（脱敏）
        when(accountMapper.selectById(1002L)).thenReturn(account(1002L));
        mockMvc.perform(get("/acc/me").header("Authorization", CONSUMER))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(0))
                .andExpect(jsonPath("$.data.accountId").value("acc_1002"))
                .andExpect(jsonPath("$.data.realNameStatus").value("REALNAMED"));
    }

    @Test
    @DisplayName("验签篡改：通道正确签名被篡改 → 4001 拒收，状态不变")
    void tamperedSignatureRejected4001() throws Exception {
        when(realnameRecordMapper.selectByBizId("rz_1")).thenReturn(record("rz_1", "REALNAMING", null));

        long ts = Instant.now().getEpochSecond();
        String payload = "rz_1|openid-1|张三丰|130123199001011234|true|" + ts + "|nonce1234";
        String sign = new HmacSignatureVerifier("acc-callback-test-secret").sign(payload);
        String tampered = sign.substring(0, sign.length() - 2) + (sign.endsWith("ab") ? "cd" : "ab");

        mockMvc.perform(post("/acc/realname/callback")
                        .header("X-Internal-Token", INTERNAL_TOKEN)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"bizId\":\"rz_1\",\"openId\":\"openid-1\",\"name\":\"张三丰\","
                                + "\"idNo\":\"130123199001011234\",\"pass\":true,\"sign\":\"" + tampered + "\","
                                + "\"timestamp\":" + ts + ",\"nonce\":\"nonce1234\"}"))
                .andExpect(status().isBadGateway())
                .andExpect(jsonPath("$.code").value(4001));

        verify(accountMapper, never()).insert(any());
    }

    @Test
    @DisplayName("pass=false：回调受理 200，状态保持 REALNAMING（可重试）")
    void passFalseKeepsRealnaming() throws Exception {
        when(realnameRecordMapper.selectByBizId("rz_2")).thenReturn(record("rz_2", "REALNAMING", null));
        when(realnameRecordMapper.selectByOpenId("openid-1")).thenReturn(null);

        mockMvc.perform(post("/acc/realname/callback")
                        .header("X-Internal-Token", INTERNAL_TOKEN)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(callbackJson("rz_2", false)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(0))
                .andExpect(jsonPath("$.data.status").value("REALNAMING"));

        verify(realnameRecordMapper).updateCallback(eq("rz_2"), eq("REALNAMING"), isNull(), any(), any(), any(), any());
        verify(accountMapper, never()).insert(any());
    }

    @Test
    @DisplayName("通道 500：register → 4001（R-02 不降级）")
    void channel500Register4001() throws Exception {
        wireMockServer.stubFor(com.github.tomakehurst.wiremock.client.WireMock.post(urlEqualTo("/realname/authorize"))
                .willReturn(aResponse().withStatus(500).withBody("{\"error\":\"internal\"}")));

        mockMvc.perform(post("/acc/register")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"mobile\":\"13800138000\",\"role\":\"CONSUMER\"}"))
                .andExpect(status().isBadGateway())
                .andExpect(jsonPath("$.code").value(4001));
    }

    @Test
    @DisplayName("支付通道：verify-payee 成功 → bind 200 落绑定")
    void paymentVerifySuccessBind200() throws Exception {
        wireMockServer.stubFor(com.github.tomakehurst.wiremock.client.WireMock.post(urlEqualTo("/verify-payee"))
                .willReturn(okJson("{\"matched\":true}")));

        when(accountMapper.selectById(1002L)).thenReturn(account(1002L));
        when(walletBindingMapper.selectByAccountAndChannel(1002L, "WECHAT")).thenReturn(null);
        when(idempotencyRecordMapper.insertIgnore(anyString(), anyString(), anyInt(), anyString())).thenReturn(1);
        when(walletBindingMapper.selectById("bnd_1001")).thenReturn(binding("bnd_1001", 1002L));

        mockMvc.perform(post("/acc/wallet/bind")
                        .header("Authorization", CONSUMER)
                        .header("Idempotency-Key", "k-wm-1")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"channel\":\"WECHAT\",\"payeeAccount\":\"6222021234567890\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(0))
                .andExpect(jsonPath("$.data.bindingId").value("bnd_1001"))
                .andExpect(jsonPath("$.data.payeeAccount").value("6222*********890"));

        verify(walletBindingMapper).insert(any());
    }

    @Test
    @DisplayName("支付通道：超时（WireMock 延迟 > 客户端超时）→ bind 4002")
    void paymentTimeout4002() throws Exception {
        wireMockServer.stubFor(com.github.tomakehurst.wiremock.client.WireMock.post(urlEqualTo("/verify-payee"))
                .willReturn(okJson("{\"matched\":true}").withFixedDelay(4000)));

        when(accountMapper.selectById(1002L)).thenReturn(account(1002L));

        mockMvc.perform(post("/acc/wallet/bind")
                        .header("Authorization", CONSUMER)
                        .header("Idempotency-Key", "k-wm-2")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"channel\":\"WECHAT\",\"payeeAccount\":\"6222021234567890\"}"))
                .andExpect(status().isBadGateway())
                .andExpect(jsonPath("$.code").value(4002));
    }

    private static String callbackJson(String bizId, boolean pass) {
        long ts = Instant.now().getEpochSecond();
        String payload = bizId + "|openid-1|张三丰|130123199001011234|" + pass + "|" + ts + "|nonce1234";
        String sign = new HmacSignatureVerifier("acc-callback-test-secret").sign(payload);
        return "{\"bizId\":\"" + bizId + "\",\"openId\":\"openid-1\",\"name\":\"张三丰\","
                + "\"idNo\":\"130123199001011234\",\"pass\":" + pass + ",\"sign\":\"" + sign + "\","
                + "\"timestamp\":" + ts + ",\"nonce\":\"nonce1234\"}";
    }

    private static RealnameRecord record(String bizId, String status, Long accountId) {
        RealnameRecord record = new RealnameRecord();
        record.setBizId(bizId);
        record.setAccountId(accountId);
        record.setChannel("WECHAT");
        record.setOpenId("pending_" + bizId);
        record.setName("张三丰");
        record.setIdNo("130123199001011234");
        record.setStatus(status);
        record.setLevel("BASE");
        record.setCreatedAt(Instant.parse("2026-01-01T00:00:00Z"));
        return record;
    }

    private static Account account(long accountId) {
        Account account = new Account();
        account.setAccountId(accountId);
        account.setRole("CONSUMER");
        account.setMobile("13800138000");
        account.setRealNameStatus("REALNAMED");
        account.setWalletStatus("ACTIVE");
        account.setRealName("张三丰");
        account.setIdNo("130123199001011234");
        account.setCreatedAt(Instant.parse("2026-01-15T10:30:00Z"));
        return account;
    }

    private static WalletBinding binding(String bindingId, long accountId) {
        WalletBinding binding = new WalletBinding();
        binding.setBindingId(bindingId);
        binding.setAccountId(accountId);
        binding.setChannel("WECHAT");
        binding.setPayeeAccount("6222021234567890");
        binding.setPayeeName("张三丰");
        binding.setStatus("BOUND");
        binding.setCreatedAt(Instant.parse("2026-01-15T10:30:00Z"));
        return binding;
    }
}
