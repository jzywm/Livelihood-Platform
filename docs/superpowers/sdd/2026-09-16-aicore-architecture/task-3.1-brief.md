### Task 3.1: DDL（步骤级工单）

**Worktree**：`D:\progrom\.worktrees\aicore-architecture`，服务根 `services/aicore/`。
**Python**：`services/aicore/.venv\Scripts\python.exe`（Python 3.14.6）。**MUST NOT `pip install`**（沙箱会 `PermissionError`，依赖已装齐）。
**编码**：所有新文件 UTF-8 **无 BOM**；MUST NOT 用 PowerShell `Set-Content` / `Out-File` 写含中文的文件（会变 GBK）。
**真实 MySQL（本机已就绪，Task 3.1 起可用）**：
- 主机 `127.0.0.1:3306`，库 `aicore`、`aicore_test`（utf8mb4）；只读参考账号 `aicore_dev` / `Aicore_Dev_2026`（对 `aicore` 与 `aicore_test` 有 ALL 权限）。
- 客户端：`D:\soft\mysql\bin\mysql.exe`（警告 "password on command line" 是正常的，可忽略）。
- MySQL 服务由 Windows 服务 `MySQL` 承载（AUTO_START，已监听 `127.0.0.1:3306`）。**MUST NOT 手动 `mysqld.exe`**：手动实例会与服务抢数据目录，导致实例卡死。

**Files（11 个，一个不多一个不少）：**
| 路径 | 内容 |
|---|---|
| `deploy/sql/ddl/00_create_database.sql` | 建库 `aicore` 与 `aicore_test` |
| `deploy/sql/ddl/10_ai_task.template.sql` | 分片表模板（占位符） |
| `deploy/sql/ddl/11_ocr_result.template.sql` | 分片表模板 |
| `deploy/sql/ddl/12_ocr_correction.template.sql` | 分片表模板（**含同分片物理外键**） |
| `deploy/sql/ddl/20_vision_review.sql` | 非分片表 |
| `deploy/sql/ddl/21_vision_marker.sql` | 非分片表 |
| `deploy/sql/ddl/22_review_verdict.sql` | 非分片表 |
| `deploy/sql/ddl/23_kitchen_anomaly.sql` | 非分片表 |
| `deploy/sql/ddl/24_risk_predict_result.sql` | 非分片表 |
| `deploy/sql/ddl/25_vision_qa_log.sql` | 非分片表 |
| `tests/repository/test_ddl_matches_er.py` | 纯文本比对用例（**无需数据库**） |

另需创建 `tests/repository/__init__.py`（空文件，与 `tests/unit/__init__.py` 同款，使测试包可导入）。

---

#### 占位符约定（Task 3.3 要复用，**必须照此实现**）

分片表模板里出现**两个**占位符，且只有这两个：

| 占位符 | 渲染为 | 用途 |
|---|---|---|
| `{table}` | 本表的物理表名（`` `ai_task_202601` `` 形态的**裸名**，不含反引号） | `CREATE TABLE IF NOT EXISTS `{table}`` |
| `{month}` | 6 位 `YYYYMM` | 引用**同月同分片**的兄弟表：`` `ocr_result_{month}` `` |

**为什么要 `{month}` 而不是把整张表名也做成占位符**：`ocr_correction.task_id` 的物理外键必须指向**同月**的 `ocr_result_YYYYMM`；若只允许 `{table}`，模板就无法表达"同月的另一张表"。设计文档 §5.1 的"表名占位统一为 `{table}`"指的是**本表名**用 `{table}`，`{month}` 是它的补充而非替代——请在实现里按上表办，并在模板文件顶部注释写清这条。

**模板 MUST 满足**：
1. `CREATE TABLE IF NOT EXISTS`（幂等）；
2. 反引号包裹**表名与列名**（`port` / `status` 等词在 MySQL 中是保留字风险面）；
3. 渲染后即为可执行 SQL——**模板本身不能被执行**（含 `{` 会语法错），故文件名带 `.template.sql`；
4. 模板内**不写** `USE`；库由执行方指定。

---

#### 通用 DDL 约定（9 张表一致）

- `ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci`（每个 `CREATE TABLE` 末尾都写全）。
- 时间列一律 `datetime(3)`；`CURRENT_TIMESTAMP(3)` 只用于 `er.md` 明确标注该默认值的列，其余时间列**无默认值**。
- **MUST NOT 出现 `ON UPDATE CURRENT_TIMESTAMP`**：`er.md` 没有任何 `updated_at` 列，凭空加是偏离。
- `tinyint(1)` 用于布尔列；`int UNSIGNED` 用于 `progress` / `markers_count`。
- 中文注释：每张表 `COMMENT='...'`，每个列 `COMMENT '...'`，文案取 `er.md` §6 的"说明"列（可精简，但 MUST NOT 改变语义）。
- **物理外键统一 `ON DELETE RESTRICT ON UPDATE RESTRICT`**（MySQL 默认即 RESTRICT，**显式写出**是为了不让读者以为漏了）：`review_verdict` 是审计留痕、`ocr_correction` 是评估集语料，两者都要求不可被级联删除。
- **MUST NOT 建 `er.md` 未列出的列**（不加 `created_by` / `updated_at` / `deleted` 之类）。
- **索引照 `er.md` §7 逐项建**（见下面每张表的"索引"小节）；索引名**逐字照抄** §7。

