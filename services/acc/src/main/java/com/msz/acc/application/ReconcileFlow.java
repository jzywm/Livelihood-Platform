package com.msz.acc.application;

import com.msz.acc.application.port.ReconcileExecutor;
import com.msz.acc.domain.model.ReconcileStatus;
import com.msz.acc.domain.model.ReconcileTask;
import com.msz.acc.domain.service.ReconcileDecision;
import com.msz.acc.domain.support.AccBusinessException;
import com.msz.acc.repository.IdempotencyGuard;
import com.msz.acc.repository.IdempotencyRecordMapper;
import com.msz.acc.repository.ReconcileTaskMapper;
import com.msz.common.idgen.IdGenerator;

import java.time.Clock;
import java.time.LocalDate;
import java.time.format.DateTimeParseException;

/**
 * 对账触发流程（4.6）：Idempotency-Key、建任务 RUNNING、执行核对、finish DONE/DIFF + 3009。
 */
public final class ReconcileFlow {

    private static final String SCENE = "reconcile";

    private final ReconcileTaskMapper taskMapper;
    private final IdempotencyGuard idempotencyGuard;
    private final IdGenerator idGenerator;
    private final ReconcileExecutor executor;
    private final ReconcileDecision decision;
    private final Clock clock;

    public ReconcileFlow(ReconcileTaskMapper taskMapper, IdempotencyRecordMapper idempotencyRecordMapper,
                         IdGenerator idGenerator, ReconcileExecutor executor, ReconcileDecision decision,
                         Clock clock) {
        this.taskMapper = taskMapper;
        this.idempotencyGuard = new IdempotencyGuard(idempotencyRecordMapper, () -> "");
        this.idGenerator = idGenerator;
        this.executor = executor;
        this.decision = decision;
        this.clock = clock;
    }

    public ReconcileResult trigger(String from, String to, String idempotencyKey) {
        LocalDate fromDate = parseDate(from);
        LocalDate toDate = parseDate(to);
        if (fromDate.isAfter(toDate)) {
            throw new AccBusinessException(1003, "对账起止日期非法");
        }
        String payload = idempotencyGuard.execute(SCENE, idempotencyKey, () -> {
            ReconcileTask task = new ReconcileTask();
            task.setReconcileId("rec_" + idGenerator.nextId());
            task.setFromDate(fromDate);
            task.setToDate(toDate);
            task.setStatus(ReconcileStatus.RUNNING.name());
            task.setDiffCount(0L);
            task.setCreatedAt(clock.instant());
            taskMapper.insert(task);

            long diff = executor.compare(fromDate, toDate);
            ReconcileStatus status = decision.finish(ReconcileStatus.RUNNING, diff);
            taskMapper.finish(task.getReconcileId(), status.name(), diff, clock.instant());

            ReconcileResult result = new ReconcileResult(
                    task.getReconcileId(), status.name(), diff, decision.alertCode(status));
            return serialize(result);
        });
        return deserialize(payload);
    }

    private static LocalDate parseDate(String value) {
        if (value == null) {
            throw new AccBusinessException(1002, "对账日期缺失");
        }
        try {
            return LocalDate.parse(value);
        } catch (DateTimeParseException e) {
            throw new AccBusinessException(1002, "对账日期格式非法");
        }
    }

    private static String serialize(ReconcileResult result) {
        return result.reconcileId() + "|" + result.status() + "|" + result.diffCount() + "|" + result.alertCode();
    }

    private static ReconcileResult deserialize(String payload) {
        String[] parts = payload.split("\\|", -1);
        return new ReconcileResult(parts[0], parts[1], Long.parseLong(parts[2]), Integer.parseInt(parts[3]));
    }
}
