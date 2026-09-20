# Task 3.2 报告：SQLAlchemy 模型（9 表）

**状态**：完成。5 道门禁全绿；**2 处偏离工单**（均为 SQLAlchemy 2.0.54 的类型行为所致，均已用单元测试守住，**没有静默降级**），0 处结构漏项。
**工作树**：`D:\progrom\.worktrees\aicore-architecture`，服务根 `services/aicore/`。
**MUST NOT `git commit`** —— 未提交，改动留在工作区等控制者统一提交。

---

## 1. 交付文件清单

| 文件 | 动作 | 规模 |
|---|---|---|
| `services/aicore/src/aicore/repository/models.py` | 修改（原为 1 行 docstring 占位） | 511 行 |
| `services/aicore/tests/unit/test_models.py` | 新建 | 757 行 / **196 条用例** |

`models.py` 内容：模块 docstring（权威口径 + 类型映射表 + 两处偏离的登记）、
`Base(DeclarativeBase)`、9 个模型（80 列）、`LOGICAL_TABLE_NAMES`（9 项）、
两个类型助手 `_datetime_ms()` / `_unsigned_int()`、`type JsonValue` 别名。
`test_models.py` 内容：期望值**照 DDL 逐列抄写**（列名/顺序/可空性/枚举值/索引名与列序/
外键/server_default），全部为字面量，不解析 DDL、不连库。

文件编码实测：两文件均 **UTF-8 无 BOM、LF 行尾**，与既有源码一致
（`bom=False crlf=0 lf=511` / `bom=False crlf=0 lf=757`）。

---

## 2. 验证命令与原始输出

### 2.1 本任务用例（工单原命令）

```
$ .venv\Scripts\python.exe -m pytest tests/unit/test_models.py -q
........................................................................ [ 36%]
........................................................................ [ 73%]
....................................................                     [100%]
============================== warnings summary ===============================
.venv\Lib\site-packages\_pytest\cacheprovider.py:469
  ...PytestCacheWarning: could not create cache path ...\pytest-cache-files-x5_5tq4q: [WinError 5] 拒绝访问。
-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
[exit code: 0]
```

> 计数行为说明：`pyproject.toml` 的 `addopts = "-q"` 与命令行 `-q` 叠加成 `-qq`，
> 该模式下 pytest 不打印末行计数。故另跑一次单 `-q` 取计数（去掉缓存插件以消掉上面那条
> 沙箱权限警告）：

```
$ .venv\Scripts\python.exe -m pytest tests/unit/test_models.py -p no:cacheprovider
........................................................................ [ 36%]
........................................................................ [ 73%]
....................................................                     [100%]
196 passed in 0.48s
[exit code: 0]
```

### 2.2 全量回归（工单原命令）

```
$ .venv\Scripts\python.exe -m pytest -q
........................................................................ [ 10%]
.............................sssssss.................................... [ 21%]
........................................................................ [ 31%]
....................................................................s... [ 42%]
........................................................................ [ 53%]
........................................................................ [ 63%]
........................................................................ [ 74%]
........................................................................ [ 85%]
........................................................................ [ 95%]
.............................                                            [100%]
[exit code: 0]
```

同一条全量、单 `-q` 取计数：

```
$ .venv\Scripts\python.exe -m pytest -p no:cacheprovider
669 passed, 8 skipped in 22.68s
[exit code: 0]
```

**基线核对（重要）**：把本任务的新用例排除后重跑，得

```
$ .venv\Scripts\python.exe -m pytest -p no:cacheprovider --ignore=tests/unit/test_models.py
473 passed, 8 skipped in 19.23s
[exit code: 0]
```

即既有用例 473 passed / 8 skipped —— **工单写的「基线 453 passed, 8 skipped」是旧数字**
（实测基线比工单多 20 条，我未改动任何既有用例）。473 + 196 = 669，与全量计数一致，
**既有用例一条未变红**。

### 2.3 ruff

```
$ .venv\Scripts\ruff.exe check . --no-cache
warning: Encountered error: 拒绝访问。 (os error 5)      ← ×10（沙箱下 pytest 缓存目录不可读）
All checks passed!
[exit code: 0]
```