---

#### 表 1｜`ai_task`（模板 `10_ai_task.template.sql`）

列（顺序照 `er.md` §6.1）：
```
task_id        varchar(32)  NOT NULL              COMMENT '任务号 task_ 前缀 + UUID'
account_id     varchar(32)  NOT NULL              COMMENT '提交账号，分表键'
idem_key       varchar(64)  NULL     DEFAULT NULL COMMENT '幂等键'
type           enum('OCR','VISION_REVIEW','KITCHEN_ANOMALY','RISK_PREDICT') NOT NULL
status         enum('PROCESSING','SUCCEEDED','FAILED','MANUAL_REVIEW')      NOT NULL DEFAULT 'PROCESSING'
progress       int unsigned NOT NULL DEFAULT 0
error_code     varchar(16)  NULL     DEFAULT NULL
model_meta     json         NULL     DEFAULT NULL
is_eval_sample tinyint(1)   NOT NULL DEFAULT 0
created_at     datetime(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3)
finished_at    datetime(3)  NULL     DEFAULT NULL
```
索引（`er.md` §7.1，**逐字**）：
- `PRIMARY KEY (task_id)`
- `KEY idx_account_created (account_id, created_at)`
- `UNIQUE KEY uk_idem (account_id, idem_key)`
- `KEY idx_status_created (status, created_at)`
- `KEY idx_eval (is_eval_sample, type)`

约束：无物理外键。

#### 表 2｜`ocr_result`（模板 `11_ocr_result.template.sql`）

```
task_id             varchar(32)  NOT NULL COMMENT '= ai_task.task_id，1:1 同月分片'
fields_json         json         NOT NULL
validity            enum('VALID','EXPIRING','EXPIRED','UNKNOWN') NOT NULL
category_match      tinyint(1)   NOT NULL DEFAULT 0
summary             varchar(255) NOT NULL
suggestions_json    json         NULL DEFAULT NULL
needs_manual_review tinyint(1)   NOT NULL DEFAULT 0
```
索引：`PRIMARY KEY (task_id)`，无附加索引。

**`ocr_result.task_id` → `ai_task.task_id` MUST NOT 建物理外键**（跨月分片表间建不了；`ocr_result` 与 `ai_task` 同月，但模板无法表达"引用同月另一张模板表"且设计文档 L290 明确要求不建）。请在模板顶部注释写出"逻辑关联 + 幂等补偿"。

#### 表 3｜`ocr_correction`（模板 `12_ocr_correction.template.sql`）

```
correction_id varchar(32)  NOT NULL COMMENT '纠错号 cor_ 前缀 + UUID'
task_id       varchar(32)  NOT NULL COMMENT '关联 OCR 任务（同月同分片路由键）'
field_name    varchar(64)  NOT NULL
ai_value      varchar(255) NULL DEFAULT NULL
human_value   varchar(255) NOT NULL
confidence    decimal(3,2) NULL DEFAULT NULL
corrected_by  varchar(64)  NOT NULL
corrected_at  datetime(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3)
```
索引（`er.md` §7.3）：`PRIMARY KEY (correction_id)`、`KEY idx_task (task_id)`、`KEY idx_field_corrected (field_name, corrected_at)`。

**物理外键（本模板的要点）**：
```
CONSTRAINT fk_ocr_correction_task FOREIGN KEY (task_id)
    REFERENCES `ocr_result_{month}` (`task_id`)
    ON DELETE RESTRICT ON UPDATE RESTRICT
```
被引用的 `ocr_result_{month}` 必须在**同月**已建（建表顺序：`ai_task` → `ocr_result` → `ocr_correction`）。

#### 表 4｜`vision_review`（`20_vision_review.sql`）

