package com.msz.acc.repository;

import com.msz.acc.domain.model.RealnameRecord;
import org.apache.ibatis.session.SqlSession;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.time.Instant;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * RealnameRecordMapperTest：uk_open_id 冲突被拒、updateCallback 回填 account_id/callback_at。
 */
class RealnameRecordMapperTest extends AbstractDbTest {

    @Test
    @DisplayName("uk_open_id 唯一冲突被拒（重复回传拒绝）")
    void duplicateOpenIdIsRejected() {
        try (SqlSession s = openSession()) {
            RealnameRecordMapper mapper = s.getMapper(RealnameRecordMapper.class);
            mapper.insert(record("rz_1", "openid-dup", null));
            assertDuplicateKey(() -> mapper.insert(record("rz_2", "openid-dup", null)));
        }
    }

    @Test
    @DisplayName("updateCallback 回填 account_id/callback_at")
    void updateCallbackFillsAccountAndCallbackAt() {
        try (SqlSession s = openSession()) {
            s.getMapper(RealnameRecordMapper.class).insert(record("rz_10", "openid-10", null));
        }

        Instant callbackAt = Instant.parse("2026-01-02T03:04:05Z");
        try (SqlSession s = openSession()) {
            assertThat(s.getMapper(RealnameRecordMapper.class)
                    .updateCallback("rz_10", "REALNAMED", 888L, callbackAt)).isEqualTo(1);
        }

        try (SqlSession s = openSession()) {
            RealnameRecord loaded = s.getMapper(RealnameRecordMapper.class).selectByBizId("rz_10");
            assertThat(loaded).isNotNull();
            assertThat(loaded.getAccountId()).isEqualTo(888L);
            assertThat(loaded.getCallbackAt()).isEqualTo(callbackAt);
            assertThat(loaded.getStatus()).isEqualTo("REALNAMED");
        }
    }

    @Test
    @DisplayName("selectByOpenId 命中实名业务单（幂等键）")
    void selectByOpenIdFindsRecord() {
        try (SqlSession s = openSession()) {
            s.getMapper(RealnameRecordMapper.class).insert(record("rz_20", "openid-20", null));
        }
        try (SqlSession s = openSession()) {
            RealnameRecord loaded = s.getMapper(RealnameRecordMapper.class).selectByOpenId("openid-20");
            assertThat(loaded).isNotNull();
            assertThat(loaded.getBizId()).isEqualTo("rz_20");
            assertThat(loaded.getName()).isEqualTo("李四");
            assertThat(loaded.getIdNo()).isEqualTo("110101198505052345");
        }
    }

    private static RealnameRecord record(String bizId, String openId, Long accountId) {
        RealnameRecord record = new RealnameRecord();
        record.setBizId(bizId);
        record.setAccountId(accountId);
        record.setChannel("WECHAT");
        record.setOpenId(openId);
        record.setName("李四");
        record.setIdNo("110101198505052345");
        record.setStatus("REALNAMING");
        record.setLevel("BASE");
        record.setCreatedAt(Instant.parse("2026-01-01T00:00:00Z"));
        return record;
    }
}
