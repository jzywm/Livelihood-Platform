package com.msz.acc.repository;

import com.msz.acc.domain.model.ReconcileTask;
import org.apache.ibatis.session.SqlSession;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.time.Instant;
import java.time.LocalDate;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * ReconcileTaskMapperTest：insert/finish(DONE|DIFF)/listByStatusCreated 筛选。
 */
class ReconcileTaskMapperTest extends AbstractDbTest {

    @Test
    @DisplayName("insert + selectById")
    void insertAndSelectById() {
        try (SqlSession s = openSession()) {
            s.getMapper(ReconcileTaskMapper.class).insert(task("rec_1", "RUNNING"));
        }
        try (SqlSession s = openSession()) {
            ReconcileTask loaded = s.getMapper(ReconcileTaskMapper.class).selectById("rec_1");
            assertThat(loaded).isNotNull();
            assertThat(loaded.getStatus()).isEqualTo("RUNNING");
            assertThat(loaded.getFromDate()).isEqualTo(LocalDate.parse("2026-01-01"));
            assertThat(loaded.getToDate()).isEqualTo(LocalDate.parse("2026-01-31"));
            assertThat(loaded.getDiffCount()).isZero();
        }
    }

    @Test
    @DisplayName("finish 置 DONE / DIFF 并回填 diff_count/finished_at")
    void finishDoneAndDiff() {
        try (SqlSession s = openSession()) {
            ReconcileTaskMapper mapper = s.getMapper(ReconcileTaskMapper.class);
            mapper.insert(task("rec_10", "RUNNING"));
            mapper.insert(task("rec_11", "RUNNING"));
        }
        Instant finishedAt = Instant.parse("2026-01-31T23:59:59Z");
        try (SqlSession s = openSession()) {
            ReconcileTaskMapper mapper = s.getMapper(ReconcileTaskMapper.class);
            assertThat(mapper.finish("rec_10", "DONE", 0L, finishedAt)).isEqualTo(1);
            assertThat(mapper.finish("rec_11", "DIFF", 5L, finishedAt)).isEqualTo(1);
        }
        try (SqlSession s = openSession()) {
            ReconcileTaskMapper mapper = s.getMapper(ReconcileTaskMapper.class);
            ReconcileTask done = mapper.selectById("rec_10");
            assertThat(done.getStatus()).isEqualTo("DONE");
            assertThat(done.getDiffCount()).isZero();
            assertThat(done.getFinishedAt()).isEqualTo(finishedAt);

            ReconcileTask diff = mapper.selectById("rec_11");
            assertThat(diff.getStatus()).isEqualTo("DIFF");
            assertThat(diff.getDiffCount()).isEqualTo(5L);
        }
    }

    @Test
    @DisplayName("listByStatusCreated 按 status 筛选")
    void listByStatusCreatedFilters() {
        try (SqlSession s = openSession()) {
            ReconcileTaskMapper mapper = s.getMapper(ReconcileTaskMapper.class);
            mapper.insert(task("rec_20", "RUNNING"));
            mapper.insert(task("rec_21", "RUNNING"));
            mapper.insert(task("rec_22", "RUNNING"));
            mapper.finish("rec_22", "DONE", 0L, Instant.parse("2026-01-31T23:59:59Z"));
        }
        try (SqlSession s = openSession()) {
            assertThat(s.getMapper(ReconcileTaskMapper.class).listByStatusCreated("RUNNING", 0, 10))
                    .hasSize(2);
            assertThat(s.getMapper(ReconcileTaskMapper.class).listByStatusCreated("DONE", 0, 10))
                    .hasSize(1);
        }
    }

    @Test
    @DisplayName("selectAllByRange：任务日期区间与查询区间相交即命中")
    void selectAllByRangeCoverage() {
        try (SqlSession s = openSession()) {
            ReconcileTaskMapper mapper = s.getMapper(ReconcileTaskMapper.class);
            mapper.insert(task("rec_30", "RUNNING"));                              // 2026-01-01..2026-01-31
            ReconcileTask feb = task("rec_31", "RUNNING");
            feb.setFromDate(LocalDate.parse("2026-02-01"));
            feb.setToDate(LocalDate.parse("2026-02-28"));
            mapper.insert(feb);
        }
        try (SqlSession s = openSession()) {
            ReconcileTaskMapper mapper = s.getMapper(ReconcileTaskMapper.class);
            assertThat(mapper.selectAllByRange(
                    LocalDate.parse("2026-01-10"), LocalDate.parse("2026-01-20")))
                    .extracting(ReconcileTask::getReconcileId)
                    .containsExactly("rec_30");
            assertThat(mapper.selectAllByRange(
                    LocalDate.parse("2026-01-20"), LocalDate.parse("2026-02-10")))
                    .extracting(ReconcileTask::getReconcileId)
                    .containsExactlyInAnyOrder("rec_30", "rec_31");
            assertThat(mapper.selectAllByRange(
                    LocalDate.parse("2026-03-01"), LocalDate.parse("2026-03-31")))
                    .isEmpty();
        }
    }

    private static ReconcileTask task(String reconcileId, String status) {
        ReconcileTask task = new ReconcileTask();
        task.setReconcileId(reconcileId);
        task.setFromDate(LocalDate.parse("2026-01-01"));
        task.setToDate(LocalDate.parse("2026-01-31"));
        task.setStatus(status);
        task.setDiffCount(0L);
        task.setCreatedAt(Instant.parse("2026-01-01T00:00:00Z"));
        return task;
    }
}
