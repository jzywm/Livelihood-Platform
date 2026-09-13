package com.msz.acc.domain.model;

import java.time.Instant;
import java.time.LocalDate;

/**
 * reconcile_task 监管端资金对账任务实体（er.md §6.5）。
 */
public class ReconcileTask {

    private String reconcileId;
    private LocalDate fromDate;
    private LocalDate toDate;
    private String status;
    private long diffCount;
    private Instant createdAt;
    private Instant finishedAt;

    public String getReconcileId() {
        return reconcileId;
    }

    public void setReconcileId(String reconcileId) {
        this.reconcileId = reconcileId;
    }

    public LocalDate getFromDate() {
        return fromDate;
    }

    public void setFromDate(LocalDate fromDate) {
        this.fromDate = fromDate;
    }

    public LocalDate getToDate() {
        return toDate;
    }

    public void setToDate(LocalDate toDate) {
        this.toDate = toDate;
    }

    public String getStatus() {
        return status;
    }

    public void setStatus(String status) {
        this.status = status;
    }

    public long getDiffCount() {
        return diffCount;
    }

    public void setDiffCount(long diffCount) {
        this.diffCount = diffCount;
    }

    public Instant getCreatedAt() {
        return createdAt;
    }

    public void setCreatedAt(Instant createdAt) {
        this.createdAt = createdAt;
    }

    public Instant getFinishedAt() {
        return finishedAt;
    }

    public void setFinishedAt(Instant finishedAt) {
        this.finishedAt = finishedAt;
    }
}
