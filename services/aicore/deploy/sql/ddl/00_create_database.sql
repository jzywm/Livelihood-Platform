-- AICORE 建库脚本（Task 3.1）
--
-- 用途：创建服务自有库 `aicore`（生产/开发）与 `aicore_test`（测试）。
--   `er.md` §5.1 定档「服务自有库原则」：AICORE 独立库，与主站库逻辑/物理隔离；
--   `aicore_test` 供集成测试与 DDL 演练使用，二者结构一致、数据不互通。
--
-- 为什么必须带 IF NOT EXISTS：本脚本与 `deploy/sql/ddl/*.sql` 同属**幂等建表链路**，
--   部署与建分表流程都会重复执行，重复执行 MUST 零错误（不是"忽略报错继续"）。
--
-- 为什么不用 `USE`：库由执行方通过连接参数指定（`mysql -D <db>`），脚本自身不切库，
--   免得运维本地执行一次就把会话切到 `aicore`、后续语句打错库。
--
-- 字符集：utf8mb4；排序规则 utf8mb4_0900_ai_ci（MySQL 8 默认，与表级 COLLATE 一致）。
--   注意：库级排序规则只决定**将来新建表**的默认值，不影响已存在表的排序规则。

CREATE DATABASE IF NOT EXISTS `aicore`
    DEFAULT CHARACTER SET utf8mb4
    DEFAULT COLLATE utf8mb4_0900_ai_ci;

CREATE DATABASE IF NOT EXISTS `aicore_test`
    DEFAULT CHARACTER SET utf8mb4
    DEFAULT COLLATE utf8mb4_0900_ai_ci;
