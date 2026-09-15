package com.msz.acc.infrastructure.auth.session;

import com.msz.acc.infrastructure.auth.Json;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * {@link FamilyRecord} 扁平 JSON 编解码（复用 auth 包手写 {@code Json}，不引 JSON 库）
 * 与「已轮换标记」剪枝（标记保留到原 refresh 到期，因此必须有界）。
 */
class FamilyRecordJsonTest {

    private static final long T0 = 1_760_000_000_000L;

    @Test
    @DisplayName("扁平 JSON 往返：accountId/role/mfa/status/currentJti/previousJti/已轮换标记全部还原")
    void roundTrip() {
        FamilyRecord record = new FamilyRecord("fam_1", 1001L, "CONSUMER", true, T0, T0 + 604_800_000L,
                FamilyRecord.STATUS_ACTIVE, "rf-2", "rf-1", T0 + 5_000L,
                Map.of("rf-0", T0 + 604_800_000L));

        FamilyRecord back = FamilyRecordJson.decode(FamilyRecordJson.encode(record));

        assertThat(back).isEqualTo(record);
    }

    @Test
    @DisplayName("编码为扁平对象（无嵌套数组/对象），值为原始类型 + rotated.<jti> 前缀键")
    void encodedShapeIsFlat() {
        FamilyRecord record = new FamilyRecord("fam_1", 1001L, "MERCHANT", false, T0, T0 + 1000L,
                FamilyRecord.STATUS_REVOKED, "rf-1", null, 0L, Map.of("rf-0", T0 + 1000L));

        String json = FamilyRecordJson.encode(record);

        Map<String, Object> parsed = Json.parseObject(json);
        assertThat(parsed).containsKeys("familyId", "accountId", "role", "mfa", "createdAtMillis",
                "expiresAtMillis", "status", "currentJti", "rotated.rf-0");
        assertThat(parsed.get("status")).isEqualTo("REVOKED");
        assertThat(parsed.get("previousJti")).isNull();
    }

    @Test
    @DisplayName("剪枝：过期「已轮换」标记与超过宽限的上一个 jti 被移除，未过期标记保留")
    void prunedDropsExpiredMarkers() {
        FamilyRecord record = new FamilyRecord("fam_1", 1001L, "CONSUMER", false, T0, T0 + 1000L,
                FamilyRecord.STATUS_ACTIVE, "rf-2", "rf-1", T0 + 5_000L,
                Map.of("rf-old", T0 - 1L, "rf-keep", T0 + 604_800_000L));

        FamilyRecord pruned = record.pruned(T0);

        assertThat(pruned.rotatedJtis()).containsOnlyKeys("rf-keep");
        assertThat(pruned.currentJti()).isEqualTo("rf-2");
        // 宽限窗口未过 → 上一个 jti 保留（并发重试判定依赖它）
        assertThat(pruned.previousJti()).isEqualTo("rf-1");
        assertThat(pruned.previousValidUntilMillis()).isEqualTo(T0 + 5_000L);

        // 窗口过后再剪枝 → 上一个 jti 一并移除
        FamilyRecord afterGrace = record.pruned(T0 + 5_001L);
        assertThat(afterGrace.previousJti()).isNull();
        assertThat(afterGrace.previousValidUntilMillis()).isZero();
    }
}
