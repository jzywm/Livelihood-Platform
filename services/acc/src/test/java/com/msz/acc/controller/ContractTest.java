package com.msz.acc.controller;

import com.msz.acc.application.port.RealnameChannelPort;
import com.msz.acc.application.port.PaymentChannelPort;
import com.msz.acc.application.port.ChannelStatementSource;
import com.msz.acc.application.port.FlowStatementReader;
import com.msz.acc.domain.model.Account;
import com.msz.acc.domain.model.RealnameRecord;
import com.msz.acc.domain.model.WalletBinding;
import com.msz.acc.domain.model.WalletFlow;
import com.msz.acc.infrastructure.captcha.CaptchaService;
import com.msz.acc.repository.AccountMapper;
import com.msz.acc.repository.IdempotencyRecordMapper;
import com.msz.acc.repository.RealnameRecordMapper;
import com.msz.acc.repository.ReconcileTaskMapper;
import com.msz.acc.repository.WalletBindingMapper;
import com.msz.acc.repository.WalletFlowMapper;
import com.msz.common.idgen.IdGenerator;
import org.apache.poi.ss.usermodel.Sheet;
import org.apache.poi.xssf.usermodel.XSSFWorkbook;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

import java.io.ByteArrayInputStream;
import java.time.Instant;
import java.util.List;
import java.util.concurrent.atomic.AtomicLong;

import static org.assertj.core.api.Assertions.assertThat;
import static org.hamcrest.Matchers.matchesPattern;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * ContractTest（5.1）：16 个前端接口逐接口契约断言——Envelope code=0 且 data 字段名与
 * openapi.yaml v1.1.0 schema 一致、枚举值合法；400 参数缺 → 1001/1002；枚举非法 → 1003。
 * 依赖 @MockBean 隔离全部端口/流程（契约层不触库）。
 */
@SpringBootTest
@AutoConfigureMockMvc
class ContractTest {