```
review_id        varchar(32) NOT NULL
task_id          varchar(32) NULL DEFAULT NULL
biz_type         enum('RAW_MATERIAL','CERTIFICATE','INSPECTION_SAMPLE','KITCHEN') NOT NULL
merchant_id      varchar(32) NULL DEFAULT NULL
merchant_name    varchar(64) NULL DEFAULT NULL
batch_id         varchar(32) NULL DEFAULT NULL
image_keys_json  json        NOT NULL
status           enum('AI_PROCESSING','PENDING','CONFIRMED','REFERRED','REJECTED','ARCHIVED') NOT NULL DEFAULT 'AI_PROCESSING'
confidence_level enum('HIGH','MEDIUM','LOW') NULL DEFAULT NULL
confidence       decimal(3,2) NULL DEFAULT NULL
markers_count    int unsigned NOT NULL DEFAULT 0
created_at       datetime(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3)
reviewed_at      datetime(3) NULL DEFAULT NULL
```
索引（§7.4）：`PRIMARY KEY (review_id)`、`KEY idx_merchant_created (merchant_id, created_at)`、`KEY idx_status_created (status, created_at)`、`KEY idx_task (task_id)`。无外键。

#### 表 5｜`vision_marker`（`21_vision_marker.sql`）

```
marker_id  varchar(32)  NOT NULL
review_id  varchar(32)  NOT NULL
label      varchar(64)  NOT NULL
level      enum('HIGH','MEDIUM','LOW') NOT NULL
confidence decimal(3,2) NOT NULL
bbox_json  json         NULL DEFAULT NULL
suggestion varchar(255) NULL DEFAULT NULL
```
索引（§7.5）：`PRIMARY KEY (marker_id)`、`KEY idx_review (review_id)`。
物理外键：`fk_vision_marker_review`，`review_id` → `vision_review(review_id)`，`ON DELETE RESTRICT ON UPDATE RESTRICT`。

#### 表 6｜`review_verdict`（`22_review_verdict.sql`）

```
review_id           varchar(32)  NOT NULL
action              enum('CONFIRM','REFER','REJECT','ARCHIVE') NOT NULL
comment             varchar(200) NULL DEFAULT NULL
reviewed_by         varchar(64)  NOT NULL
reviewed_at         datetime(3)  NOT NULL
authority_written   tinyint(1)   NOT NULL DEFAULT 0
authority_event_id  varchar(32)  NULL DEFAULT NULL
authority_written_at datetime(3) NULL DEFAULT NULL
```
注意：`comment` 是 MySQL 关键字，**必须反引号**。`reviewed_at` **无默认值**（由业务写入时刻决定，`er.md` "默认"列为 `—`）。
索引（§7.6）：`PRIMARY KEY (review_id)`、`KEY idx_reviewed_at (reviewed_at)`。
物理外键：`fk_review_verdict_review`，`review_id` → `vision_review(review_id)`（1:1），RESTRICT。

#### 表 7｜`kitchen_anomaly`（`23_kitchen_anomaly.sql`）

```
anomaly_id       varchar(32) NOT NULL
review_id        varchar(32) NULL DEFAULT NULL
merchant_id      varchar(32) NULL DEFAULT NULL
merchant_name    varchar(64) NULL DEFAULT NULL
stream_id        varchar(64) NOT NULL
anomaly_type     varchar(64) NOT NULL
confidence       decimal(3,2) NOT NULL
confidence_level enum('HIGH','MEDIUM','LOW') NULL DEFAULT NULL
status           enum('PENDING','CONFIRMED','REJECTED','ARCHIVED') NOT NULL DEFAULT 'PENDING'
detected_at      datetime(3) NOT NULL
reviewed_at      datetime(3) NULL DEFAULT NULL
```
索引（§7.7）：`PRIMARY KEY (anomaly_id)`、`KEY idx_stream_detected (stream_id, detected_at)`、`KEY idx_status (status, detected_at)`、`KEY idx_review (review_id)`。
物理外键：`fk_kitchen_anomaly_review`，`review_id` → `vision_review(review_id)`，RESTRICT（**可空**列上的外键，NULL 不受约束）。

#### 表 8｜`risk_predict_result`（`24_risk_predict_result.sql`）

```
merchant_id      varchar(32) NOT NULL
merchant_name    varchar(64) NULL DEFAULT NULL
risk_score       decimal(5,2) NOT NULL
risk_level       enum('LOW','MEDIUM','HIGH','CRITICAL') NOT NULL
factors_json     json NOT NULL
suggestions_json json NULL DEFAULT NULL
predicted_at     datetime(3) NOT NULL
```
索引（§7.8）：`PRIMARY KEY (merchant_id)`、`KEY idx_predicted (predicted_at)`。无外键。

#### 表 9｜`vision_qa_log`（`25_vision_qa_log.sql`）

```
qa_id      varchar(32)  NOT NULL
account_id varchar(32)  NULL DEFAULT NULL
image_key  varchar(255) NOT NULL
question   varchar(200) NOT NULL
answer     varchar(500) NOT NULL
confidence decimal(3,2) NULL DEFAULT NULL
disclaimer varchar(255) NOT NULL
created_at datetime(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3)
```
索引（§7.9）：`PRIMARY KEY (qa_id)`、`KEY idx_account_created (account_id, created_at)`。无外键。

---

#### 用例 `tests/repository/test_ddl_matches_er.py`（**纯文本，无需数据库**）