那 10 条 `os error 5` 来自工作区里既有的 `pytest-cache-files-*` / `.pytest_cache` 目录
（沙箱只读权限），与本任务两个文件无关；`All checks passed!` 与退出码 0 是门禁结论。

首轮实测曾有 2 条 E501（视觉宽度 106/107 > 100），出现在 `VisionMarker` /
`ReviewVerdict` 两个类 docstring 的单行中文说明上，已拆成多行修掉 —— 与工单预先提醒的
「E501 按视觉宽度计」一致。

### 2.4 mypy（strict）

```
$ .venv\Scripts\mypy.exe src
Success: no issues found in 51 source files
[exit code: 0]
```

**JSON 列的 `Any` 未触发任何 mypy 报错**，故未出现工单担心的「为闭嘴而退化成
`Mapped[Any]`」的情形：`model_meta` / `bbox_json` 是 `Mapped[dict[str, Any] | None]`，
`fields_json` / `image_keys_json` / `factors_json` 是 `Mapped[list[Any]]`，
`suggestions_json` 是 `Mapped[list[Any] | None]`（对象/数组的取舍依据 openapi 的
`OcrResult.fields`（array）、`MatchResult.suggestions`（array of string）、
`VisionReview.imageKeys`（array）、`VisionMarker.bbox`（object）、
`RiskPredict.factors/suggestions`（array）、`modelMeta`（object））。

### 2.5 import-linter

```
$ .venv\Scripts\lint-imports.exe --config .importlinter --no-cache
Analyzed 51 files, 12 dependencies.
api 层不得直接依赖 repository / provider KEPT
service 层只可与 provider.base 交互，不得依赖具体通道实现 KEPT (1 warning)
repository / provider / port 不得反向依赖 service KEPT
core 不得依赖任何业务层 KEPT

Contracts: 4 kept, 0 broken.

Warnings
- No matches for ignored import aicore.service.** -> aicore.provider.base.
[exit code: 0]
```

该 warning 是 `.importlinter` 里**预先登记**的 `unmatched_ignore_imports_alerting = warn`
（Task 4 落地真实 Protocol 导入后自动消失），非本任务引入。

### 2.6 git 交付面

```
$ git -C <worktree> status --short
 M services/aicore/src/aicore/repository/models.py
?? services/aicore/tests/unit/test_models.py
?? .sdd-tools.py
```

`.sdd-tools.py`（工作树根）**不是我建的、也不属于本任务**：它在我开工前的首次
`git status` 里就存在，是 SDD 工具脚本（文件首行说明「SDD 脚本等价复现（沙箱内
sh.exe 不可用）」），故未删除。除它之外，交付面就是本任务的两个文件。
本任务**未创建任何一次性探针脚本文件**（探查一律用 `python -c` 内联执行，无残留）。

本报告本身不在 `git status` 里：`.superpowers/sdd/.gitignore` 的内容是 `*`
（`git check-ignore -v` 实测命中该行），整份 SDD 记录目录被忽略，属预期。

---

## 3. 逐项验收结论

### 3.1 工单「9 个模型逐列清单」对照（DDL 为唯一权威）

| 模型 | 逻辑表名 | 列数 | 主键 | 非主键索引 | 外键 |
|---|---|---|---|---|---|
| `AiTask` | `ai_task`（分片） | 11 | `task_id` | `idx_account_created` / `uk_idem`(UNIQUE) / `idx_status_created` / `idx_eval` | — |
| `OcrResult` | `ocr_result`（分片） | 7 | `task_id` | — | — |
| `OcrCorrection` | `ocr_correction`（分片） | 8 | `correction_id` | `idx_task` / `idx_field_corrected` | `fk_ocr_correction_task` → `ocr_result.task_id` |
| `VisionReview` | `vision_review` | 13 | `review_id` | `idx_merchant_created` / `idx_status_created` / `idx_task` | — |
| `VisionMarker` | `vision_marker` | 7 | `marker_id` | `idx_review` | `fk_vision_marker_review` → `vision_review.review_id` |
| `ReviewVerdict` | `review_verdict` | 8 | `review_id` | `idx_reviewed_at` | `fk_review_verdict_review` → `vision_review.review_id` |
| `KitchenAnomaly` | `kitchen_anomaly` | 11 | `anomaly_id` | `idx_stream_detected` / `idx_status` / `idx_review` | `fk_kitchen_anomaly_review` → `vision_review.review_id` |
| `RiskPredictResult` | `risk_predict_result` | 7 | `merchant_id` | `idx_predicted` | — |
| `VisionQaLog` | `vision_qa_log` | 8 | `qa_id` | `idx_account_created` | — |

