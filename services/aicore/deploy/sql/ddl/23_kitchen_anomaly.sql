-- AICORE DDL：kitchen_anomaly（后厨直播异常标记，不分片）
-- 源：docs/er.md §6.7（数据字典）与 §7.7（表设计说明书）
--
-- 索引（er.md §7.7）：PRIMARY KEY(anomaly_id)、KEY idx_stream_detected(stream_id, detected_at)、
--   KEY idx_status(status, detected_at)、KEY idx_review(review_id)。
-- 物理外键：fk_kitchen_anomaly_review，review_id -> vision_review(review_id)，显式 RESTRICT。
--   本表的 review_id **可空**：NULL 不受外键约束（未进复核流的标记留 NULL 即可），
--   非 NULL 时必须是真实存在的审核记录 —— 这正是要保留外键的原因。
-- 时间列：`detected_at` 无默认值（er.md §6.7「默认」列为「—」），识别时间由识别流程写入。
-- 库不在此文件内指定：由执行方以 `mysql -D <db>` 指定。

CREATE TABLE IF NOT EXISTS `kitchen_anomaly` (
    `anomaly_id`       varchar(32) NOT NULL                 COMMENT '异常标记号 kan_ 前缀 + UUID',
    `review_id`        varchar(32) NULL DEFAULT NULL        COMMENT '复核记录号（物理外键 -> vision_review.review_id，复用复核接口）',
    `merchant_id`      varchar(32) NULL DEFAULT NULL        COMMENT '关联商户',
    `merchant_name`    varchar(64) NULL DEFAULT NULL        COMMENT '商户名称（脱敏展示）',
    `stream_id`        varchar(64) NOT NULL                 COMMENT '直播流标识 `live_` 前缀（B-04 后厨直播）',
    `anomaly_type`     varchar(64) NOT NULL                 COMMENT '异常类型：未穿工装/卫生问题/明火离人等',
    `confidence`       decimal(3,2) NOT NULL                COMMENT '识别置信度 0~1',
    `confidence_level` enum('HIGH','MEDIUM','LOW') NULL DEFAULT NULL COMMENT '置信度分级',
    `status`           enum('PENDING','CONFIRMED','REJECTED','ARCHIVED') NOT NULL DEFAULT 'PENDING' COMMENT '复核状态机',
    `detected_at`      datetime(3) NOT NULL                 COMMENT '识别时间，无默认值，由识别流程写入',
    `reviewed_at`      datetime(3) NULL DEFAULT NULL        COMMENT '复核时间',
    PRIMARY KEY (`anomaly_id`),
    KEY `idx_stream_detected` (`stream_id`, `detected_at`),
    KEY `idx_status` (`status`, `detected_at`),
    KEY `idx_review` (`review_id`),
    CONSTRAINT `fk_kitchen_anomaly_review` FOREIGN KEY (`review_id`)
        REFERENCES `vision_review` (`review_id`)
        ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='后厨直播异常标记（K-05），不分片';
