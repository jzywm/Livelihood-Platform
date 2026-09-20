### Task 3.2: SQLAlchemy 模型（步骤级工单）

**Worktree**：`D:\progrom\.worktrees\aicore-architecture`，服务根 `services/aicore/`。
**Python**：`services/aicore/.venv\Scripts\python.exe`（3.14.6）。**MUST NOT `pip install`**（依赖已装齐，沙箱装包必 `PermissionError`）。
**编码**：新文件 UTF-8 无 BOM；MUST NOT 用 PowerShell `Set-Content`/`Out-File` 写含中文的文件。

**Files:**
- Modify: `src/aicore/repository/models.py`
- Create: `tests/unit/test_models.py`

**前置事实（Task 3.1 已完成，MUST 先读）**：`deploy/sql/ddl/` 下 10 个 DDL 文件是**权威结构定义**；
`docs/er.md` §6 是字段口径来源。**MUST** 先读 `deploy/sql/ddl/10_ai_task.template.sql`（模板与注释风格范例）、
`11_ocr_result.template.sql`、`12_ocr_correction.template.sql`、`20_~25_*.sql`，**逐列对照**写模型。
**MUST NOT** 凭 `er.md` 的 markdown 表格"差不多"地写——以 DDL 为准，两者若不一致**立刻停下并报告**（那是 Task 3.6 要抓的缺陷，不该由你猜）。

**Task 3.1 已完成并已提交**（`2a04934` / `bd6c9d3`），落地事实：
- DDL 列定义已实测干净（真实 MySQL 上 9 表 / 4 外键 / 24 索引全部核对通过）；
- 分片表外键约束名形如 `fk_ocr_correction_task_{month}`（可任选月份重建，不会撞名）；
- **已有一份可用的离线比对实现**：`tests/repository/test_ddl_matches_er.py`
  （`parse_ddl_tables` / `parse_er_tables` / `_split_top_level` / `strip_sql_comments` 等）。
  Task 3.6 会把它抽到 `src/aicore/repository/schema.py` 作为共享层。
  **你可以读它来确认"DDL 里到底写了什么"**，但 **MUST NOT 修改它**（它已被 Task 3.1 验收并提交）；
  也 **MUST NOT 在 `models.py` 里 import 它**（`tests/` 不在包路径下，且会让 models 依赖测试代码）。

---

#### 设计口径（三条硬约束）

**① 分片表不写死表名、也不动态改表名。**
`AiTask` / `OcrResult` / `OcrCorrection` 三个模型是**逻辑表定义**，`__tablename__` 取逻辑名
（`ai_task` / `ocr_result` / `ocr_correction`），并额外导出：

```python
LOGICAL_TABLE_NAMES: dict[type[Base], str] = {
    AiTask: "ai_task",
    OcrResult: "ocr_result",
    OcrCorrection: "ocr_correction",
    VisionReview: "vision_review",
    VisionMarker: "vision_marker",
    ReviewVerdict: "review_verdict",
    KitchenAnomaly: "kitchen_anomaly",
    RiskPredictResult: "risk_predict_result",
    VisionQaLog: "vision_qa_log",
}
```

**为什么不在模型上动态改 `__tablename__`**：Task 3.6 的离线比对要读 `Base.metadata`，元数据里必须是**逻辑名**才谈得上"逐列比对"；
物理名（`ai_task_202601`）由 Task 3.3 的 `physical_table_name()` 现算。模型层一旦能改表名，
元数据就同时承载两种语义，比对器与迁移都会跟着含糊。
**MUST NOT** 定义 12 个"每月一个模型类"的子类；**MUST NOT** 让任何模型的 `__tablename__` 含 `YYYYMM`。

**② 类型映射（逐条，不许自创）**