合计 80 列 / 17 个非主键索引（16 KEY + 1 UNIQUE）/ 4 个物理外键，**逐项从
`deploy/sql/ddl/*.sql` 读取后落位**，DSL 顺序也照 DDL 正文。4 个外键的
`ondelete` / `onupdate` 全为 `RESTRICT`；分片表的约束名只写逻辑名
（`fk_ocr_correction_task`），物理名 `fk_ocr_correction_task_{month}` 由建表流程现算。

`er.md` §6 与 DDL 逐列对照**没有发现不一致**（这正是工单要求「不一致就停下报告」的情形，
未触发）：类型、可空、默认、枚举值全部一致。

### 3.2 工单「用例 MUST 包含」8 项

| 工单项 | 覆盖用例 | 结论 |
|---|---|---|
| 1. 9 模型 ↔ 逻辑表名 | `test_logical_table_names_has_exactly_nine_entries`、`test_tablename_equals_logical_name`(×9) | ✅ 恰 9 项、键集合等于 9 个模型类、值等于预期逻辑名 |
| 2. 主键 | `test_primary_key_matches_ddl`(×9) | ✅ 9 表逐表断言列名，且**恰 1 列** |
| 3. 可空性 | `test_column_nullable_matches_ddl`(×80)、`test_column_names_and_order_match_ddl`(×9) | ✅ 逐表逐列字面量断言（非正则推导）；另断言列名与顺序、且可空性字典键集合 == 列集合（防漏项） |
| 4. 枚举值集合 | `test_enum_values_match_ddl`(×11)、`test_enum_length_is_longest_value`(×11) | ✅ 11 个枚举列断 `enums` 元组（含顺序）+ `native_enum` + `validate_strings`；`length` 断言等于最长值长度 |
| 5. 索引与唯一键名 | `test_indexes_match_ddl`(×9)、`test_unique_constraints_match_ddl`(×9) | ✅ 索引名与列序逐项相等；`uk_idem` 单独核对，其余表唯一约束集合为空 |
| 6. 外键 | `test_foreign_keys_match_ddl`(×4)、`test_metadata_has_exactly_four_foreign_keys`、`test_foreign_key_names_carry_no_month_suffix` | ✅ 目标表/列 + `constraint.name` + 双 `RESTRICT`；全库恰 4 条；名字不含 6 位月份后缀 |
| 7. `server_default` 存在性 | `test_server_default_matches_ddl`(×13)、`test_columns_without_ddl_default_have_no_server_default`(×9)、`test_business_time_columns_have_no_server_default`(×4) | ✅ 13 个带默认值列逐字断言 SQL 文本（含 `CURRENT_TIMESTAMP(3)`）；并**反向**断言「有 server_default 的列集合恰等于 DDL 有 DEFAULT 的集合」；`reviewed_at`(vision_review)、`detected_at`/`reviewed_at`(kitchen_anomaly)、`predicted_at`(risk_predict_result) 四条单独断言 `is None` |
| 8. 元数据无物理分片名 | `test_metadata_table_names_are_logical_only`、`test_no_model_tablename_contains_year_month` | ✅ `Base.metadata.tables` 恰 9 个逻辑名、无 `_\d{6}$`；任何 `__tablename__` 不含 6 位数字 |

额外自加的用例（工单未要求，用于守住两处偏离与防「假绿」）：

- `test_unsigned_columns_render_integer_unsigned`：编译 MySQL 方言 DDL，断言
  `progress INTEGER UNSIGNED NOT NULL DEFAULT 0` / `markers_count INTEGER UNSIGNED NOT NULL DEFAULT 0`；
- `test_datetime_columns_render_millisecond_precision`：断言
  `created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3)`，且无默认值的
  `reviewed_at DATETIME(3)` 后面不出现 `DEFAULT`；
- `test_datetime_columns_are_not_timezone_aware`（×9）+ `test_datetime_column_count_is_not_vacuous`
  （**非空下限**：全库 `datetime(3)` 列恰 11 列，防止上一条扫到 0 列而静默全绿）；
