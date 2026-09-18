-- AICORE DDL 模板：ai_task（统一异步 AI 任务，按月分表）
-- 源：docs/er.md §6.1（数据字典）与 §7.1（表设计说明书）
--
-- ============================ 这个文件不能直接执行 ============================
-- 文件名带 `.template.sql` 而不是 `.sql`，就是因为正文含 `{table}` / `{month}` 占位符，
-- 直接喂给 mysql 会语法错。执行前必须由建表流程渲染（Task 3.3 的幂等建表）：
--   {table} -> 本表的物理表名（`ai_task_202601` 形态的**裸名**，不含反引号）
--   {month} -> 6 位 `YYYYMM`
--
-- 为什么需要两个占位符（设计文档 §5.1「表名占位统一为 {table}」的落地口径）：
--   §5.1 说的 `{table}` 指**本表名**；但 `ocr_correction.task_id` 的物理外键必须指向
--   **同月**的 `ocr_result_YYYYMM`——那是"另一张同分片的兄弟表"，只允许 `{table}` 就
--   表达不出来。故 `{month}` 是 `{table}` 的补充而非替代，二者**同时存在**：
--   本表名一律用 {table}，同月兄弟表一律用 `xxx_{month}`。
--
-- 分片（er.md §5.2）：分片键 account_id + created_at，物理表 ai_task_YYYYMM；
--   热表保留 12 个月，超期热转冷 OSS（Parquet/压缩）。
-- 约束（er.md §7.1）：task_id 为业务号（`task_` 前缀 + UUID），Python 侧不参与雪花域。
-- 库不在此文件内指定：由执行方以 `mysql -D <db>` 指定。

CREATE TABLE IF NOT EXISTS `{table}` (
    `task_id`        varchar(32)  NOT NULL                  COMMENT '任务号 task_ 前缀 + UUID，轮询 GET /aicore/tasks/{taskId}',
    `account_id`     varchar(32)  NOT NULL                  COMMENT '提交账号，分表键（与 created_at 组合）',
    `idem_key`       varchar(64)  NULL     DEFAULT NULL     COMMENT '幂等键；uk_idem(account_id, idem_key) NULL 豁免（同月表内唯一）',
    `type`           enum('OCR','VISION_REVIEW','KITCHEN_ANOMALY','RISK_PREDICT') NOT NULL COMMENT '任务类型（K-02 统一队列）',
    `status`         enum('PROCESSING','SUCCEEDED','FAILED','MANUAL_REVIEW') NOT NULL DEFAULT 'PROCESSING' COMMENT '任务状态机',
    `progress`       int unsigned NOT NULL DEFAULT 0        COMMENT '进度百分比 0~100',
    `error_code`     varchar(16)  NULL     DEFAULT NULL     COMMENT 'FAILED 业务码：4003 通道失败已转人工 / 5002 依赖超时',
    `model_meta`     json         NULL     DEFAULT NULL     COMMENT '模型/Prompt 血缘：{channel, provider, modelVersion, promptVersion, thresholds（high/medium）}',
    `is_eval_sample` tinyint(1)   NOT NULL DEFAULT 0        COMMENT '固定评估集样本标记：模型/Prompt/阈值改动前后的准确率回归基线',
    `created_at`     datetime(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '提交时间，分表键',
    `finished_at`    datetime(3)  NULL     DEFAULT NULL     COMMENT '完成时间（终态时）',
    PRIMARY KEY (`task_id`),
    KEY `idx_account_created` (`account_id`, `created_at`),
    UNIQUE KEY `uk_idem` (`account_id`, `idem_key`),
    KEY `idx_status_created` (`status`, `created_at`),
    KEY `idx_eval` (`is_eval_sample`, `type`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='统一异步 AI 任务（K-02），按月分表 ai_task_YYYYMM';
