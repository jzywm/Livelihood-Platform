-- AICORE DDL：vision_qa_log（图像问答留痕，不分片）
-- 源：docs/er.md §6.9（数据字典）与 §7.9（表设计说明书）
--
-- 索引（er.md §7.9）：PRIMARY KEY(qa_id)、KEY idx_account_created(account_id, created_at)。
--   无外键：account_id 可空（未登录/服务端间调用），且账号权威在 PROFILE/CRED 域。
-- 审计（er.md §5.5）：问答留痕随平台审计体系，保留 >=6 个月；本表**不落原始图像**，
--   仅存 OSS 对象键，图像服务端脱敏后才送视觉模型。
-- 库不在此文件内指定：由执行方以 `mysql -D <db>` 指定。

CREATE TABLE IF NOT EXISTS `vision_qa_log` (
    `qa_id`      varchar(32)  NOT NULL             COMMENT '问答留痕号 qa_ 前缀 + UUID',
    `account_id` varchar(32)  NULL DEFAULT NULL    COMMENT '提问账号',
    `image_key`  varchar(255) NOT NULL             COMMENT '图像 OSS 对象键（服务端脱敏后送视觉模型）',
    `question`   varchar(200) NOT NULL             COMMENT '提问内容，最多 200 字',
    `answer`     varchar(500) NOT NULL             COMMENT '视觉模型辅助回答',
    `confidence` decimal(3,2) NULL DEFAULT NULL    COMMENT '回答置信度 0~1（可选）',
    `disclaimer` varchar(255) NOT NULL             COMMENT '合规声明（前端必须展示）：仅辅助判断、不作执法/鉴定结论',
    `created_at` datetime(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '提问时间',
    PRIMARY KEY (`qa_id`),
    KEY `idx_account_created` (`account_id`, `created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='图像问答留痕（K-04），不分片';