- `test_other_types_render_as_ddl_synonyms`：`BOOL`(=tinyint(1)) / 内联 `ENUM(...)` /
  `VARCHAR(32)` / `NUMERIC(5, 2)` / `NUMERIC(3, 2)`；
- `test_foreign_key_renders_restrict_and_logical_target`：渲染文本里出现
  `ON DELETE RESTRICT ON UPDATE RESTRICT`，且**不出现**物理月份后缀。

### 3.3 门禁

| 门禁 | 要求 | 实测 |
|---|---|---|
| `pytest tests/unit/test_models.py -q` | 全绿 | ✅ 196 passed，exit 0 |
| `pytest -q` | 基线不变红 | ✅ 669 passed, 8 skipped，exit 0（既有 473 + 8 skip 原样保留） |
| `ruff check . --no-cache` | All checks passed! | ✅ exit 0 |
| `mypy src` | Success（strict） | ✅ `Success: no issues found in 51 source files` |
| `lint-imports --config .importlinter --no-cache` | 4 kept, 0 broken | ✅ exit 0 |

其它自检：无 `sleep`（用例内零等待）；`git status` 交付面仅本任务两个文件（+ 既有
`.sdd-tools.py`）；未 `git commit`。

---

## 4. 偏离工单之处（逐条 + 理由）

### 偏离 1：`Integer(unsigned=True)` → `Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")`

- **工单原文**：`int unsigned` 用 `Integer(unsigned=True)`；「若该参数在 SQLAlchemy 2.0.54 上
  行为不符（如被静默忽略），停下报告，不要静默降级」。
- **实测**：不是「被静默忽略」，而是**硬报错**。通用 `Integer` 在 2.0.54 上不接收任何参数：

  ```
  $ .venv\Scripts\python.exe -c "from sqlalchemy import Integer; Integer(unsigned=True)"
  TypeError: Integer() takes no arguments
  ```

  源码侧佐证：`unsigned` 只存在于 MySQL 方言的 `_IntegerType.__init__`
  （`sqlalchemy/dialects/mysql/types.py:75`），通用 `sqlalchemy/sql/sqltypes.py` 里
  `grep -i 'unsigned\|zerofill'` **零命中**。故工单的字面写法在本版本上无法成立。
- **采用方案**：`with_variant` —— 主类型仍声明为通用 `Integer()`，MySQL 方言下渲染
  `INTEGER UNSIGNED`，其他方言渲染 `INTEGER`。这是 SQLAlchemy 官方给「方言专属参数」的
  标准表达方式，且**达到了工单的目的**（Task 3.5 的 autogenerate 不会反复想把列改成有符号）。
- **没有做**：没有退化成 `Integer()`（那才是工单禁止的静默降级）。渲染结果由
  `test_unsigned_columns_render_integer_unsigned` 守住。
- **风险/影响面**：若控制者坚持字面写法，替代只有「直接 `mysql.INTEGER(unsigned=True)`」
  （模型层绑定 MySQL 方言），或接受丢失 UNSIGNED。二者我都不认为更好，故保留 `with_variant`。

### 偏离 2：`DateTime()` → `DateTime().with_variant(mysql.DATETIME(fsp=3), "mysql")`

- **工单原文**：`datetime(3)` 用 `DateTime()`（**MUST NOT** `timezone=True`）。
- **问题**：工单对 `unsigned` 的检查口径在这里同样成立但方向相反——`DateTime()` **不报错，
  却静默丢精度**：通用 `DateTime()` 在 MySQL 上渲染 `DATETIME`（fsp=0），而 DDL 明确写的是
  `datetime(3)`，`er.md` §6 通用约定也写明「时间 `datetime(3)` 毫秒精度」。
  而工单第 13 行同时规定 `deploy/sql/ddl/*.sql` 是**列定义的唯一权威**。
- **采用方案**：主类型仍是 `DateTime()`、仍**无时区**（`timezone=True` 的禁令严格遵守，
  并有 `test_datetime_columns_are_not_timezone_aware` 守住），仅给 MySQL 方言补 `fsp=3`，
  渲染出 DDL 要求的 `DATETIME(3)`。这样：① 与 DDL 一致；② Task 3.5 的 autogenerate
  不会生成一条把 `datetime(3)` 改成 `DATETIME`（丢毫秒）的 `alter_column`；
  ③ Python 侧可见类型仍是 `DateTime`（比对器读 `column.type` 得到的就是 `DateTime` 实例）。
