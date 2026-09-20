-- AICORE DDL 模板：ocr_result（证照 OCR 结果，随任务同月分表）
-- 源：docs/er.md §6.2（数据字典）与 §7.2（表设计说明书）
--
-- ============================ 这个文件不能直接执行 ============================
-- 文件名带 `.template.sql`，正文含 `{table}` / `{month}` 占位符，需由建表流程渲染：
--   {table} -> 本表的物理表名（`ocr_result_202601` 形态的**裸名**，不含反引号）
--   {month} -> 6 位 `YYYYMM`
-- 两个占位符的分工见 10_ai_task.template.sql 顶部说明：本表名用 {table}，
-- 同月兄弟表用 `xxx_{month}`；二者同时存在，缺一不可（Task 3.3 复用同一约定）。
--
-- 分片（er.md §5.2）：**随 ai_task 同月分表**（同一 task_id 落同分片，1:1 查询不跨分片）；
--   物理表 ocr_result_YYYYMM，建表顺序 ai_task -> ocr_result -> ocr_correction。
--
-- 为什么 task_id 不建物理外键（MUST NOT，非疏漏）：
--   1) 设计文档 L290 明确要求「ocr_result.task_id -> ai_task.task_id 不建物理外键」——
--      跨月分片表之间建不了外键（不同月的物理表互不相识），一张模板也表达不出
--      "引用同月的另一张模板表"；
--   2) 分期建表时被引用表可能尚未创建，物理外键会让建表顺序变成硬依赖；
--   3) 本模板内的 `{month}` 占位符只解决"同月兄弟表"这一种情形（见
--      12_ocr_correction.template.sql 对 ocr_result 的物理外键），不用于 ai_task。
--   与本表的关联因此是**逻辑关联**，一致性由「同月同分片路由 + 幂等写入补偿」保证：
--   任务与结果同月落同分片，写入端按 task_id 幂等 upsert；跨分片不 JOIN、不聚合、
--   不跨分片事务（er.md §5.3）。每日对账（TBD-11）兜住漏写/漂移。
--
-- 索引（er.md §7.2）：仅 PRIMARY KEY(task_id)，无需附加索引（只按任务号访问）。
-- 库不在此文件内指定：由执行方以 `mysql -D <db>` 指定。

CREATE TABLE IF NOT EXISTS `{table}` (
    `task_id`             varchar(32)  NOT NULL             COMMENT '= ai_task.task_id，1:1 同月分片',
    `fields_json`         json         NOT NULL             COMMENT '结构化提取字段；OcrField = {fieldName, value（脱敏）, confidence（0~1）}',
    `validity`            enum('VALID','EXPIRING','EXPIRED','UNKNOWN') NOT NULL COMMENT '有效期比对结果',
    `category_match`      tinyint(1)   NOT NULL DEFAULT 0   COMMENT '经营范围/类目比对是否匹配',
    `summary`             varchar(255) NOT NULL             COMMENT '一句话核验结论（面向人工核验）',
    `suggestions_json`    json         NULL     DEFAULT NULL COMMENT '人工核验提示（如「有效期不足 90 天」）',
    `needs_manual_review` tinyint(1)   NOT NULL DEFAULT 0   COMMENT '识别置信度不足 -> 转人工核验兜底（C8）',
    PRIMARY KEY (`task_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='证照 OCR 结果（K-01），随任务同月分表 ocr_result_YYYYMM';
