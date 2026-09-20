-- AICORE DDL 模板：ocr_correction（人工核验纠错回流，随任务同月分表）
-- 源：docs/er.md §6.3（数据字典）与 §7.3（表设计说明书）
--
-- ============================ 这个文件不能直接执行 ============================
-- 文件名带 `.template.sql`，正文含 `{table}` / `{month}` 占位符，需由建表流程渲染：
--   {table} -> 本表的物理表名（`ocr_correction_202601` 形态的**裸名**，不含反引号）
--   {month} -> 6 位 `YYYYMM`
-- 两个占位符同时存在、分工固定：本表名一律用 {table}，**同月兄弟表**一律用
-- `xxx_{month}`（设计文档 §5.1「表名占位统一为 {table}」指本表名，{month} 是其补充：
-- 只有 {table} 时无法表达"引用同月的另一张表"，而下面的物理外键正需要它）。
--
-- **本模板的要点：同分片物理外键**
--   CONSTRAINT `fk_ocr_correction_task_{month}` FOREIGN KEY (`task_id`)
--       REFERENCES `ocr_result_{month}` (`task_id`)
--   —— 被引用的 `ocr_result_YYYYMM` 必须在**同月**已建，故建表顺序固定为
--   ai_task -> ocr_result -> ocr_correction（er.md §5.2、§7.3）。
--   跨月引用在语法上就不成立：`{month}` 渲染后是本表所属月的兄弟表，别的月找不到。
--
-- **约束名 MUST 带 `{month}`（2026-09-16 修正，MySQL 实证）**：
--   MySQL 的外键约束名在 **schema 内唯一**，不是表内唯一。若把约束名写死成
--   `fk_ocr_correction_task`，模板套用到第二个月（`ocr_correction_202602`）时必然撞名：
--       ERROR 1826 (HY000): Duplicate foreign key constraint name 'fk_ocr_correction_task'
--   故约束名与表名同口径地带月份后缀；三个模板里的**所有** `CONSTRAINT` 名都必须含
--   `{month}`（用例 test_ddl_constraint_names_all_carry_month 守着这条）。
--
-- 为什么 ON DELETE / ON UPDATE 都显式写 RESTRICT：
--   纠错语料是**评估集语料**（§7.11 准确率闭环的数据基础），不可被级联删除或级联改写；
--   MySQL 默认即 RESTRICT，显式写出是为了不让读者以为漏写了级联规则。
--
-- 分片（er.md §5.2）：随 ocr_result **同月分表**（同一 task_id 落同分片，1:N 不跨分片）；
-- 索引（er.md §7.3）：PRIMARY KEY(correction_id)、KEY idx_task(task_id)、
--   KEY idx_field_corrected(field_name, corrected_at)。
-- 库不在此文件内指定：由执行方以 `mysql -D <db>` 指定。

CREATE TABLE IF NOT EXISTS `{table}` (
    `correction_id` varchar(32)  NOT NULL                  COMMENT '纠错号 cor_ 前缀 + UUID',
    `task_id`       varchar(32)  NOT NULL                  COMMENT '关联 OCR 任务（物理外键 -> ocr_result 同月同分片，路由键）',
    `field_name`    varchar(64)  NOT NULL                  COMMENT '被纠正字段名（如 licenseNo / validUntil / scope）',
    `ai_value`      varchar(255) NULL     DEFAULT NULL     COMMENT 'AI 原值（脱敏，如 911301********1234）',
    `human_value`   varchar(255) NOT NULL                  COMMENT '人工修正值（脱敏，作为该字段的 ground truth）',
    `confidence`    decimal(3,2) NULL     DEFAULT NULL     COMMENT 'AI 当时的置信度（用于分析「低置信是否真的错」与阈值调优）',
    `corrected_by`  varchar(64)  NOT NULL                  COMMENT '核验人（脱敏展示，如 王*员）',
    `corrected_at`  datetime(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '纠正时间（分表路由以 task_id 所在月为准）',
    PRIMARY KEY (`correction_id`),
    KEY `idx_task` (`task_id`),
    KEY `idx_field_corrected` (`field_name`, `corrected_at`),
    CONSTRAINT `fk_ocr_correction_task_{month}` FOREIGN KEY (`task_id`)
        REFERENCES `ocr_result_{month}` (`task_id`)
        ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='人工核验纠错回流（准确率提升闭环语料层），随任务同月分表 ocr_correction_YYYYMM';