- **若控制者裁定必须字面照抄**：把 `_datetime_ms()` 改成 `return DateTime()` 即可（一行），
  代价是模型与 DDL 在 fsp 上不一致、autogenerate 可能反复生成改列语句并**真的丢毫秒精度**。
  我不建议，故登记为待裁定项。

### 非偏离、但需要控制者知道的取舍

1. **`Boolean()` 渲染 `BOOL`**：MySQL 里 `BOOL` 就是 `tinyint(1)` 的同义词，DDL 侧写的
   `tinyint(1)`；`information_schema` 两侧都归一为 `tinyint(1)`。
2. **`Numeric(3,2)` 渲染 `NUMERIC(3, 2)`**：MySQL 里 `NUMERIC` 与 `DECIMAL` 同义
   （DDL 写 `decimal(3,2)`）。工单指定的就是 `Numeric`，未自创。
3. **列/表 COMMENT 未镜像**：工单的逐列清单与用例清单都没有要求 comment；DDL 里的中文
   COMMENT 仍是唯一权威文档。若 Task 3.6 的比对维度含 comment，需另开任务补齐
   （本任务未做，登记在 §5）。
4. **`JsonValue` 别名被定义但未被列标注直接引用**：工单要求「用 `type JsonValue = ...`
   这一处别名，各列按语义收窄」，故各列写的是收窄后的 `dict[str, Any]` / `list[Any]`，
   别名作为值域文档保留。若控制者认为这属于死代码，可删（不影响任何断言）。
5. **未跑 `ruff format`**：不是工单门禁；且实测既有文件也非 format-clean
   （`src/aicore/core/logging.py`、`tests/repository/test_ddl_matches_er.py` 都会被
   重排，其中还会生成超过 100 列的行、与 `ruff check` 的 E501 冲突），故**不动**，
   手工排版以 `ruff check` 为准。
6. **主键未在 `__table_args__` 里重复声明**：遵守工单；用「主键恰 1 列」的断言等价覆盖
   （重复声明 `PrimaryKeyConstraint` 会让该断言变红）。

---

## 5. 我没做到的事（诚实登记）

1. **没连真实 MySQL**：本任务按要求不需要连库，验证只到「MySQL 方言编译」这一层
   （`CreateTable(...).compile(dialect=mysql.dialect())`）。真库上的结构一致性是 Task 3.1 的
   成果（已实测 9 表 / 4 外键 / 索引逐项核对），我**没有**再跑一遍真库校验。
2. **没验证 Alembic autogenerate 收敛**：那是 Task 3.5 的交付物。我只提供了必要条件
   （模型渲染文本与 DDL 一致），**没有**跑 `alembic revision --autogenerate` 去证明
   「不生成多余 alter」。特别是 §4 的偏离 2 是否真的消除 fsp 抖动，只有 3.5 实测才能定论。
3. **没镜像列/表 COMMENT**（见 §4.3）。若 3.6 的 ModelSource 比对 comment，会呈现差异。
4. **没有为「分片表的物理约束名带月份」写模型侧断言**：我只断言了「模型里的外键名
   *不含* 月份后缀」，物理名拼接的正确性归 Task 3.3 的建表流程与 Task 3.1 的真库实测。
5. **没有做类型映射的「反向完备性」检查**：即「DDL 里出现的每一种类型都被映射」。
   我是逐列对照 DDL 写的（80 列全覆盖），但没有写一个自动扫描 `deploy/sql/ddl/*.sql`
   里类型集合与模型类型集合对照的用例——那属于 Task 3.6 的比对器职责，重复实现它会
   产生第二套解析逻辑。
6. **工单基线数字与实测不符**（工单 453 passed / 实测 473 passed，见 §2.2）。我按实测
   数字验收「不变红」，没有去追查这 20 条差异的来源。
7. **`json` 列的标注是「按语义收窄」的人工判断**（依据 openapi 的数组/对象形态），
    DDL 本身不区分 JSON 数组与对象；若某列将来真写入另一种形态，标注会过于乐观
   （运行期不会有约束，MySQL JSON 列不校验形态）。