| er.md / DDL 类型 | SQLAlchemy |
|---|---|
| `varchar(n)` | `String(n)`；`Mapped[str]`（NULL 列 `Mapped[str \| None]`） |
| `enum('A','B')` | `Mapped[str]` + `Enum("A", "B", name="...", native_enum=True, validate_strings=True, length=<最长值长度>)` |
| `tinyint(1)`（布尔语义） | `Mapped[bool]` + `Boolean()` |
| `int unsigned` | `Mapped[int]` + `Integer()`（+ `unsigned=True` 若不想被 autogenerate 反复改；见下） |
| `decimal(3,2)` / `decimal(5,2)` | `Mapped[Decimal]` + `Numeric(3, 2)` / `Numeric(5, 2)` |
| `datetime(3)` | `Mapped[datetime]` + `DateTime()`（**MUST NOT** `timezone=True`：MySQL `DATETIME` 不存时区，UTC 是应用层约定） |
| `json` | 见下 |

- **枚举每一列都要显式 `length=`**：`length` 缺省时 SQLAlchemy 会取最长枚举值长度，
  但写出来才不会被后人误认为"漏了"。`name=` 取 `"ai_task_type"` 这类**snake_case 全小写**名
  （MySQL 原生 ENUM **不会**在库里建出这个类型名，`name` 只影响 SQLAlchemy 内部标识与 `CREATE TYPE` 方言）。
  给定 `length=` 时，`ai_task.type` 的最长值是 `KITCHEN_ANOMALY`（15）——**MUST 按实际最长值填**，不要照抄本行示例。
- **JSON 列的 `Mapped[...]` 标注**：本组先用 `type JsonValue = dict[str, Any] | list[Any]` 这一处别名，
  各列按语义收窄到 `Mapped[dict[str, Any]]` / `Mapped[list[Any]]`。**若 mypy strict 因 `Any` 报错，即刻停下报告**，
  不要为了让 mypy 闭嘴而把类型退化成 `Mapped[Any]` 或 `object`（那会让 3.7 的读写代码失去检查）。
- **`unsigned=True` 的取舍**：`progress` / `markers_count` 是 `int unsigned`。SQLAlchemy 的 `Integer` 默认渲染
  `INTEGER`（无 UNSIGNED）。**给 `Integer(unsigned=True)`**，使 Task 3.5 的 autogenerate 不会每跑一次就想把列改成有符号。
  若该参数在 SQLAlchemy 2.0.54 上行为不符（如被静默忽略），**停下报告**，不要静默降级。

**③ 服务端默认值必须显式写出。**
DDL 里有 `DEFAULT CURRENT_TIMESTAMP(3)` 与 `DEFAULT 0` / `DEFAULT 'PROCESSING'` 等。
模型侧**MUST** 用 `server_default=text("CURRENT_TIMESTAMP(3)")` / `server_default=text("0")` /
`server_default=text("'PROCESSING'")` 表达（字符串默认值要带内层单引号）。
**理由**：不写 `server_default`，Task 3.5 的 Alembic autogenerate 会认为库里多了一列默认值、
每次都想生成一条 `alter_column`，迁移就不再收敛。`default=`（Python 侧）**可选**、非必需。

---

#### 9 个模型逐列清单（顺序、可空、主键 MUST 与 DDL 完全一致）

**`AiTask` → `ai_task`**（分片）
`task_id` PK `String(32)` ｜ `account_id` `String(32)` NOT NULL ｜ `idem_key` `String(64)` NULL
`type` enum 4 值 NOT NULL ｜ `status` enum 4 值 NOT NULL `server_default 'PROCESSING'`
`progress` int unsigned NOT NULL `server_default 0` ｜ `error_code` `String(16)` NULL ｜ `model_meta` json NULL
`is_eval_sample` bool NOT NULL `server_default 0` ｜ `created_at` `DateTime` NOT NULL `server_default CURRENT_TIMESTAMP(3)` ｜ `finished_at` `DateTime` NULL

**`OcrResult` → `ocr_result`**（分片）
`task_id` PK `String(32)` ｜ `fields_json` json NOT NULL ｜ `validity` enum 4 值 NOT NULL
`category_match` bool NOT NULL `server_default 0` ｜ `summary` `String(255)` NOT NULL
`suggestions_json` json NULL ｜ `needs_manual_review` bool NOT NULL `server_default 0`