必须包含这 5 组断言（缺一不可）：

1. **逐列比对**：解析 `docs/er.md` §6 的 9 张表 markdown 表格（列：字段/类型/空/键/默认/说明），得到 `{表: [(列名, 类型, 是否可空)]}`；解析 `deploy/sql/ddl/*.sql`（模板按 `{table}`→`<逻辑名>` 渲染后解析），逐列比对：**表集合相等、每表列名序列相等、类型相等、可空性相等**。差异信息 MUST 是可读清单（哪张表、哪个字段、期望与实际），而不是一句 assert False。
2. **枚举 ↔ openapi.yaml 一一对应**：解析 `docs/openapi.yaml` 的 `enum: [...]` 行，与 DDL 里 `enum('...')` 的值集合比对。对应关系（**逐条**）：
   | DDL 列 | openapi schema |
   |---|---|
   | `ai_task.type` | `TaskType` |
   | `ai_task.status` | `TaskStatus` |
   | `ocr_result.validity` | `DocValidity`（`openapi.yaml` 中在 `validity` 属性上的内联 enum，行 ~734） |
   | `vision_review.biz_type` | `VisionBizType` |
   | `vision_review.status` | `VisionReviewStatus` |
   | `vision_review.confidence_level` / `vision_marker.level` / `kitchen_anomaly.confidence_level` | `ConfidenceLevel` |
   | `review_verdict.action` | `VerdictAction` |
   | `kitchen_anomaly.status` | `AnomalyStatus`（内联，行 ~1089） |
   | `risk_predict_result.risk_level` | `RiskLevel` |
   实现方式自选（抽查式硬编码期望值 + 与 openapi 解析结果双向断言），但**MUST 对得上**，且 openapi 侧改动后本用例必须变红。
3. **占位符协议**：三个模板都含 `{table}` 与 `{month}`；`12_ocr_correction.template.sql` 含 `REFERENCES` 且引用`` `ocr_result_{month}` ``；渲染函数（本用例内部的小工具，`str.replace`）对 `{table}`/`{month}` 各渲染一次后**不再含 `{`**。
4. **幂等性**：每个 DDL 文件的每张表都是 `CREATE TABLE IF NOT EXISTS`；`00_create_database.sql` 是 `CREATE DATABASE IF NOT EXISTS`。
5. **通用约定**：每个 `CREATE TABLE` 都含 `ENGINE=InnoDB`、`utf8mb4`；无 `ON UPDATE CURRENT_TIMESTAMP`；无 `er.md` 未列出的列（由断言 1 覆盖，无需重复实现）。

**禁止**：把 `er.md` 的列名/类型**抄进用例当期望值**（那就是抄两遍、双双写错也发现不了）；期望值 MUST 从 `docs/er.md` 解析得到。

#### 真实 MySQL 执行（Step 2，须留下原始输出）

在 worktree 内执行（示例，`<MYSQL>` = `D:\soft\mysql\bin\mysql.exe`）：

1. `& <MYSQL> -h 127.0.0.1 -u aicore_dev -p'...' < deploy/sql/ddl/00_create_database.sql`
2. 用 `.venv\Scripts\python.exe` 写一个**临时**渲染脚本（跑完删除，MUST NOT 留在仓库），把三个模板按 `month=202601` 渲染成真实 SQL，**按 `ai_task_202601` → `ocr_result_202601` → `ocr_correction_202601` 顺序**执行，再执行 6 个非分片文件；库指定 `aicore_test`（避免污染 `aicore`）。
3. 幂等复跑：**同样两条命令再跑一遍**，MUST 零错误。
4. 用 `information_schema` 自查：9 张逻辑表（3 张分片表以 `_202601` 结尾）+ 期望的索引名/外键名**逐项**列出。原始输出粘进报告。
5. Python 依赖：优先 `sqlalchemy` + `pymysql`（已在 `.venv`）连接，或直接 `mysql.exe`。**MUST NOT** 安装任何包。

**清理**：临时渲染脚本、`*.sql` 生成物、日志一律删除；`git status` 只应出现本任务的文件。

---

**验收（自证）**：
- `python -m pytest tests/repository -q` 全绿（无 MySQL 依赖）；
- 真实 MySQL 上 9 张表建表成功、复跑幂等、`information_schema` 逐项核对无差异；
- `.venv\Scripts\ruff.exe check . --no-cache` → `All checks passed!`；
- `.venv\Scripts\mypy.exe src` → `Success: no issues found`（本任务只新增测试，`mypy` 只覆盖 `src`，仍须干净）；
- `.venv\Scripts\lint-imports.exe --config .importlinter --no-cache` → `4 kept, 0 broken`；
- 报告里给出**原始命令与原始输出**（不是"我跑过了"），并列出**任何**偏离本工单之处及理由。
