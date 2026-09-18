-- AICORE DDL：vision_review（视觉合规审核记录，不分片）
-- 源：docs/er.md §6.4（数据字典）与 §7.4（表设计说明书）
--
-- 分片（er.md §5.2）：**暂不分片**（阈值触发再分，TBD-11），物理表名即 vision_review；
--   分片键 merchant_id + created_at 为**预留**，故 idx_merchant_created 现在就建。
-- 索引（er.md §7.4）：PRIMARY KEY(review_id)、KEY idx_merchant_created(merchant_id, created_at)、
--   KEY idx_status_created(status, created_at)、KEY idx_task(task_id)。无外键。
-- 约定：本表与 vision_marker / review_verdict / kitchen_anomaly 同库，后三者的物理外键
--   指回本表 review_id；状态机 AI_PROCESSING -> PENDING -> CONFIRMED/REFERRED/REJECTED/ARCHIVED，
--   C8 要求人工确认后处置、AI 不自动处罚。
-- 库不在此文件内指定：由执行方以 `mysql -D <db>` 指定。

CREATE TABLE IF NOT EXISTS `vision_review` (
    `review_id`        varchar(32) NOT NULL                    COMMENT '审核记录号 rev_ 前缀 + UUID，工作台查询/复核凭据',
    `task_id`          varchar(32) NULL     DEFAULT NULL       COMMENT '关联任务号（逻辑关联）',
    `biz_type`         enum('RAW_MATERIAL','CERTIFICATE','INSPECTION_SAMPLE','KITCHEN') NOT NULL COMMENT '业务类型（KITCHEN 复用 K-05 标记）',
    `merchant_id`      varchar(32) NULL     DEFAULT NULL       COMMENT '关联商户；结论回写 A-02 档案与信用分',
    `merchant_name`    varchar(64) NULL     DEFAULT NULL       COMMENT '商户名称（脱敏展示，如 张*饭馆）',
    `batch_id`         varchar(32) NULL     DEFAULT NULL       COMMENT '关联溯源批次（抽检图像）',
    `image_keys_json`  json        NOT NULL                    COMMENT '图像 OSS 对象键（1~9 张），预览走签名 URL',
    `status`           enum('AI_PROCESSING','PENDING','CONFIRMED','REFERRED','REJECTED','ARCHIVED') NOT NULL DEFAULT 'AI_PROCESSING' COMMENT '审核状态机',
    `confidence_level` enum('HIGH','MEDIUM','LOW') NULL DEFAULT NULL COMMENT '置信度分级（0.9/0.7 分界初值）',
    `confidence`       decimal(3,2) NULL    DEFAULT NULL       COMMENT '最高标记置信度 0~1',
    `markers_count`    int unsigned NOT NULL DEFAULT 0         COMMENT '疑似标记数量',
    `created_at`       datetime(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '提交时间',
    `reviewed_at`      datetime(3) NULL     DEFAULT NULL       COMMENT '复核时间（已复核时有值）',
    PRIMARY KEY (`review_id`),
    KEY `idx_merchant_created` (`merchant_id`, `created_at`),
    KEY `idx_status_created` (`status`, `created_at`),
    KEY `idx_task` (`task_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='视觉合规审核记录（K-03），暂不分片';
