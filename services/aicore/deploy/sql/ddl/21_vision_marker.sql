-- AICORE DDL：vision_marker（疑似问题标记，不分片）
-- 源：docs/er.md §6.5（数据字典）与 §7.5（表设计说明书）
--
-- 索引（er.md §7.5）：PRIMARY KEY(marker_id)、KEY idx_review(review_id)。
-- 物理外键：fk_vision_marker_review，review_id -> vision_review(review_id)；
--   显式 ON DELETE/UPDATE RESTRICT —— 标记与结论同生命周期，标记不可被级联删除，
--   审核记录也不可被带着标记一起删（删除须显式先处理子表）。
-- 约束（er.md §7.5）：AI 只标记不决策；suggestion 仅建议。
-- 库不在此文件内指定：由执行方以 `mysql -D <db>` 指定。

CREATE TABLE IF NOT EXISTS `vision_marker` (
    `marker_id`  varchar(32)  NOT NULL             COMMENT '标记号 marker_ 前缀 + UUID',
    `review_id`  varchar(32)  NOT NULL             COMMENT '所属审核记录（物理外键 -> vision_review.review_id）',
    `label`      varchar(64)  NOT NULL             COMMENT '疑似标签：疑似过期/疑似变质/包装不规范/资质不符/未穿工装/卫生问题/明火离人',
    `level`      enum('HIGH','MEDIUM','LOW') NOT NULL COMMENT '标记置信度分级',
    `confidence` decimal(3,2) NOT NULL             COMMENT '标记置信度 0~1',
    `bbox_json`  json         NULL DEFAULT NULL    COMMENT '图像内位置框 {x,y,width,height}，归一化坐标 0~1，前端框选展示',
    `suggestion` varchar(255) NULL DEFAULT NULL    COMMENT '处置建议（仅建议，人工决策执行）',
    PRIMARY KEY (`marker_id`),
    KEY `idx_review` (`review_id`),
    CONSTRAINT `fk_vision_marker_review` FOREIGN KEY (`review_id`)
        REFERENCES `vision_review` (`review_id`)
        ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='疑似问题标记（K-03），不分片';
