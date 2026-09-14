package com.msz.acc.controller;

import com.msz.acc.domain.model.Account;
import com.msz.acc.domain.model.WalletFlow;
import com.msz.acc.repository.AccountMapper;
import com.msz.acc.repository.IdempotencyRecordMapper;
import com.msz.acc.repository.RealnameRecordMapper;
import com.msz.acc.repository.ReconcileTaskMapper;
import com.msz.acc.repository.WalletBindingMapper;
import com.msz.acc.repository.WalletFlowMapper;
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

import java.time.Instant;
import java.util.List;
import java.util.concurrent.atomic.AtomicLong;

import static org.hamcrest.Matchers.matchesPattern;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * InternalApiTest（5.4）：内部 Token 鉴权；getAccount/getRealname 脱敏；recordFlow 落库
 * （@MockBean WalletFlowMapper 断言调用）+ 同 channelOrderNo 二击幂等（IT-03 记账链路）。
 */
@SpringBootTest
@AutoConfigureMockMvc
class InternalApiTest {

    private static final String INTERNAL_TOKEN = "acc-internal-test-token";
    private static final Instant OCCURRED_AT = Instant.parse("2026-01-15T10:30:00Z");

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

    @BeforeEach
    void setUp() {
        when(idGenerator.nextId()).thenAnswer(invocation -> seq.incrementAndGet());
        when(accountMapper.selectById(anyLong())).thenReturn(account(1001L));
    }

    @Test
    @DisplayName("getAccount：内部 token 通过 → 200 脱敏账户")
    void getAccountMasked() throws Exception {
        mockMvc.perform(get("/acc/internal/account/1001").header("X-Internal-Token", INTERNAL_TOKEN))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(0))
                .andExpect(jsonPath("$.data.accountId").value("acc_1001"))
                .andExpect(jsonPath("$.data.role").value("CONSUMER"))
                .andExpect(jsonPath("$.data.mobile").value(matchesPattern("^\\d{3}\\*{4}\\d{4}$")))
                .andExpect(jsonPath("$.data.realName").value("张*丰"));
    }

    @Test
    @DisplayName("getRealname：内部 token 通过 → 200 脱敏实名信息")
    void getRealnameMasked() throws Exception {
        mockMvc.perform(get("/acc/internal/realname/1001").header("X-Internal-Token", INTERNAL_TOKEN))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(0))
                .andExpect(jsonPath("$.data.realNameStatus").value("REALNAMED"))
                .andExpect(jsonPath("$.data.realName").value("张*丰"))
                .andExpect(jsonPath("$.data.idNo").value("1301**********1234"));
    }

    @Test
    @DisplayName("IT-03 recordFlow：落库（mapper.insert 断言）+ 同 channelOrderNo 二击幂等")
    void recordFlowPersistsAndIdempotent() throws Exception {
        when(walletFlowMapper.selectByAccountAndRange(anyString(), anyLong(), any(), any(), anyInt(), anyInt(), any()))
                .thenReturn(List.of());

        mockMvc.perform(post("/acc/internal/wallet/flows")
                        .header("X-Internal-Token", INTERNAL_TOKEN)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"accountId\":1001,\"type\":\"PAYROLL\",\"direction\":\"IN\","
                                + "\"amount\":\"3200.00\",\"channelOrderNo\":\"wx001\",\"bizType\":\"代发\","
                                + "\"occurredAt\":\"2026-01-15T10:30:00Z\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(0))
                .andExpect(jsonPath("$.data.flowId").value("flw_1001"))
                .andExpect(jsonPath("$.data.channelOrderNo").value("wx001"))
                .andExpect(jsonPath("$.data.hash").isString());

        verify(walletFlowMapper, times(1)).insert(any());

        // 二击：同 channelOrderNo 幂等返回原流水，不再 insert
        WalletFlow existing = new WalletFlow();
        existing.setFlowId(1001L);
        existing.setAccountId(1001L);
        existing.setType("PAYROLL");
        existing.setDirection("IN");
        existing.setAmount("3200.00");
        existing.setStatus("SUCCEEDED");
        existing.setChannelOrderNo("wx001");
        existing.setBizType("代发");
        existing.setHash("h1");
        existing.setOccurredAt(OCCURRED_AT);
        when(walletFlowMapper.selectByAccountAndRange(anyString(), anyLong(), any(), any(), anyInt(), anyInt(), any()))
                .thenReturn(List.of(existing));

        mockMvc.perform(post("/acc/internal/wallet/flows")
                        .header("X-Internal-Token", INTERNAL_TOKEN)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"accountId\":1001,\"type\":\"PAYROLL\",\"direction\":\"IN\","
                                + "\"amount\":\"3200.00\",\"channelOrderNo\":\"wx001\",\"bizType\":\"代发\","
                                + "\"occurredAt\":\"2026-01-15T10:30:00Z\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.flowId").value("flw_1001"));

        verify(walletFlowMapper, times(1)).insert(any());
    }

    @Test
    @DisplayName("recordFlow：type 枚举非法 → 1003；无内部 token → 403")
    void recordFlowValidation() throws Exception {
        mockMvc.perform(post("/acc/internal/wallet/flows")
                        .header("X-Internal-Token", INTERNAL_TOKEN)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"accountId\":1001,\"type\":\"BOGUS\",\"direction\":\"IN\","
                                + "\"amount\":\"3200.00\",\"occurredAt\":\"2026-01-15T10:30:00Z\"}"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value(1003));

        mockMvc.perform(post("/acc/internal/wallet/flows")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"accountId\":1001,\"type\":\"PAYROLL\",\"direction\":\"IN\","
                                + "\"amount\":\"3200.00\",\"occurredAt\":\"2026-01-15T10:30:00Z\"}"))
                .andExpect(status().isForbidden())
                .andExpect(jsonPath("$.code").value(2002));
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
}