**`OcrCorrection` → `ocr_correction`**（分片，**含物理外键**）
`correction_id` PK `String(32)` ｜ `task_id` `String(32)` NOT NULL + `ForeignKey("ocr_result.task_id", ondelete="RESTRICT", onupdate="RESTRICT")`
`field_name` `String(64)` NOT NULL ｜ `ai_value` `String(255)` NULL ｜ `human_value` `String(255)` NOT NULL
`confidence` `Numeric(3,2)` NULL ｜ `corrected_by` `String(64)` NOT NULL ｜ `corrected_at` `DateTime` NOT NULL `server_default CURRENT_TIMESTAMP(3)`

**`VisionReview` → `vision_review`**
`review_id` PK `String(32)` ｜ `task_id` `String(32)` NULL ｜ `biz_type` enum 4 值 NOT NULL
`merchant_id` `String(32)` NULL ｜ `merchant_name` `String(64)` NULL ｜ `batch_id` `String(32)` NULL
`image_keys_json` json NOT NULL ｜ `status` enum 6 值 NOT NULL `server_default 'AI_PROCESSING'`
`confidence_level` enum 3 值 NULL ｜ `confidence` `Numeric(3,2)` NULL
`markers_count` int unsigned NOT NULL `server_default 0` ｜ `created_at` `DateTime` NOT NULL `server_default CURRENT_TIMESTAMP(3)` ｜ `reviewed_at` `DateTime` NULL

**`VisionMarker` → `vision_marker`**（物理外键 → vision_review）
`marker_id` PK `String(32)` ｜ `review_id` `String(32)` NOT NULL + FK ｜ `label` `String(64)` NOT NULL
`level` enum 3 值 NOT NULL ｜ `confidence` `Numeric(3,2)` NOT NULL ｜ `bbox_json` json NULL ｜ `suggestion` `String(255)` NULL

**`ReviewVerdict` → `review_verdict`**（1:1 物理外键）
`review_id` PK `String(32)` + FK ｜ `action` enum 4 值 NOT NULL ｜ `comment` `String(200)` NULL
`reviewed_by` `String(64)` NOT NULL ｜ `reviewed_at` `DateTime` NOT NULL（**无 server_default**）
`authority_written` bool NOT NULL `server_default 0` ｜ `authority_event_id` `String(32)` NULL ｜ `authority_written_at` `DateTime` NULL

**`KitchenAnomaly` → `kitchen_anomaly`**（物理外键，**可空列上的 FK**）
`anomaly_id` PK `String(32)` ｜ `review_id` `String(32)` NULL + FK ｜ `merchant_id` `String(32)` NULL
`merchant_name` `String(64)` NULL ｜ `stream_id` `String(64)` NOT NULL ｜ `anomaly_type` `String(64)` NOT NULL
`confidence` `Numeric(3,2)` NOT NULL ｜ `confidence_level` enum 3 值 NULL
`status` enum 4 值 NOT NULL `server_default 'PENDING'` ｜ `detected_at` `DateTime` NOT NULL ｜ `reviewed_at` `DateTime` NULL

**`RiskPredictResult` → `risk_predict_result`**
`merchant_id` PK `String(32)` ｜ `merchant_name` `String(64)` NULL ｜ `risk_score` `Numeric(5,2)` NOT NULL
`risk_level` enum 4 值 NOT NULL ｜ `factors_json` json NOT NULL ｜ `suggestions_json` json NULL ｜ `predicted_at` `DateTime` NOT NULL

**`VisionQaLog` → `vision_qa_log`**
`qa_id` PK `String(32)` ｜ `account_id` `String(32)` NULL ｜ `image_key` `String(255)` NOT NULL
`question` `String(200)` NOT NULL ｜ `answer` `String(500)` NOT NULL ｜ `confidence` `Numeric(3,2)` NULL
`disclaimer` `String(255)` NOT NULL ｜ `created_at` `DateTime` NOT NULL `server_default CURRENT_TIMESTAMP(3)`

**外键命名 MUST 与 DDL 一致**：`fk_ocr_correction_task` / `fk_vision_marker_review` / `fk_review_verdict_review` /
`fk_kitchen_anomaly_review`（用 `ForeignKey(..., name="fk_...")`）。

---

#### `__table_args__`：索引 MUST 与 DDL 逐项一致