    private static final String TOKEN = "Bearer " + TestJwt.token("1001", "CONSUMER", true);
    private static final Instant NOW = Instant.parse("2026-01-15T10:30:00Z");

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private CaptchaService captchaService;

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
        when(walletFlowMapper.countByAccountAndRange(anyString(), anyLong(), any(), any(), any())).thenReturn(0L);
        when(walletFlowMapper.selectAllByRange(anyString(), any(), any(), anyInt(), anyInt())).thenReturn(List.of());
        when(channelStatementSource.statements(any(), any())).thenReturn(List.of());
        when(flowStatementReader.read(any(), any())).thenReturn(List.of());
    }

    // ---------- captcha ----------

    @Test
    @DisplayName("GET /acc/captcha：缺省 SLIDER，{captchaId,type,expireAt}，不含 answer")
    void captchaChallengeDefaultSlider() throws Exception {
        mockMvc.perform(get("/acc/captcha"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(0))
                .andExpect(jsonPath("$.data.captchaId").value("cap_1001"))
                .andExpect(jsonPath("$.data.type").value("SLIDER"))
                .andExpect(jsonPath("$.data.expireAt").isString())
                .andExpect(jsonPath("$.data.answer").doesNotExist())
                .andExpect(jsonPath("$.traceId").isString());
    }

    @Test
    @DisplayName("GET /acc/captcha?type=IMAGE：降级图形验证码")
    void captchaImageDowngrade() throws Exception {
        mockMvc.perform(get("/acc/captcha").param("type", "IMAGE"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(0))
                .andExpect(jsonPath("$.data.type").value("IMAGE"));
    }

    @Test
    @DisplayName("GET /acc/captcha?type=BOGUS：枚举非法 → 400/1003")
    void captchaInvalidTypeRejected() throws Exception {
        mockMvc.perform(get("/acc/captcha").param("type", "BOGUS"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value(1003));
    }

    @Test
    @DisplayName("POST /acc/captcha/verify：错误偏移 success=false 不抛异常；正确偏移下发一次性 verifyToken")
    void captchaVerifyLifecycle() throws Exception {
        mockMvc.perform(get("/acc/captcha"));
        String captchaId = "cap_1001";

        mockMvc.perform(post("/acc/captcha/verify")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"captchaId\":\"" + captchaId + "\",\"offsetX\":-1}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(0))
                .andExpect(jsonPath("$.data.success").value(false));

        int answer = captchaService.expectedOffset(captchaId);
        mockMvc.perform(post("/acc/captcha/verify")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"captchaId\":\"" + captchaId + "\",\"offsetX\":" + answer + "}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.success").value(true))
                .andExpect(jsonPath("$.data.verifyToken").value("ct_1002"));
    }

    @Test
    @DisplayName("POST /acc/captcha/verify：captchaId 缺失 → 400/1001；坏 JSON → 400/1002")
    void captchaVerifyMissingParam() throws Exception {
        mockMvc.perform(post("/acc/captcha/verify")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"offsetX\":137}"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value(1001));

        mockMvc.perform(post("/acc/captcha/verify")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("not-json"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value(1002));
    }

    // ---------- register ----------

    @Test
    @DisplayName("POST /acc/register：返回 {bizId,authorizeUrl,realNameStatus}")
    void registerReturnsContractFields() throws Exception {
        when(realnameChannelPort.requestAuthorization("rz_1001", "13800138000", "CONSUMER"))
                .thenReturn("https://auth.example/authorize");

        mockMvc.perform(post("/acc/register")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"mobile\":\"13800138000\",\"role\":\"CONSUMER\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(0))
                .andExpect(jsonPath("$.data.bizId").value("rz_1001"))
                .andExpect(jsonPath("$.data.authorizeUrl").value("https://auth.example/authorize"))
                .andExpect(jsonPath("$.data.realNameStatus").value("REALNAMING"));
    }

    @Test
    @DisplayName("POST /acc/register：mobile 缺失 1001 / role 枚举非法 1003 / mobile 格式非法 1002")
    void registerParamValidation() throws Exception {
        mockMvc.perform(post("/acc/register")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"role\":\"CONSUMER\"}"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value(1001));

        mockMvc.perform(post("/acc/register")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"mobile\":\"13800138000\",\"role\":\"HACKER\"}"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value(1003));

        mockMvc.perform(post("/acc/register")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"mobile\":\"123\",\"role\":\"CONSUMER\"}"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value(1002));
    }

    @Test
    @DisplayName("POST /acc/register：mobile_hash 幂等命中返回原 accountId，不再调通道")
    void registerIdempotentReturnsAccountId() throws Exception {
        Account existing = account(999L, "REALNAMED");
        when(accountMapper.selectByMobileHash(anyString())).thenReturn(existing);

        mockMvc.perform(post("/acc/register")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"mobile\":\"13800138000\",\"role\":\"CONSUMER\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(0))
                .andExpect(jsonPath("$.data.accountId").value("acc_999"))
                .andExpect(jsonPath("$.data.realNameStatus").value("REALNAMED"));

        verify(realnameChannelPort, never()).requestAuthorization(anyString(), anyString(), anyString());
    }

    // ---------- realname status ----------

    @Test
    @DisplayName("GET /acc/realname/status：未登录可查，轮询状态机 + 姓名/证件号脱敏")
    void realnameStatusPollingMasked() throws Exception {
        RealnameRecord realnaming = record("rz_1", "REALNAMING", null);
        RealnameRecord realnamed = record("rz_1", "REALNAMED", 1001L);
        when(realnameRecordMapper.selectByBizId("rz_1")).thenReturn(realnaming, realnamed);

        mockMvc.perform(get("/acc/realname/status").param("bizId", "rz_1"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(0))
                .andExpect(jsonPath("$.data.realNameStatus").value("REALNAMING"))
                .andExpect(jsonPath("$.data.realName").value("张*丰"))
                .andExpect(jsonPath("$.data.idNo").value("1301**********1234"));

        mockMvc.perform(get("/acc/realname/status").param("bizId", "rz_1"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.realNameStatus").value("REALNAMED"))
                .andExpect(jsonPath("$.data.accountId").value("acc_1001"));
    }

    @Test
    @DisplayName("GET /acc/realname/status：bizId 缺失 1001 / 不存在 3006(404)")
    void realnameStatusMissingAndNotFound() throws Exception {
        mockMvc.perform(get("/acc/realname/status"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value(1001));

        when(realnameRecordMapper.selectByBizId("rz_none")).thenReturn(null);
        mockMvc.perform(get("/acc/realname/status").param("bizId", "rz_none"))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.code").value(3006));
    }

    // ---------- nfc ----------

    @Test
    @DisplayName("POST /acc/realname/nfc：M2 占位，基础实名 → {realNameLevel:BASE}")
    void nfcPlaceholderReturnsBase() throws Exception {
        when(accountMapper.selectById(1001L)).thenReturn(account(1001L, "REALNAMED"));

        mockMvc.perform(post("/acc/realname/nfc")
                        .header("Authorization", TOKEN)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"idCard\":\"130123199001011234\",\"faceToken\":\"ft_1\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(0))
                .andExpect(jsonPath("$.data.realNameLevel").value("BASE"));
    }

    @Test
    @DisplayName("POST /acc/realname/nfc：未基础实名 → 3001；idCard 缺失 → 1001")
    void nfcNotRealnamedAndMissingBody() throws Exception {
        when(accountMapper.selectById(1001L)).thenReturn(account(1001L, "REALNAMING"));
        mockMvc.perform(post("/acc/realname/nfc")
                        .header("Authorization", TOKEN)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"idCard\":\"130123199001011234\",\"faceToken\":\"ft_1\"}"))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.code").value(3001));

        mockMvc.perform(post("/acc/realname/nfc")
                        .header("Authorization", TOKEN)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{}"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value(1001));
    }

    // ---------- me ----------

    @Test
    @DisplayName("GET /acc/me：字段与 openapi Account 一致，mobile/realName 脱敏")
    void meMasked() throws Exception {
        Account account = account(1001L, "REALNAMED");
        account.setMobile("13800138000");
        when(accountMapper.selectById(1001L)).thenReturn(account);

        mockMvc.perform(get("/acc/me").header("Authorization", TOKEN))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(0))
                .andExpect(jsonPath("$.data.accountId").value("acc_1001"))
                .andExpect(jsonPath("$.data.role").value("CONSUMER"))
                .andExpect(jsonPath("$.data.realNameStatus").value("REALNAMED"))
                .andExpect(jsonPath("$.data.walletStatus").value("ACTIVE"))
                .andExpect(jsonPath("$.data.mobile").value(matchesPattern("^\\d{3}\\*{4}\\d{4}$")))
                .andExpect(jsonPath("$.data.realName").value("张*丰"))
                .andExpect(jsonPath("$.data.createdAt").isString());
    }

    // ---------- wallet flows / summary / export ----------

    @Test
    @DisplayName("GET /acc/wallet/flows：PageResult 结构与 WalletFlow 字段名一致")
    void walletFlowsPageContract() throws Exception {
        when(walletFlowMapper.countByAccountAndRange(eq("wallet_flow_202601"), eq(1001L), any(), any(), any())).thenReturn(1L);
        when(walletFlowMapper.selectByAccountAndRange(eq("wallet_flow_202601"), eq(1001L), any(), any(), anyInt(), anyInt(), any()))
                .thenReturn(List.of(flow(1L, 1001L)));

        mockMvc.perform(get("/acc/wallet/flows")
                        .header("Authorization", TOKEN)
                        .param("from", "2026-01-01").param("to", "2026-01-31"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(0))
                .andExpect(jsonPath("$.data.list[0].flowId").value("flw_1"))
                .andExpect(jsonPath("$.data.list[0].type").value("PAYROLL"))
                .andExpect(jsonPath("$.data.list[0].direction").value("IN"))
                .andExpect(jsonPath("$.data.list[0].amount").value("3200.00"))
                .andExpect(jsonPath("$.data.list[0].status").value("SUCCEEDED"))
                .andExpect(jsonPath("$.data.list[0].channelOrderNo").value("wx001"))
                .andExpect(jsonPath("$.data.list[0].bizType").value("代发"))
                .andExpect(jsonPath("$.data.list[0].hash").isString())
                .andExpect(jsonPath("$.data.list[0].occurredAt").isString())
                .andExpect(jsonPath("$.data.total").value(1))
                .andExpect(jsonPath("$.data.page").value(1))
                .andExpect(jsonPath("$.data.pageSize").value(20));
    }

    @Test
    @DisplayName("GET /acc/wallet/flows：type 枚举非法 1003 / page 非数字 1002 / 日期非法 1002")
    void walletFlowsParamValidation() throws Exception {
        mockMvc.perform(get("/acc/wallet/flows").header("Authorization", TOKEN).param("type", "BOGUS"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value(1003));

        mockMvc.perform(get("/acc/wallet/flows").header("Authorization", TOKEN).param("page", "abc"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value(1002));

        mockMvc.perform(get("/acc/wallet/flows").header("Authorization", TOKEN).param("from", "2026-13-99"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value(1002));
    }

    @Test
    @DisplayName("GET /acc/wallet/summary：{totalIn,totalOut,byType[]}")
    void walletSummaryContract() throws Exception {
        mockMvc.perform(get("/acc/wallet/summary").header("Authorization", TOKEN))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(0))
                .andExpect(jsonPath("$.data.totalIn").value("0"))
                .andExpect(jsonPath("$.data.totalOut").value("0"))
                .andExpect(jsonPath("$.data.byType").isArray());
    }

    @Test
    @DisplayName("GET /acc/wallet/flows/export：xlsx Content-Type + 最小合法工作簿（表头+行）")
    void exportXlsx() throws Exception {
        when(walletFlowMapper.countByAccountAndRange(anyString(), anyLong(), any(), any(), any())).thenReturn(1L);
        when(walletFlowMapper.selectByAccountAndRange(anyString(), anyLong(), any(), any(), anyInt(), anyInt(), any()))
                .thenReturn(List.of(flow(1L, 1001L)));

        byte[] bytes = mockMvc.perform(get("/acc/wallet/flows/export")
                        .header("Authorization", TOKEN)
                        .param("from", "2026-01-01").param("to", "2026-01-31"))
                .andExpect(status().isOk())
                .andExpect(header().string("Content-Type",
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))
                .andReturn().getResponse().getContentAsByteArray();

        try (XSSFWorkbook workbook = new XSSFWorkbook(new ByteArrayInputStream(bytes))) {
            Sheet sheet = workbook.getSheet("flows");
            assertThat(sheet.getLastRowNum()).isEqualTo(1);
            assertThat(sheet.getRow(0).getCell(0).getStringCellValue()).isEqualTo("flowId");
            assertThat(sheet.getRow(1).getCell(0).getStringCellValue()).isEqualTo("flw_1");
        }
    }

    @Test
    @DisplayName("GET /acc/wallet/flows/export：mfa=false → 403/2003")
    void exportMfaRequired() throws Exception {
        mockMvc.perform(get("/acc/wallet/flows/export")
                        .header("Authorization", "Bearer " + TestJwt.token("1001", "CONSUMER", false)))
                .andExpect(status().isForbidden())
                .andExpect(jsonPath("$.code").value(2003));
    }

    // ---------- binding ----------

    @Test
    @DisplayName("POST /acc/wallet/bind：成功返回 Binding，payeeAccount/payeeName 脱敏")
    void bindSuccessMasked() throws Exception {
        when(accountMapper.selectById(1001L)).thenReturn(account(1001L, "REALNAMED"));
        when(walletBindingMapper.selectByAccountAndChannel(1001L, "WECHAT")).thenReturn(null);
        when(idempotencyRecordMapper.insertIgnore(anyString(), anyString(), anyInt(), anyString())).thenReturn(1);
        when(walletBindingMapper.selectById("bnd_1001")).thenReturn(binding("bnd_1001", 1001L, "WECHAT"));

        mockMvc.perform(post("/acc/wallet/bind")
                        .header("Authorization", TOKEN)
                        .header("Idempotency-Key", "k-bind-1")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"channel\":\"WECHAT\",\"payeeAccount\":\"6222021234567890\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(0))
                .andExpect(jsonPath("$.data.bindingId").value("bnd_1001"))
                .andExpect(jsonPath("$.data.channel").value("WECHAT"))
                .andExpect(jsonPath("$.data.payeeAccount").value("6222*********890"))
                .andExpect(jsonPath("$.data.payeeName").value("张*丰"))
                .andExpect(jsonPath("$.data.status").value("BOUND"))
                .andExpect(jsonPath("$.data.createdAt").isString());
    }

    @Test
    @DisplayName("POST /acc/wallet/bind：Idempotency-Key 缺失 1001 / channel 枚举非法 1003")
    void bindParamValidation() throws Exception {
        when(accountMapper.selectById(1001L)).thenReturn(account(1001L, "REALNAMED"));

        mockMvc.perform(post("/acc/wallet/bind")
                        .header("Authorization", TOKEN)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"channel\":\"WECHAT\",\"payeeAccount\":\"6222021234567890\"}"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value(1001));

        mockMvc.perform(post("/acc/wallet/bind")
                        .header("Authorization", TOKEN)
                        .header("Idempotency-Key", "k-bind-2")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"channel\":\"CASH\",\"payeeAccount\":\"6222021234567890\"}"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value(1003));
    }

    @Test
    @DisplayName("GET /acc/wallet/bindings：列表脱敏")
    void bindingsListMasked() throws Exception {
        when(walletBindingMapper.listByAccount(1001L))
                .thenReturn(List.of(binding("bnd_1", 1001L, "WECHAT"), binding("bnd_2", 1001L, "ALIPAY")));

        mockMvc.perform(get("/acc/wallet/bindings").header("Authorization", TOKEN))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(0))
                .andExpect(jsonPath("$.data.length()").value(2))
                .andExpect(jsonPath("$.data[0].payeeAccount").value("6222*********890"))
                .andExpect(jsonPath("$.data[0].payeeName").value("张*丰"));
    }

    @Test
    @DisplayName("PUT /acc/wallet/bindings/{bindingId}：换绑成功返回脱敏 Binding")
    void bindingReplace() throws Exception {
        when(accountMapper.selectById(1001L)).thenReturn(account(1001L, "REALNAMED"));
        when(walletBindingMapper.selectById("bnd_old")).thenReturn(binding("bnd_old", 1001L, "WECHAT"));
        when(walletBindingMapper.selectByAccountAndChannel(1001L, "ALIPAY")).thenReturn(null);
        when(idempotencyRecordMapper.insertIgnore(anyString(), anyString(), anyInt(), anyString())).thenReturn(1);
        when(walletBindingMapper.selectById("bnd_1001")).thenReturn(binding("bnd_1001", 1001L, "ALIPAY"));

        mockMvc.perform(put("/acc/wallet/bindings/bnd_old")
                        .header("Authorization", TOKEN)
                        .header("Idempotency-Key", "k-replace")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"channel\":\"ALIPAY\",\"payeeAccount\":\"6222021234567890\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(0))
                .andExpect(jsonPath("$.data.bindingId").value("bnd_1001"))
                .andExpect(jsonPath("$.data.channel").value("ALIPAY"))
                .andExpect(jsonPath("$.data.payeeAccount").value("6222*********890"));
    }

    @Test
    @DisplayName("DELETE /acc/wallet/bindings/{bindingId}：返回 {bindingId,status:UNBOUND}")
    void bindingUnbind() throws Exception {
        when(walletBindingMapper.selectById("bnd_1")).thenReturn(binding("bnd_1", 1001L, "WECHAT"));

        mockMvc.perform(delete("/acc/wallet/bindings/bnd_1").header("Authorization", TOKEN))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(0))
                .andExpect(jsonPath("$.data.bindingId").value("bnd_1"))
                .andExpect(jsonPath("$.data.status").value("UNBOUND"));
    }

    // ---------- funds ----------

    @Test
    @DisplayName("GET /acc/funds/audit：REGULATOR 可见 FundsAuditFlow 字段（含 reconcileStatus）")
    void auditRegulatorContract() throws Exception {
        String regulatorToken = "Bearer " + TestJwt.token("9001", "REGULATOR", true);
        when(walletFlowMapper.selectAllByRange(anyString(), any(), any(), anyInt(), anyInt()))
                .thenReturn(List.of(flow(1L, 1001L)));
        when(reconcileTaskMapper.selectAllByRange(any(), any())).thenReturn(List.of());

        mockMvc.perform(get("/acc/funds/audit")
                        .header("Authorization", regulatorToken)
                        .param("from", "2026-01-01").param("to", "2026-01-31"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(0))
                .andExpect(jsonPath("$.data.list[0].flowId").value("flw_1"))
                .andExpect(jsonPath("$.data.list[0].payeeId").value("acc_1001"))
                .andExpect(jsonPath("$.data.list[0].reconcileStatus").value("PENDING"))
                .andExpect(jsonPath("$.data.total").value(1));
    }

    @Test
    @DisplayName("GET /acc/funds/audit：非监管 → 403/2002；reconcileStatus 枚举非法 → 1003")
    void auditForbiddenAndEnumValidation() throws Exception {
        mockMvc.perform(get("/acc/funds/audit").header("Authorization", TOKEN))
                .andExpect(status().isForbidden())
                .andExpect(jsonPath("$.code").value(2002));

        String regulatorToken = "Bearer " + TestJwt.token("9001", "REGULATOR", true);
        mockMvc.perform(get("/acc/funds/audit")
                        .header("Authorization", regulatorToken)
                        .param("reconcileStatus", "BOGUS"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value(1003));
    }

    @Test
    @DisplayName("POST /acc/funds/reconcile：无差异 → {reconcileId,status:DONE,diffCount:0}")
    void reconcileDone() throws Exception {
        String regulatorToken = "Bearer " + TestJwt.token("9001", "REGULATOR", true);
        when(idempotencyRecordMapper.insertIgnore(anyString(), anyString(), anyInt(), anyString())).thenReturn(1);

        mockMvc.perform(post("/acc/funds/reconcile")
                        .header("Authorization", regulatorToken)
                        .header("Idempotency-Key", "k-rec-1")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"from\":\"2026-01-01\",\"to\":\"2026-01-31\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(0))
                .andExpect(jsonPath("$.data.reconcileId").value("rec_1001"))
                .andExpect(jsonPath("$.data.status").value("DONE"))
                .andExpect(jsonPath("$.data.diffCount").value(0));
    }

    @Test
    @DisplayName("POST /acc/funds/reconcile：Idempotency-Key 缺失 → 1001")
    void reconcileMissingKey() throws Exception {
        String regulatorToken = "Bearer " + TestJwt.token("9001", "REGULATOR", true);
        mockMvc.perform(post("/acc/funds/reconcile")
                        .header("Authorization", regulatorToken)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"from\":\"2026-01-01\",\"to\":\"2026-01-31\"}"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value(1001));
    }

    // ---------- account close ----------

    @Test
    @DisplayName("POST /acc/account/close：返回 {accountId,closedAt}")
    void accountClose() throws Exception {
        when(accountMapper.selectById(1001L)).thenReturn(account(1001L, "REALNAMED"));
        when(realnameRecordMapper.selectByAccountIdAndStatus(1001L, "REALNAMING")).thenReturn(List.of());

        mockMvc.perform(post("/acc/account/close")
                        .header("Authorization", TOKEN)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"reason\":\"不再使用\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(0))
                .andExpect(jsonPath("$.data.accountId").value("acc_1001"))
                .andExpect(jsonPath("$.data.closedAt").isString());
    }

    // ---------- fixtures ----------

    private static Account account(long accountId, String realNameStatus) {
        Account account = new Account();
        account.setAccountId(accountId);
        account.setRole("CONSUMER");
        account.setMobile("13800138000");
        account.setRealNameStatus(realNameStatus);
        account.setWalletStatus("ACTIVE");
        account.setRealName("张三丰");
        account.setIdNo("130123199001011234");
        account.setCreatedAt(NOW);
        return account;
    }

    private static RealnameRecord record(String bizId, String status, Long accountId) {
        RealnameRecord record = new RealnameRecord();
        record.setBizId(bizId);
        record.setAccountId(accountId);
        record.setChannel("WECHAT");
        record.setOpenId("openid-1");
        record.setName("张三丰");
        record.setIdNo("130123199001011234");
        record.setStatus(status);
        record.setLevel("BASE");
        record.setCreatedAt(NOW);
        return record;
    }

    private static WalletFlow flow(long flowId, long accountId) {
        WalletFlow flow = new WalletFlow();
        flow.setFlowId(flowId);
        flow.setAccountId(accountId);
        flow.setType("PAYROLL");
        flow.setDirection("IN");
        flow.setAmount("3200.00");
        flow.setStatus("SUCCEEDED");
        flow.setChannelOrderNo("wx001");
        flow.setBizType("代发");
        flow.setHash("a3f2b1c9d8e7f6a5");
        flow.setOccurredAt(NOW);
        flow.setCreatedAt(NOW);
        return flow;
    }

    private static WalletBinding binding(String bindingId, long accountId, String channel) {
        WalletBinding binding = new WalletBinding();
        binding.setBindingId(bindingId);
        binding.setAccountId(accountId);
        binding.setChannel(channel);
        binding.setPayeeAccount("6222021234567890");
        binding.setPayeeName("张三丰");
        binding.setStatus("BOUND");
        binding.setCreatedAt(NOW);
        return binding;
    }
}
