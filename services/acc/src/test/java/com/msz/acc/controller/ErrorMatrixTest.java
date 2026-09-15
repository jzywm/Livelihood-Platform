package com.msz.acc.controller;

import com.msz.acc.application.port.ChannelStatement;
import com.msz.acc.application.port.ChannelStatementSource;
import com.msz.acc.application.port.FlowStatementReader;
import com.msz.acc.application.port.PaymentChannelPort;
import com.msz.acc.application.port.RealnameChannelPort;
import com.msz.acc.domain.model.Account;
import com.msz.acc.domain.model.WalletBinding;
import com.msz.acc.domain.support.AccBusinessException;
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
import org.springframework.dao.DataAccessException;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.request.RequestPostProcessor;
import org.springframework.test.web.servlet.MockMvc;

import java.time.Instant;
import java.util.List;
import java.util.concurrent.TimeoutException;
import java.util.concurrent.atomic.AtomicLong;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * ErrorMatrixTest（5.2）：2001/2002/2003/3001/3002/3006/3008/3009/4001/4002/5000/5001/5002
 * 逐码触发并断言 Envelope code + message 口径（对齐 _common ErrorCode）+ HTTP 状态分段。
 */
@SpringBootTest
@AutoConfigureMockMvc
class ErrorMatrixTest {

    private static final RequestPostProcessor CONSUMER = TestIdentity.of("1001", "CONSUMER", true);

    @Autowired
    private MockMvc mockMvc;

    @MockBean
    private IdGenerator idGenerator;

    @MockBean
    private RealnameChannelPort realnameChannelPort;

    @MockBean
    private PaymentChannelPort paymentChannelPort;

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

    private final AtomicLong seq = new AtomicLong(1000);

    @BeforeEach
    void setUp() {
        when(idGenerator.nextId()).thenAnswer(invocation -> seq.incrementAndGet());
        when(accountMapper.selectByMobileHash(anyString())).thenReturn(null);
        when(walletFlowMapper.countByAccountAndRange(anyString(), anyLong(), any(), any(), any())).thenReturn(0L);
        when(flowStatementReader.read(any(), any())).thenReturn(List.of());
    }

    @Test
    @DisplayName("2001：无 token / 坏签名 → 401 + code 2001 + message 口径")
    void error2001NoTokenAndBadSignature() throws Exception {
        mockMvc.perform(get("/acc/me"))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.code").value(2001))
                .andExpect(jsonPath("$.message").value("未登录 / Token 失效"))
                .andExpect(jsonPath("$.traceId").isString());

        // 网关唯一鉴权点后:空白身份头同样视为未认证(fail-closed)
        mockMvc.perform(get("/acc/me").header("X-User-Id", " "))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.code").value(2001));
    }

