package com.msz.acc.repository;

import com.msz.acc.domain.model.IdempotencyRecord;

import java.util.function.Supplier;

/**
 * 幂等记录组件（3.3）：以 acc_idempotency_record 的 uk_idempotency_key 为唯一事实源。
 *
 * <p>流程：{@code INSERT IGNORE} 抢占槽位——affected==1 视为首次，执行 action 后回填 payload；
 * affected==0 视为重复，轮询读取首次结果返回（3008 幂等口径）。并发同 key 仅首次执行 action。</p>
 */
public final class IdempotencyGuard {

    private static final long AWAIT_TIMEOUT_NANOS = 2_000_000_000L;
    private static final long POLL_INTERVAL_MILLIS = 5L;

    private final IdempotencyRecordMapper mapper;
    private final Supplier<String> payloadSupplier;

    public IdempotencyGuard(IdempotencyRecordMapper mapper, Supplier<String> payloadSupplier) {
        this.mapper = mapper;
        this.payloadSupplier = payloadSupplier;
    }

    /**
     * 执行幂等动作。首次（抢占槽位成功）执行 {@code action} 并回填；重复则返回首次 payload。
     *
     * @param scene  业务场景（存 biz_scene，不参与唯一判定）
     * @param key    幂等键（唯一约束 uk_idempotency_key）
     * @param action 首次执行的实际动作；为 null 时回退到构造注入的 payloadSupplier
     */
    public String execute(String scene, String key, Supplier<String> action) {
        Supplier<String> effective = action != null ? action : payloadSupplier;
        int affected = mapper.insertIgnore(scene, key, 0, "");
        if (affected == 1) {
            String payload = effective.get();
            mapper.updateResult(key, 0, payload);
            return payload;
        }
        return awaitFirstResult(key);
    }

    private String awaitFirstResult(String key) {
        long deadline = System.nanoTime() + AWAIT_TIMEOUT_NANOS;
        IdempotencyRecord record = mapper.selectByKey(key);
        while (record != null && isPending(record) && System.nanoTime() < deadline) {
            sleep(POLL_INTERVAL_MILLIS);
            record = mapper.selectByKey(key);
        }
        return record == null ? null : record.getResponsePayload();
    }

    private static boolean isPending(IdempotencyRecord record) {
        return record.getResponsePayload() == null || record.getResponsePayload().isEmpty();
    }

    private static void sleep(long millis) {
        try {
            Thread.sleep(millis);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }
}
