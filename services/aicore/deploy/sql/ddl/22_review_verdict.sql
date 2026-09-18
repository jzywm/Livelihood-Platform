-- AICORE DDL：review_verdict（人工复核结论留痕，不分片，1:1）
-- 源：docs/er.md §6.6（数据字典）与 §7.6（表设计说明书）
--
-- `comment` 是 MySQL 关键字，列名必须反引号（本文件已加，勿删）。
-- 索引（er.md §7.6）：PRIMARY KEY(review_id)、KEY idx_reviewed_at(reviewed_at)。
-- 物理外键：fk_review_verdict_review，review_id -> vision_review(review_id)，1:1；
--   显式 RESTRICT —— 本表是**审计留痕**，结论只增不改、不可被级联删除。
-- 时间列：`reviewed_at` **无默认值**（= er.md §6.6 的「默认」列为「—」）：
--   复核时间由业务写入时刻决定，数据库兜默认值会把"忘记写时间"变成静默假数据。
-- 权威回写（er.md §7.6）：authority_written 只能由人工复核结论驱动置位（C8）；
--   authority_event_id 为 MQ `aicore.conclusion` 事件号，兼作消费幂等键与每日对账依据。
-- 库不在此文件内指定：由执行方以 `mysql -D <db>` 指定。

CREATE TABLE IF NOT EXISTS `review_verdict` (
    `review_id`            varchar(32)  NOT NULL            COMMENT '复核对象（物理外键 -> vision_review.review_id，1:1）',
    `action`               enum('CONFIRM','REFER','REJECT','ARCHIVE') NOT NULL COMMENT '人工结论动作（C8：AI 不决策，人工确认后处置）',
    `comment`              varchar(200) NULL DEFAULT NULL   COMMENT '复核意见，最多 200 字（CONFIRM/REFER 建议必填），留痕',
    `reviewed_by`          varchar(64)  NOT NULL            COMMENT '复核人（脱敏展示，如 王*员）',
    `reviewed_at`          datetime(3)  NOT NULL            COMMENT '复核时间（全链路审计），无默认值，由业务写入',
    `authority_written`    tinyint(1)   NOT NULL DEFAULT 0  COMMENT '权威数据回写标记：是否已回写 CRED（A-02）/ DASH（A-08）；只能由人工复核结论驱动置位',
    `authority_event_id`   varchar(32)  NULL DEFAULT NULL   COMMENT '回写事件号：MQ aicore.conclusion 事件号，消费方幂等键 + 每日对账依据',
    `authority_written_at` datetime(3)  NULL DEFAULT NULL   COMMENT '回写时间',
    PRIMARY KEY (`review_id`),
    KEY `idx_reviewed_at` (`reviewed_at`),
    CONSTRAINT `fk_review_verdict_review` FOREIGN KEY (`review_id`)
        REFERENCES `vision_review` (`review_id`)
        ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='人工复核结论留痕（C8），不分片，与 vision_review 1:1';