    @Test
    @DisplayName("2002：越权（A 的 token 查 B 的 flows / 操作 B 的 binding）→ 403 + code 2002")
    void error2002CrossAccountAccess() throws Exception {
        when(walletFlowMapper.selectByAccountAndRange(anyString(), anyLong(), any(), any(), anyInt(), anyInt(), any()))
                .thenThrow(new AccBusinessException(2002, "越权访问他人流水"));
        mockMvc.perform(get("/acc/wallet/flows")
                        .with(CONSUMER)
                        .param("from", "2026-01-01").param("to", "2026-01-31"))
                .andExpect(status().isForbidden())
                .andExpect(jsonPath("$.code").value(2002))
                .andExpect(jsonPath("$.message").value("无权限 / 越权"));

        when(accountMapper.selectById(1001L)).thenReturn(account(1001L, "REALNAMED"));
        WalletBinding others = new WalletBinding();
        others.setBindingId("bnd_b");
        others.setAccountId(2002L);
        others.setChannel("WECHAT");
        when(walletBindingMapper.selectById("bnd_b")).thenReturn(others);
        mockMvc.perform(put("/acc/wallet/bindings/bnd_b")
                        .with(CONSUMER)
                        .header("Idempotency-Key", "k-x")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"channel\":\"ALIPAY\",\"payeeAccount\":\"6222021234567890\"}"))
                .andExpect(status().isForbidden())
                .andExpect(jsonPath("$.code").value(2002));
    }

    @Test
    @DisplayName("2003：MFA 检查点（AuthContext.mfa=false 访问 export）→ 403 + code 2003")
    void error2003MfaRequired() throws Exception {
        mockMvc.perform(get("/acc/wallet/flows/export")
                        .with(TestIdentity.of("1001", "CONSUMER", false)))
                .andExpect(status().isForbidden())
                .andExpect(jsonPath("$.code").value(2003))
                .andExpect(jsonPath("$.message").value("MFA 未通过"));
    }

    @Test
    @DisplayName("3001：未实名绑定 → 422 + code 3001")
    void error3001NotRealnamedBind() throws Exception {
        when(accountMapper.selectById(1001L)).thenReturn(account(1001L, "REALNAMING"));

        mockMvc.perform(post("/acc/wallet/bind")
                        .with(CONSUMER)
                        .header("Idempotency-Key", "k-3001")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"channel\":\"WECHAT\",\"payeeAccount\":\"6222021234567890\"}"))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.code").value(3001))
                .andExpect(jsonPath("$.message").value("实名未完成"));
    }

    @Test
    @DisplayName("3002：户名与实名不符 → 422 + code 3002")
    void error3002PayeeNameMismatch() throws Exception {
        when(accountMapper.selectById(1001L)).thenReturn(account(1001L, "REALNAMED"));
        doThrow(new AccBusinessException(3002, "户名与实名不一致"))
                .when(paymentChannelPort).verifyPayee(anyLong(), anyString(), anyString(), anyString());

        mockMvc.perform(post("/acc/wallet/bind")
                        .with(CONSUMER)
                        .header("Idempotency-Key", "k-3002")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"channel\":\"WECHAT\",\"payeeAccount\":\"6222021234567890\"}"))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.code").value(3002))
                .andExpect(jsonPath("$.message").value("实名不匹配"));
    }

    @Test
    @DisplayName("3006：bizId 不存在 → 404 + code 3006")
    void error3006ObjectNotFound() throws Exception {
        when(realnameRecordMapper.selectByBizId("rz_none")).thenReturn(null);

        mockMvc.perform(get("/acc/realname/status").param("bizId", "rz_none"))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.code").value(3006))
                .andExpect(jsonPath("$.message").value("对象不存在"));
    }

    @Test
    @DisplayName("3008：同 Idempotency-Key 二击（唯一键冲突）→ 422 + code 3008")
    void error3008DuplicateIdempotencyKey() throws Exception {
        when(accountMapper.selectById(1001L)).thenReturn(account(1001L, "REALNAMED"));
        when(walletBindingMapper.selectByAccountAndChannel(1001L, "WECHAT")).thenReturn(null);
        when(idempotencyRecordMapper.insertIgnore(anyString(), anyString(), anyInt(), anyString()))
                .thenThrow(new DuplicateKeyException("uk_idempotency_key 冲突"));

        mockMvc.perform(post("/acc/wallet/bind")
                        .with(CONSUMER)
                        .header("Idempotency-Key", "k-dup")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"channel\":\"WECHAT\",\"payeeAccount\":\"6222021234567890\"}"))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.code").value(3008))
                .andExpect(jsonPath("$.message").value("幂等键冲突"));
    }

    @Test
    @DisplayName("3009：对账 diff（fake ChannelStatementSource 注入 diff）→ Envelope code 0 + data.status=DIFF")
    void error3009ReconcileDiff() throws Exception {
        RequestPostProcessor regulator = TestIdentity.of("9001", "REGULATOR", true);
        when(idempotencyRecordMapper.insertIgnore(anyString(), anyString(), anyInt(), anyString())).thenReturn(1);
        when(channelStatementSource.statements(any(), any())).thenReturn(List.of(
                new ChannelStatement("wx-only-channel", "3200.00", Instant.parse("2026-01-15T10:30:00Z"))));

        mockMvc.perform(post("/acc/funds/reconcile")
                        .with(regulator)
                        .header("Idempotency-Key", "k-3009")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"from\":\"2026-01-01\",\"to\":\"2026-01-31\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(0))
                .andExpect(jsonPath("$.data.status").value("DIFF"))
                .andExpect(jsonPath("$.data.diffCount").value(1));
    }

    @Test
    @DisplayName("4001：实名通道不可用 → 502 + code 4001")
    void error4001RealnameChannelUnavailable() throws Exception {
        when(realnameChannelPort.requestAuthorization(anyString(), anyString(), anyString()))
                .thenThrow(new AccBusinessException(4001, "实名通道不可用"));

        mockMvc.perform(post("/acc/register")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"mobile\":\"13800138000\",\"role\":\"CONSUMER\"}"))
                .andExpect(status().isBadGateway())
                .andExpect(jsonPath("$.code").value(4001))
                .andExpect(jsonPath("$.message").value("实名接口失败"));
    }

    @Test
    @DisplayName("4002：支付通道失败/超时 → 502 + code 4002")
    void error4002PaymentChannelFailed() throws Exception {
        when(accountMapper.selectById(1001L)).thenReturn(account(1001L, "REALNAMED"));
        doThrow(new AccBusinessException(4002, "支付通道失败 / 超时"))
                .when(paymentChannelPort).verifyPayee(anyLong(), anyString(), anyString(), anyString());

        mockMvc.perform(post("/acc/wallet/bind")
                        .with(CONSUMER)
                        .header("Idempotency-Key", "k-4002")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"channel\":\"WECHAT\",\"payeeAccount\":\"6222021234567890\"}"))
                .andExpect(status().isBadGateway())
                .andExpect(jsonPath("$.code").value(4002))
                .andExpect(jsonPath("$.message").value("支付通道失败 / 超时"));
    }

    @Test
    @DisplayName("5000：未捕获异常 → 500 + code 5000 + message 统一「内部错误」+ traceId")
    void error5000Unexpected() throws Exception {
        when(walletFlowMapper.selectByAccountAndRange(anyString(), anyLong(), any(), any(), anyInt(), anyInt(), any()))
                .thenThrow(new IllegalStateException("boom"));

        mockMvc.perform(get("/acc/wallet/summary").with(CONSUMER))
                .andExpect(status().isInternalServerError())
                .andExpect(jsonPath("$.code").value(5000))
                .andExpect(jsonPath("$.message").value("内部错误"))
                .andExpect(jsonPath("$.traceId").isString());
    }

    @Test
    @DisplayName("5001：DB 异常（DataAccessException）→ 500 + code 5001")
    void error5001DataAccess() throws Exception {
        when(accountMapper.selectById(anyLong())).thenThrow(new DataAccessException("db down") {
        });

        mockMvc.perform(get("/acc/me").with(CONSUMER))
                .andExpect(status().isInternalServerError())
                .andExpect(jsonPath("$.code").value(5001))
                .andExpect(jsonPath("$.message").value("数据库错误"));
    }

    @Test
    @DisplayName("5002：依赖超时（TimeoutException 场景映射）→ 500 + code 5002")
    void error5002Timeout() throws Exception {
        when(realnameChannelPort.requestAuthorization(anyString(), anyString(), anyString()))
                .thenAnswer(invocation -> {
                    throw new TimeoutException("channel timeout");
                });

        mockMvc.perform(post("/acc/register")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"mobile\":\"13800138000\",\"role\":\"CONSUMER\"}"))
                .andExpect(status().isInternalServerError())
                .andExpect(jsonPath("$.code").value(5002))
                .andExpect(jsonPath("$.message").value("依赖超时 / 熔断"));
    }

    private static Account account(long accountId, String realNameStatus) {
        Account account = new Account();
        account.setAccountId(accountId);
        account.setRole("CONSUMER");
        account.setRealNameStatus(realNameStatus);
        account.setWalletStatus("ACTIVE");
        account.setRealName("张三丰");
        account.setCreatedAt(Instant.parse("2026-01-15T10:30:00Z"));
        return account;
    }
}
