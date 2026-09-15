package com.msz.acc.controller;

import com.msz.acc.application.port.ChannelStatementSource;
import com.msz.acc.application.port.FlowStatementReader;
import com.msz.acc.domain.model.Account;
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

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * AuthMatrixTest（5.2 续）：六方角色均可访问 /acc/me；仅 REGULATOR 可 audit/reconcile（其余 403）；
 * internal 接口无/错 token → 403。
 */
@SpringBootTest
@AutoConfigureMockMvc
class AuthMatrixTest {

    private static final List<String> ROLES =
            List.of("CONSUMER", "MERCHANT", "SUPPLIER", "WORKER", "REGULATOR", "OPERATOR");

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

    @MockBean
    private ChannelStatementSource channelStatementSource;

    @MockBean
    private FlowStatementReader flowStatementReader;

    @BeforeEach
    void setUp() {
        when(idGenerator.nextId()).thenAnswer(invocation -> new AtomicLong(1000).incrementAndGet());
        when(walletFlowMapper.selectAllByRange(anyString(), any(), any(), anyInt(), anyInt())).thenReturn(List.of());
        when(reconcileTaskMapper.selectAllByRange(any(), any())).thenReturn(List.of());
        when(idempotencyRecordMapper.insertIgnore(anyString(), anyString(), anyInt(), anyString())).thenReturn(1);
        when(channelStatementSource.statements(any(), any())).thenReturn(List.of());
        when(flowStatementReader.read(any(), any())).thenReturn(List.of());
    }

    @Test
    @DisplayName("六方角色均可访问 /acc/me（角色回显）")
    void sixRolesCanAccessMe() throws Exception {
        for (String role : ROLES) {
            when(accountMapper.selectById(anyLong())).thenReturn(account(1001L, role));
            mockMvc.perform(get("/acc/me").with(TestIdentity.of("1001", role, true)))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.code").value(0))
                    .andExpect(jsonPath("$.data.accountId").value("acc_1001"))
                    .andExpect(jsonPath("$.data.role").value(role));
        }
    }

    @Test
    @DisplayName("audit：仅 REGULATOR 可访问，其余五方 403 + 2002")
    void onlyRegulatorCanAudit() throws Exception {
        for (String role : ROLES) {
            mockMvc.perform(get("/acc/funds/audit")
                            .with(TestIdentity.of("9001", role, true)))
                    .andExpect("REGULATOR".equals(role) ? status().isOk() : status().isForbidden())
                    .andExpect(jsonPath("$.code").value("REGULATOR".equals(role) ? 0 : 2002));
        }
    }

    @Test
    @DisplayName("reconcile：仅 REGULATOR 可触发，其余五方 403 + 2002")
    void onlyRegulatorCanReconcile() throws Exception {
        for (String role : ROLES) {
            mockMvc.perform(post("/acc/funds/reconcile")
                            .with(TestIdentity.of("9001", role, true))
                            .header("Idempotency-Key", "k-" + role)
                            .contentType(MediaType.APPLICATION_JSON)
                            .content("{\"from\":\"2026-01-01\",\"to\":\"2026-01-31\"}"))
                    .andExpect("REGULATOR".equals(role) ? status().isOk() : status().isForbidden())
                    .andExpect(jsonPath("$.code").value("REGULATOR".equals(role) ? 0 : 2002));
        }
    }

    @Test
    @DisplayName("internal 接口：无 token → 403；错误 token → 403")
    void internalTokenRequired() throws Exception {
        mockMvc.perform(get("/acc/internal/account/1001"))
                .andExpect(status().isForbidden())
                .andExpect(jsonPath("$.code").value(2002));

        mockMvc.perform(get("/acc/internal/account/1001").header("X-Internal-Token", "wrong-token"))
                .andExpect(status().isForbidden())
                .andExpect(jsonPath("$.code").value(2002));
    }

    private static Account account(long accountId, String role) {
        Account account = new Account();
        account.setAccountId(accountId);
        account.setRole(role);
        account.setMobile("13800138000");
        account.setRealNameStatus("REALNAMED");
        account.setWalletStatus("ACTIVE");
        account.setRealName("张三丰");
        account.setCreatedAt(Instant.parse("2026-01-15T10:30:00Z"));
        return account;
    }
}
