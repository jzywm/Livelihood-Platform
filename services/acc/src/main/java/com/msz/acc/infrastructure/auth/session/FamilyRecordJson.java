package com.msz.acc.infrastructure.auth.session;

import com.msz.acc.infrastructure.auth.Json;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 会话族记录的扁平 JSON 编解码（复用 auth 包手写 {@code Json}，不引 JSON 库）。
 *
 * <p>「已轮换 jti 标记」用 {@code rotated.<jti>} 前缀键表达——手写 JSON 只支持扁平对象，
 * 不用数组/嵌套对象；键前缀法同时也让标记集合在字符串层可见（便于运维排查）。</p>
 */
final class FamilyRecordJson {

    private static final String ROTATED_PREFIX = "rotated.";
    private static final String ACCESS_PREFIX = "access.";

    private FamilyRecordJson() {
    }

    static String encode(FamilyRecord record) {
        Map<String, Object> map = new LinkedHashMap<>();
        map.put("familyId", record.familyId());
        map.put("accountId", record.accountId());
        map.put("role", record.role());
        map.put("mfa", record.mfa());
        map.put("createdAtMillis", record.createdAtMillis());
        map.put("expiresAtMillis", record.expiresAtMillis());
        map.put("status", record.status());
        map.put("currentJti", record.currentJti());
        map.put("previousJti", record.previousJti());
        map.put("previousValidUntilMillis", record.previousValidUntilMillis());
        for (Map.Entry<String, Long> entry : record.rotatedJtis().entrySet()) {
            map.put(ROTATED_PREFIX + entry.getKey(), entry.getValue());
        }
        for (Map.Entry<String, Long> entry : record.accessJtis().entrySet()) {
            map.put(ACCESS_PREFIX + entry.getKey(), entry.getValue());
        }
        return Json.toJson(map);
    }

    static FamilyRecord decode(String json) {
        Map<String, Object> map = Json.parseObject(json);
        Map<String, Long> rotated = new LinkedHashMap<>();
        Map<String, Long> access = new LinkedHashMap<>();
        for (Map.Entry<String, Object> entry : map.entrySet()) {
            if (entry.getKey().startsWith(ROTATED_PREFIX)) {
                rotated.put(entry.getKey().substring(ROTATED_PREFIX.length()), asLong(entry.getValue()));
            } else if (entry.getKey().startsWith(ACCESS_PREFIX)) {
                access.put(entry.getKey().substring(ACCESS_PREFIX.length()), asLong(entry.getValue()));
            }
        }
        return new FamilyRecord(string(map, "familyId"), asLong(map.get("accountId")), string(map, "role"),
                Boolean.TRUE.equals(map.get("mfa")), asLong(map.get("createdAtMillis")),
                asLong(map.get("expiresAtMillis")), string(map, "status"), string(map, "currentJti"),
                string(map, "previousJti"), asLong(map.get("previousValidUntilMillis")), rotated, access);
    }

    private static String string(Map<String, Object> map, String key) {
        Object value = map.get(key);
        return value instanceof String s ? s : null;
    }

    private static long asLong(Object value) {
        return value instanceof Number n ? n.longValue() : 0L;
    }
}
