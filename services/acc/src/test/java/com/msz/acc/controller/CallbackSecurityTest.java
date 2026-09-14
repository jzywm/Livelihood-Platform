package com.msz.acc.controller;

import com.msz.acc.domain.model.RealnameRecord;
import com.msz.acc.infrastructure.crypto.HmacSignatureVerifier;
import com.msz.acc.repository.AccountMapper;
import com.msz.acc.repository.RealnameRecordMapper;
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
import java.util.concurrent.atomic.AtomicLong;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * CallbackSecurityTest（5.3）：回调仅内网（无 X-Internal-Token → 403）+ 验签（坏签名 → 4001 拒收）
 * + 幂等（重放同 bizId → 200）。
 */
@SpringBootTest
@AutoConfigureMockMvc
class CallbackSecurityTest {

    private static final String INTERNAL_TOKEN = "acc-internal-test-token";

    @Autowired
    private MockMvc mockMvc;

    @MockBean
    private IdGenerator idGenerator;

    @MockBean
    private AccountMapper accountMapper;

    @MockBean
    private RealnameRecordMapper realnameRecordMapper;

    @BeforeEach
    void setUp() {
        when(idGenerator.nextId()).thenAnswer(invocation -> new AtomicLong(1000).incrementAndGet());
    }

    @Test
    @DisplayName("无 X-Internal-Token → 403 拒绝（外部调用被拒）")
    void noInternalTokenRejected() throws Exception {
        mockMvc.perform(post("/acc/realname/callback")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(callbackJson("rz_1", true)))
                .andExpect(status().isForbidden())
                .andExpect(jsonPath("$.code").value(2002));
    }

    @Test
    @DisplayName("错误 X-Internal-Token → 403 拒绝")
    void wrongInternalTokenRejected() throws Exception {
        mockMvc.perform(post("/acc/realname/callback")
                        .header("X-Internal-Token", "wrong")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(callbackJson("rz_1", true)))
                .andExpect(status().isForbidden())
                .andExpect(jsonPath("$.code").value(2002));
    }

    @Test
    @DisplayName("验签失败（篡改/错密钥）→ 4001 拒收且不建户")
    void tamperedSignatureRejected() throws Exception {
        when(realnameRecordMapper.selectByBizId("rz_1")).thenReturn(record("rz_1", "REALNAMING"));

        long ts = Instant.now().getEpochSecond();
        String payload = "rz_1|openid-1|张三丰|130123199001011234|true|" + ts + "|nonce1234";
        String badSign = new HmacSignatureVerifier("wrong-secret").sign(payload);
        String body = "{\"bizId\":\"rz_1\",\"openId\":\"openid-1\",\"name\":\"张三丰\","
                + "\"idNo\":\"130123199001011234\",\"pass\":true,\"sign\":\"" + badSign + "\","
                + "\"timestamp\":" + ts + ",\"nonce\":\"nonce1234\"}";

        mockMvc.perform(post("/acc/realname/callback")
                        .header("X-Internal-Token", INTERNAL_TOKEN)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(body))
                .andExpect(status().isBadGateway())
                .andExpect(jsonPath("$.code").value(4001));

        verify(accountMapper, never()).insert(any());
    }

    @Test
    @DisplayName("重放同 bizId（已 REALNAMED）→ 幂等 200 返回原账户")
    void replaySameBizIdIdempotent() throws Exception {
        RealnameRecord realnamed = record("rz_1", "REALNAMED");
        realnamed.setAccountId(1001L);
        when(realnameRecordMapper.selectByBizId("rz_1")).thenReturn(realnamed);

        mockMvc.perform(post("/acc/realname/callback")
                        .header("X-Internal-Token", INTERNAL_TOKEN)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(callbackJson("rz_1", true)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(0))
                .andExpect(jsonPath("$.data.bizId").value("rz_1"))
                .andExpect(jsonPath("$.data.status").value("REALNAMED"))
                .andExpect(jsonPath("$.data.accountId").value("acc_1001"));

        verify(accountMapper, never()).insert(any());
    }

    /** 以配置默认密钥（acc-callback-test-secret）正确签名的回调报文。 */
    private static String callbackJson(String bizId, boolean pass) {
        long ts = Instant.now().getEpochSecond();
        String payload = bizId + "|openid-1|张三丰|130123199001011234|" + pass + "|" + ts + "|nonce1234";
        String sign = new HmacSignatureVerifier("acc-callback-test-secret").sign(payload);
        return "{\"bizId\":\"" + bizId + "\",\"openId\":\"openid-1\",\"name\":\"张三丰\","
                + "\"idNo\":\"130123199001011234\",\"pass\":" + pass + ",\"sign\":\"" + sign + "\","
                + "\"timestamp\":" + ts + ",\"nonce\":\"nonce1234\"}";
    }

    private static RealnameRecord record(String bizId, String status) {
        RealnameRecord record = new RealnameRecord();
        record.setBizId(bizId);
        record.setChannel("WECHAT");
        record.setOpenId("pending_" + bizId);
        record.setName("");
        record.setIdNo("");
        record.setStatus(status);
        record.setLevel("BASE");
        record.setCreatedAt(Instant.parse("2026-01-01T00:00:00Z"));
        return record;
    }
}
