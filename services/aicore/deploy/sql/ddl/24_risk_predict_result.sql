-- AICORE DDL：risk_predict_result（风险商户预测结果，不分片，M3 占位）
-- 源：docs/er.md §6.8（数据字典）与 §7.8（表设计说明书）
--
-- 索引（er.md §7.8）：PRIMARY KEY(merchant_id)、KEY idx_predicted(predicted_at)。无外键：
--   merchant_id 是 CRED 域 ID 的**只读引用**（不重新发号），跨服务不建物理外键。
-- 主键语义：merchant_id 作主键 = 每商户**最新一次覆盖**，历史走审计留痕（§7.8）。
-- 时间列：`predicted_at` 无默认值（er.md §6.8「默认」列为「—」），预测时间由预测流程写入。
-- 库不在此文件内指定：由执行方以 `mysql -D <db>` 指定。

CREATE TABLE IF NOT EXISTS `risk_predict_result` (
    `merchant_id`      varchar(32) NOT NULL                 COMMENT '商户编号（引用 CRED 域 ID，只读引用；最新一次覆盖，历史走审计）',
    `merchant_name`    varchar(64) NULL DEFAULT NULL        COMMENT '商户名称（脱敏展示）',
    `risk_score`       decimal(5,2) NOT NULL                COMMENT '风险分 0~100，越高风险越大',
    `risk_level`       enum('LOW','MEDIUM','HIGH','CRITICAL') NOT NULL COMMENT '风险等级（阈值上线前评审）',
    `factors_json`     json        NOT NULL                 COMMENT '风险因子（欠薪：连续 2 期代付超时；假货：投诉激增）',
    `suggestions_json` json        NULL DEFAULT NULL        COMMENT '处置建议（AI 输出风险建议、人工决策执行）',
    `predicted_at`     datetime(3) NOT NULL                 COMMENT '预测时间，无默认值，由预测流程写入',
    PRIMARY KEY (`merchant_id`),
    KEY `idx_predicted` (`predicted_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='风险商户预测结果（K-06），不分片，M3 占位';