每个模型 `__table_args__` 必须显式声明**该表 DDL 里的全部非主键索引**（含唯一键）：
用 `Index("idx_name", "col_a", "col_b")` 与 `UniqueConstraint("account_id", "idem_key", name="uk_idem")`，
或等价的 `mapped_column(index=True)`——**但索引名必须逐字等于 DDL 里的名字**。
**MUST NOT** 让 SQLAlchemy 自动生成名字（如 `ix_ai_task_account_id`）——Task 3.6 会把 `Base.metadata` 的索引名与 DDL 比对。
逐表索引清单见 `deploy/sql/ddl/*.sql`（或工单 Task 3.1 §每张表"索引"小节）。
`ocr_result` / `review_verdict` 之外的表注意别漏 `idx_eval`、`idx_field_corrected`、`idx_stream_detected` 等。

**注意**：主键用 `primary_key=True` 表达，**MUST NOT** 在 `__table_args__` 里再写一遍 `PrimaryKeyConstraint`。

---

#### `Base` 定义

```python
class Base(DeclarativeBase):
    """声明式基类。元数据里的表名是**逻辑名**，物理分片名由 repository/sharding.py 现算。"""
```
`models.py` 的模块 docstring MUST 说明：本模块是 DDL 的**唯一代码侧映射**，
结构变更 MUST 先改 DDL 再改本模块，两边的偏差由 `tests/repository/test_ddl_matches_er.py`（Task 3.1）
与 `scripts/compare_schema.py`（Task 3.6，含模型元数据这一源）强制抓出。

---

#### 用例 `tests/unit/test_models.py`（无需数据库）

MUST 包含：
1. **9 个模型 ↔ 逻辑表名**：`LOGICAL_TABLE_NAMES` 恰有 9 项，键集合等于 9 个模型类，值等于预期逻辑名；
   且每个模型的 `__tablename__ == LOGICAL_TABLE_NAMES[model]`。
2. **主键**：逐表断言主键列名（`ai_task`→`task_id`，`ocr_correction`→`correction_id`，`risk_predict_result`→`merchant_id`）。
3. **可空性**：对**每张表**逐列断言 `nullable`（从 `model.__table__.columns` 读），期望值**照 DDL 写**。
   这是本用例的核心价值：模型与 DDL 走偏会被抓住。**不要**用循环正则会漏项的写法，逐表逐列写清楚。
4. **枚举值集合**：逐枚举列断言 `column.type.enums` 的**元组**（顺序也要与 DDL 一致）。
5. **索引与唯一键名**：逐表断言非主键索引名集合与 `uk_idem`。
6. **外键**：4 个 FK 的目标表与目标列、`ondelete`/`onupdate` 均为 `"RESTRICT"`。
7. **`server_default` 存在性**：`created_at` 等带默认值的列，其 `server_default` 的 SQL 文本含 `CURRENT_TIMESTAMP(3)`；
   `reviewed_at` / `predicted_at` / `detected_at` **断言 `server_default is None`**（反向断言，防止顺手加了默认值）。
8. **元数据里没有物理分片名**：`Base.metadata.tables` 的键集合**不含**任何以 6 位数字结尾的名字。

---

**验收（自证）**：
- `.venv\Scripts\python.exe -m pytest tests/unit/test_models.py -q` 全绿；
- `.venv\Scripts\python.exe -m pytest -q` 全量仍全绿（**MUST NOT 弄红既有 387 条**）；
- `.venv\Scripts\ruff.exe check . --no-cache` → `All checks passed!`；
- `.venv\Scripts\mypy.exe src` → `Success: no issues found`（**strict 模式**，`repository/models.py` 必须过）；
- `.venv\Scripts\lint-imports.exe --config .importlinter --no-cache` → `4 kept, 0 broken`；
- 报告里给出**原始命令 + 原始输出**，并逐项列出**任何偏离本工单之处 + 理由**；没有就写"无偏离"。
- **MUST NOT `git commit`**（控制者统一提交）。

**报告写入**：`.superpowers/sdd/2026-09-16-aicore-architecture/task-3.2-report.md`
