# Task 3.6b 报告：`test_ddl_matches_er.py` 改用共享层 + 三方向阴性用例

- **Worktree**：`D:\progrom\.worktrees\aicore-architecture`，服务根 `services/aicore/`
- **Python**：`.venv\Scripts\python.exe`（3.14.6）；**MUST NOT `pip install`**（本次未安装任何东西）
- **只改/加测试文件**：`tests/repository/test_ddl_matches_er.py`（改）、
  `tests/repository/test_schema_consistency.py`（新增）。**未**改 `src/aicore/**`、`docs/er.md`、
  `docs/openapi.yaml`、`deploy/sql/ddl/**`；**未** `git commit`；测试内**无 `sleep`**。
- **探针脚本用量**：**0 个**（所有探查都用一次性 `python -c` 内联命令完成，不落盘）。

---

## 一、重构前的用例计数与用例名清单

命令：

```
.venv\Scripts\python.exe -m pytest tests/repository/test_ddl_matches_er.py -q -p no:cacheprovider --no-header
```

原始输出（重构前）：

```
.............................................................            [100%]
```

（`addopts` 已含一个 `-q`，再加 `-q` 后 pytest 不打印摘要行；故另跑一次不带重复 `-q` 取计数）

```
61 passed
```

用例名清单（`--collect-only` 逐条，共 **61** 条）：

```
tests/repository/test_ddl_matches_er.py::test_er_md_parses_all_nine_tables
tests/repository/test_ddl_matches_er.py::test_ddl_directory_matches_brief_manifest
tests/repository/test_ddl_matches_er.py::test_ddl_column_order_and_types_match_er
tests/repository/test_ddl_matches_er.py::test_ddl_enums_match_er_enums
tests/repository/test_ddl_matches_er.py::test_enum_column_count_is_not_vacuous
tests/repository/test_ddl_matches_er.py::test_timestamp_defaults_match_er_notes
tests/repository/test_ddl_matches_er.py::test_openapi_has_enough_enum_lines
tests/repository/test_ddl_matches_er.py::test_enum_wiring_is_self_consistent
tests/repository/test_ddl_matches_er.py::test_every_er_enum_column_is_wired_to_openapi
tests/repository/test_ddl_matches_er.py::test_ddl_enum_matches_openapi_enum[ai_task.status]
tests/repository/test_ddl_matches_er.py::test_ddl_enum_matches_openapi_enum[ai_task.type]
tests/repository/test_ddl_matches_er.py::test_ddl_enum_matches_openapi_enum[kitchen_anomaly.confidence_level]
tests/repository/test_ddl_matches_er.py::test_ddl_enum_matches_openapi_enum[kitchen_anomaly.status]
tests/repository/test_ddl_matches_er.py::test_ddl_enum_matches_openapi_enum[ocr_result.validity]
tests/repository/test_ddl_matches_er.py::test_ddl_enum_matches_openapi_enum[review_verdict.action]
tests/repository/test_ddl_matches_er.py::test_ddl_enum_matches_openapi_enum[risk_predict_result.risk_level]
tests/repository/test_ddl_matches_er.py::test_ddl_enum_matches_openapi_enum[vision_marker.level]
tests/repository/test_ddl_matches_er.py::test_ddl_enum_matches_openapi_enum[vision_review.biz_type]
tests/repository/test_ddl_matches_er.py::test_ddl_enum_matches_openapi_enum[vision_review.confidence_level]
tests/repository/test_ddl_matches_er.py::test_ddl_enum_matches_openapi_enum[vision_review.status]
tests/repository/test_ddl_matches_er.py::test_openapi_enum_values_match_spot_check[schemas.ConfidenceLevel.enum]
tests/repository/test_ddl_matches_er.py::test_openapi_enum_values_match_spot_check[schemas.KitchenAnomalyStatus.enum]
tests/repository/test_ddl_matches_er.py::test_openapi_enum_values_match_spot_check[properties.validity.enum]
tests/repository/test_ddl_matches_er.py::test_openapi_enum_values_match_spot_check[schemas.RiskLevel.enum]
tests/repository/test_ddl_matches_er.py::test_openapi_enum_values_match_spot_check[schemas.TaskStatus.enum]
tests/repository/test_ddl_matches_er.py::test_openapi_enum_values_match_spot_check[schemas.TaskType.enum]
tests/repository/test_ddl_matches_er.py::test_openapi_enum_values_match_spot_check[schemas.VerdictAction.enum]
tests/repository/test_ddl_matches_er.py::test_openapi_enum_values_match_spot_check[schemas.VisionBizType.enum]
tests/repository/test_ddl_matches_er.py::test_openapi_enum_values_match_spot_check[schemas.VisionReviewStatus.enum]
tests/repository/test_ddl_matches_er.py::test_template_contains_both_placeholders[ai_task]
tests/repository/test_ddl_matches_er.py::test_template_contains_both_placeholders[ocr_correction]
tests/repository/test_ddl_matches_er.py::test_template_contains_both_placeholders[ocr_result]
tests/repository/test_ddl_matches_er.py::test_correction_template_has_same_month_physical_foreign_key
tests/repository/test_ddl_matches_er.py::test_ddl_constraint_names_all_carry_month
tests/repository/test_ddl_matches_er.py::test_rendered_template_has_no_placeholder_left[ai_task]
tests/repository/test_ddl_matches_er.py::test_rendered_template_has_no_placeholder_left[ocr_correction]
tests/repository/test_ddl_matches_er.py::test_rendered_template_has_no_placeholder_left[ocr_result]
tests/repository/test_ddl_matches_er.py::test_sharded_templates_are_not_executable_verbatim
tests/repository/test_ddl_matches_er.py::test_ddl_does_not_switch_database
tests/repository/test_ddl_matches_er.py::test_every_create_table_is_idempotent
tests/repository/test_ddl_matches_er.py::test_create_database_is_idempotent
tests/repository/test_ddl_matches_er.py::test_ddl_declares_all_nine_tables
tests/repository/test_ddl_matches_er.py::test_common_ddl_conventions[ai_task]
tests/repository/test_ddl_matches_er.py::test_common_ddl_conventions[kitchen_anomaly]
tests/repository/test_ddl_matches_er.py::test_common_ddl_conventions[ocr_correction]
tests/repository/test_ddl_matches_er.py::test_common_ddl_conventions[ocr_result]
tests/repository/test_ddl_matches_er.py::test_common_ddl_conventions[review_verdict]
tests/repository/test_ddl_matches_er.py::test_common_ddl_conventions[risk_predict_result]
tests/repository/test_ddl_matches_er.py::test_common_ddl_conventions[vision_marker]
tests/repository/test_ddl_matches_er.py::test_common_ddl_conventions[vision_qa_log]
tests/repository/test_ddl_matches_er.py::test_common_ddl_conventions[vision_review]
tests/repository/test_ddl_matches_er.py::test_every_column_and_table_has_chinese_comment[ai_task]
tests/repository/test_ddl_matches_er.py::test_every_column_and_table_has_chinese_comment[kitchen_anomaly]
tests/repository/test_ddl_matches_er.py::test_every_column_and_table_has_chinese_comment[ocr_correction]
tests/repository/test_ddl_matches_er.py::test_every_column_and_table_has_chinese_comment[ocr_result]
tests/repository/test_ddl_matches_er.py::test_every_column_and_table_has_chinese_comment[review_verdict]
tests/repository/test_ddl_matches_er.py::test_every_column_and_table_has_chinese_comment[risk_predict_result]
tests/repository/test_ddl_matches_er.py::test_every_column_and_table_has_chinese_comment[vision_marker]
tests/repository/test_ddl_matches_er.py::test_every_column_and_table_has_chinese_comment[vision_qa_log]
tests/repository/test_ddl_matches_er.py::test_every_column_and_table_has_chinese_comment[vision_review]
tests/repository/test_ddl_matches_er.py::test_ddl_declares_physical_foreign_keys_with_restrict
```

## 二、重构后的对照（"行为不变"的判据）

命令（重构后，同样先 `--collect-only`）：

```
.venv\Scripts\python.exe -m pytest tests/repository/test_ddl_matches_er.py -p no:cacheprovider --no-header --collect-only
```

集合比对（把重构前的清单存成基线文件后用 `Compare-Object` 逐条比对，原始输出）：

```
baseline=61 now=61
IDENTICAL: 用例名清单逐条一致
```

**结论：61 条 → 61 条，用例名逐条一致（无新增、无删除、无改名）。**

运行结果（重构后）：

```
.............................................................            [100%]
61 passed in 6.31s
```

文件体量：`test_ddl_matches_er.py` **1014 行 → 714 行**（`git diff --stat`：`221 insertions(+), 403 deletions(-)`），
新增 `test_schema_consistency.py` **269 行**。

---

## 三、重构内容：删了什么、保留了什么

### 3.1 已删除的本地解析/渲染实现（→ 一律改调共享层）

| 被删除的本地符号 | 现在调用 |
|---|---|
| `Column` | `schema.ColumnSpec` |
| `DdlTable`（含 `create_body`） | `schema.TableSpec`；枚举值改从 `ColumnSpec.enum_values` 取 |
| `ErFormatError` | `schema.SchemaParseError` |
| `_iter_er_rows` / `parse_er_tables` | `schema.parse_er_md` |
| `_normalize_type` | `schema.normalize_type` |
| `_parse_enum_values` | 无需替代（共享层已把枚举值解进 `ColumnSpec.enum_values`） |
| `_split_markdown_row` / `_strip_outer_empty` / `_is_separator_row` | `schema._*`（共享层未导出公开名，按工单"如未导出可加下划线函数调用"） |
| `_split_top_level` | `schema._split_top_level`（仅 `split_column_clauses` 的顶层切分用） |
| `parse_ddl_columns` / `parse_ddl_tables` | `schema.parse_ddl` |
| `normalize_logical_name` | `schema.normalize_table_name`（该符号在原文件里**从未被调用**，属死代码） |
| `strip_sql_comments` | `schema.strip_sql_comments` |
| `parse_all_ddl_tables` | `schema.parse_ddl_directory`（经 `load_ddl_tables()` 调用点） |
| `diff_columns` | `schema.diff` |
| `render_template` | `sharding.render_shard_template`（**超出工单清单的额外去重**，见偏离项 D1） |
| `strip_sql_string_literals` | `sharding.sql_skeleton`（**超出工单清单的额外去重**，见偏离项 D1） |
| `DDL_TYPE_RE` / `ENUM_TYPE_RE` / `CREATE_TABLE_RE` / `ER_HEADING_RE` / `ER_TABLE_NAME_RE` / `MD_HEADER_CELLS` / `PHYSICAL_SUFFIX_RE` | 随其唯一使用者一并删除；判据改用共享层的 `_TYPE_RE` / `_ENUM_RE` / `_CREATE_TABLE_RE` / `_ER_HEADING_RE` / `_ER_TABLE_NAME_RE` / `ER_HEADER_CELLS` |
| `PROJECT_ROOT` | `schema.SERVICE_ROOT`（路径口径同源，见偏离项 D2） |

自证（grep 全文件，剩余命中全部带 `schema.` 前缀，即全部是共享层调用、无本地定义）：

```
Line 280:     `schema._ER_HEADING_RE` / `schema.ER_HEADER_CELLS` / `schema._split_markdown_row` /
Line 281:     `schema._strip_outer_empty` / `schema._is_separator_row` 全部取自共享层，
Line 304:         if schema._ER_HEADING_RE.match(line) is None:
Line 311:             rows.append(schema._strip_outer_empty(schema._split_markdown_row(lines[index])))
Line 316:         name_match = schema._ER_TABLE_NAME_RE.match(line)
Line 321:             if schema._is_separator_row(cells):
```

### 3.2 保留的（及理由）

- **`parse_er_defaults`（本文件唯一的局部解析）**：读 `er.md` §6 的「默认」列。
  理由写在函数 docstring 里：共享层 `ColumnSpec` 刻意只承载**四个来源都表达得了**的维度，
  默认值只有 `er.md` 与 DDL 表达得了；塞进 `ColumnSpec` 会让 `information_schema` 与模型侧
  永远缺这一维。**未**为它改共享层 `ColumnSpec`。
  其章节判定与单元格切分仍复用共享层（`_ER_HEADING_RE` / `ER_HEADER_CELLS` /
  `_split_markdown_row` / `_strip_outer_empty` / `_is_separator_row`），本函数只多做"取第 5 列"。
- **注释维度检查**（共享层只比结构、不比注释）：`CJK_RE`、`COMMENT_COUNT_RE`、
  `TABLE_CN_COMMENT_RE`、`COLUMN_COMMENT_RE`、`COLUMN_CN_COMMENT_RE`、`DDL_COLUMN_ITEM_RE`、
  `split_column_clauses`、`collect_column_clauses`，以及
  `test_every_column_and_table_has_chinese_comment`。模块 docstring 已写明"这是本文件独有的
  注释维度检查"。
- **文本级助手**：`read_ddl` / `ddl_file` / `first_create_table_block` / `collect_index_names`。
- **枚举 ↔ openapi 接线**：`DDL_ENUM_TO_OPENAPI` / `OPENAPI_ENUM_SPOT_CHECK` /
  `resolve_yaml_path` / `load_openapi` / `format_differences` / `MIN_*` 常量（共享层不管 `openapi.yaml`）。
- **`ALL_TABLES` / `SHARDED_TABLES` / `FIXED_TABLES`（按 brief 手写的清单）**：刻意**不**从
  `repository/sharding.py` 取 —— 它是 `test_ddl_directory_matches_brief_manifest` 的
  **独立期望源**，从被测实现里取清单会让该断言退化成"自己跟自己比"（已在用例 docstring 里写明）。
- 所有 `test_*` 的**断言语义未变**，只换底层解析来源；`MIN_*` 非空下限一条未删。

---

## 四、三方向阴性用例（`tests/repository/test_schema_consistency.py`，10 条）

| 用例 | 方向 | 作用 |
|---|---|---|
| `test_three_sources_are_non_vacuous` | 共同 | 非空下限：三源各解出 **9** 张表 |
| `test_ddl_side_unmutated_is_green` | ① 绿 | 未改动 DDL vs `er.md`：`diff == []` |
| `test_mutating_ddl_side_goes_red` | ① 红 | `25_vision_qa_log.sql` 的 `qa_id`：`varchar(32)`→`varchar(64)` |
| `test_er_md_side_unmutated_is_green` | ② 绿 | 未改动 `er.md` vs DDL：`diff == []` |
| `test_mutating_er_md_side_goes_red` | ② 红 | `review_verdict.reviewed_at` 的「空」：`NO`→`YES` |
| `test_metadata_side_unmutated_is_green` | ③ 绿 | 未改动元数据 vs DDL：`diff == []` |
| `test_mutating_metadata_side_goes_red` | ③ 红 | 临时 `MetaData` 的 `vision_review.confidence.nullable` 取反 |
| `test_compare_schema_returns_zero_on_the_happy_path` | CLI | `main([]) == 0`，且日志里三个源都解出 9 张表 |
| `test_compare_schema_with_mysql_without_password_is_not_zero` | CLI | 口令为空时 `main(["--with-mysql"]) == 2` |
| `test_compare_schema_with_mysql_unreachable_database_is_not_zero` | CLI | 库不存在时 `main(["--with-mysql","--database", <不存在>]) == 2` |

**MUST NOT 改真实源文件**已遵守：三个方向全部在内存里改文本 / 改临时 `MetaData`
（`Base.metadata` 深拷贝进新 `MetaData`，并用断言钉住"原件未被改动"）。

### 4.1 三方向红/绿原始输出（独立脚本打印，未落盘）

```
=== 方向 1: 改 DDL ===
未改动 diff(er, ddl) = []
替换处数 = 1 | 改动后 diff = ['表 vision_qa_log 字段 qa_id 类型不一致：左 varchar(32)，右 varchar(64)']
=== 方向 2: 改 er.md ===
未改动 diff(er, ddl) = []
目标行出现次数 = 1
改动后 diff = ['表 review_verdict 字段 reviewed_at 可空性不一致：左 YES，右 NO']
=== 方向 3: 改模型 ===
未改动 diff(ddl, meta) = []
原件未被改动: True
改动后 diff = ['表 vision_review 字段 confidence 可空性不一致：左 YES，右 NO']
```

- 方向①命中"类型不一致"，且**同时给出期望与实际两个值**（`varchar(32)` / `varchar(64)`），并点名表 + 列；
- 方向②命中"**可空性**不一致"，点名表 + 列；
- 方向③命中"可空性不一致"，点名表 + 列，且原件未被污染。

### 4.2 防"看着严、其实是空的"

- 每个方向都配**未改动对照**（`diff == []`，就在红用例的紧邻上方），证明"红"是改动引起的；
- 每个方向都断言**差异恰好 1 条**（`len(differences) == 1`），防"报一堆别的差异"冒充命中；
- 每个红用例都断言**改动确实反映到了解析结果/导出结果**上
  （`mutated[...] != original[...]`），否则本用例会变成假绿；
- 方向①的文本改动用 `subn` 并断言**替换处数 == 1**；方向②用**整行 + `count == 1`** 自检，
  避免 `er.md` 里另外两处 `reviewed_at` 被误改；
- 三个方向都断言解析出的**表数 == 9**（防"两边都空、彼此一致"）。

### 4.3 用例运行结果

```
..........                                                               [100%]
10 passed in 0.76s
```

---

## 五、验收命令的原始输出

### 5.1 `pytest tests/repository/test_ddl_matches_er.py -q`

```
.............................................................            [100%]
```

（`addopts` 已含 `-q`，重复 `-q` 不打印摘要行；补跑一次不带重复 `-q` 的同一文件：）

```
.............................................................            [100%]
61 passed in 6.31s
```

### 5.2 `pytest tests/repository/test_schema_consistency.py -q`

```
..........                                                               [100%]
```

补跑摘要：

```
..........                                                               [100%]
10 passed in 0.76s
```

### 5.3 `pytest -p no:cacheprovider --no-header -m "not integration"`

```
........................................................................ [  8%]
........................................................................ [ 17%]
........................................................................ [ 25%]
.....................sssssss............................................ [ 34%]
........................................................................ [ 43%]
........................................................................ [ 51%]
.........s.............................................................. [ 60%]
........................................................................ [ 69%]
........................................................................ [ 77%]
........................................................................ [ 86%]
........................................................................ [ 94%]
..........................................                               [100%]
826 passed, 8 skipped, 10 deselected in 18.05s
```

> **与工单基线 773 passed / 8 skipped 的差异说明（重要，别误读）**：
> 多出的 53 条**不能**算作本任务的增量。期间控制者并行跑了别的 subagent，仓库里出现了
> 其它任务新增的测试（例如 `tests/repository/test_session.py` 收集到 25 条）。
> 本任务能确证的是**逐文件的收集数**：
>
> ```
> tests/repository/test_ddl_matches_er.py: 61     ← 重构前也是 61
> tests/repository/test_schema_consistency.py: 10 ← 本次新增
> ```

### 5.4 `ruff check . --no-cache`

```
_probe_repo_paths.py:45:27: RUF100 [*] Unused `noqa` directive (non-enabled: `BLE001`)
_probe_repo_paths.py:55:27: RUF100 [*] Unused `noqa` directive (non-enabled: `BLE001`)
_probe_repo_paths.py:68:27: RUF100 [*] Unused `noqa` directive (non-enabled: `BLE001`)
_probe_repo_paths.py:80:27: RUF100 [*] Unused `noqa` directive (non-enabled: `BLE001`)
_probe_repo_paths.py:91:27: RUF100 [*] Unused `noqa` directive (non-enabled: `BLE001`)
_probe_repo_paths.py:104:27: RUF100 [*] Unused `noqa` directive (non-enabled: `BLE001`)
_probe_repo_paths.py:118:27: RUF100 [*] Unused `noqa` directive (non-enabled: `BLE001`)
_probe_repo_paths.py:133:27: RUF100 [*] Unused `noqa` directive (non-enabled: `BLE001`)
_probe_repo_paths.py:149:27: RUF100 [*] Unused `noqa` directive (non-enabled: `BLE001`)
_probe_repo_paths.py:157:27: RUF100 [*] Unused `noqa` directive (non-enabled: `BLE001`)
_probe_repo_paths.py:185:99: E501 Line too long (108 > 100)
_probe_repo_paths2.py:31:27: RUF100 [*] Unused `noqa` directive (non-enabled: `BLE001`)
_probe_repo_paths2.py:76:74: E501 Line too long (104 > 100)
_probe_repo_paths2.py:151:31: RUF100 [*] Unused `noqa` directive (non-enabled: `BLE001`)
Found 14 errors.
[*] 12 fixable with the `--fix` option.
```

> **全仓 ruff 当前是红的，但 14 条全部落在 `services/aicore/_probe_repo_paths.py` 与
> `_probe_repo_paths2.py`** —— 这两个是**并发 subagent 留在服务根目录的一次性探针脚本**
> （`git status` 里是未跟踪文件），与本次改动无关。我没有删它们（那会打断对方正在做的工作）。
> 本任务两个文件的 scoped 结果：

```
.venv\Scripts\ruff.exe check tests/repository/test_ddl_matches_er.py tests/repository/test_schema_consistency.py --no-cache
All checks passed!
```

（另：更早一次 `ruff check .` 还报过 `tests/repository/test_session.py:624 E501`，下一次再跑就消失了
—— 同样是并发任务在改文件。**这属于工单里点明的并发约束，不是本任务的缺陷。**）

### 5.5 `mypy src`

```
Success: no issues found in 52 source files
```

### 5.6 `lint-imports --config .importlinter --no-cache`

```
api 层不得直接依赖 repository / provider KEPT
service 层只可与 provider.base 交互，不得依赖具体通道实现 KEPT (1 warning)
repository / provider / port 不得反向依赖 service KEPT
core 不得依赖任何业务层 KEPT

Contracts: 4 kept, 0 broken.
```

（那条 warning 是既有的 `unmatched_ignore_imports` 提示，非本次引入。）

### 5.7 覆盖率门禁

```
TOTAL                                       1117     36    97%
Required test coverage of 80.0% reached. Total coverage: 96.78%
```

pytest 退出码 `0`，`fail_under = 80` 达标。

### 5.8 改动范围

```
git diff --stat -- services/aicore/tests/repository/test_ddl_matches_er.py
 .../aicore/tests/repository/test_ddl_matches_er.py | 624 ++++++++-------------
 1 file changed, 221 insertions(+), 403 deletions(-)
```

新增文件：`tests/repository/test_schema_consistency.py`（未跟踪，269 行）。
两个文件均为 **UTF-8 无 BOM**（首 3 字节 `34,34,34`，即 `"""`）。
`src/aicore` / `docs` / `deploy` 的改动全部来自**并发任务**（`config.py`、`session.py` 等），**没有一处是我的**。

---

## 六、偏离项 + 理由

- **D1（额外去重，超出工单清单）**：工单只要求删"本地解析器"，我把两份**本地渲染/骨架**也删了：
  `render_template` → `sharding.render_shard_template`、`strip_sql_string_literals` →
  `sharding.sql_skeleton`。理由：它们是同一 `{table}`/`{month}` 协议的**第二份实现**，
  而"同一件事两份实现会漂移"正是本次任务的判据；且 `render_shard_template` 就是
  `scripts/apply_ddl.py` 生产路径上真正会执行的渲染。
  **行为差异（已核实无害）**：共享层把 `{table}` 渲成**物理表名**
  （`ocr_correction_202601`），旧本地函数渲成逻辑名（`ocr_correction`）；受影响的两条用例
  （`test_rendered_template_has_no_placeholder_left`、`test_ddl_declares_physical_foreign_keys_with_restrict`）
  做的是花括号计数与 FK 正则匹配，均不受表名形态影响，61 条全绿不变。
- **D2（额外去重）**：`DDL_DIR` / `ER_MD` 改为取 `schema.DDL_DIR` / `schema.ER_MD`，
  `OPENAPI_YAML` 基于 `schema.SERVICE_ROOT`。理由：路径也是"同一件事的两份定义"，
  漂移表现同样是"两个工具各比各的"。取值与原 `PROJECT_ROOT` 口径完全一致（同一目录）。
- **D3（新增自检）**：`parse_er_defaults` 里加了两条**交叉自检**（表集合与共享层一致、
  每表"默认"行数 == 共享层解出的列数）。工单只要求保留这一件局部解析、未要求自检；
  加它是为了防"局部解析悄悄与共享层分叉"——分叉后本函数会张冠李戴，
  而 `test_timestamp_defaults_match_er_notes` 会变成对着错行比的假断言。
- **D4（合并两个近乎重复的收集器）**：`collect_ddl_enums` / `collect_er_enums` 合并为一个
  `collect_enums(tables: Mapping[str, schema.TableSpec])`（原两函数体只差数据来源）。
  用例名与断言均未变。
- **D5（新文件的两处选择）**：
  ① 方向②的改动目标行**写死整行**（`review_verdict.reviewed_at`）并配 `count == 1` 自检 ——
  工单未指定改哪一行；写全行是为了不与另外两处 `reviewed_at` 混淆，`count` 自检保证"改不动就报红"。
  ② 方向③**只改 `nullable` 不改类型** —— `to_metadata` 内部的 `Column._copy()` 对普通类型
  （VARCHAR / DECIMAL）**共享同一个 `TypeEngine` 实例**（只有 `Enum` 这类 SchemaEventTarget 才 copy），
  改 `column.type.length` 会**连带改到 `Base.metadata`**、污染同进程其它用例；
  `nullable` 是 Column 自身属性，改副本不碰原件（用例里有断言钉住）。
- **D6（CLI 退出码用例的凭据处理）**：`--with-mysql` 指向不存在库的那条，口令从环境取
  （`tests/conftest.py` 会用本机 `.env` 回填 `DSH_IT_MYSQL_PASSWORD`），取不到时用
  一眼看得出是占位符的 `not-a-real-password` 顶上，目的是让脚本**真的走到连接那一步**
  （留空会命中"缺口令"的提前返回，断言就退化成与上一条重复的空断言）。
  **未硬编码任何真实凭据**。
- **D7（模块级常量 `RENDER_MONTH`）**：新文件里自定 `RENDER_MONTH = "202601"` 与
  `TABLE_COUNT = 9`，没有从 `compare_schema.DEFAULT_MONTH` / `schema` 取 —— 新文件是
  "独立期望源"的角色，从被测实现取期望值会让断言退化。

---

## 七、我没做到的事（诚实登记）

1. **`ruff check .` 全仓当前不绿**，但红的 14 条全部来自**并发 subagent 的一次性探针文件**
   `services/aicore/_probe_repo_paths.py` / `_probe_repo_paths2.py`。我没有删（会打断对方工作），
   也没有替对方修。本任务两个文件 scoped ruff 全绿（原始输出见 5.4）。
   若控制者要求"全仓 ruff 必须绿"，需要先让那个 subagent 清理探针，或由控制者确认后再跑一次。
2. **工单基线 773 passed 与本次 826 passed 不可直接相减**。期间仓库里多了并发任务的测试文件
   （如 `tests/repository/test_session.py` 收集 25 条）。我只能确证逐文件收集数
   （`test_ddl_matches_er.py` 61→61 逐条同名；新增文件 10 条），**无法**把 +53 全部归因清楚。
3. **`parse_er_defaults` 仍保留一段"扫描 §6 章节 + 取第 5 列"的循环骨架**。它复用了共享层的
   判据与切分函数，但循环本身是本地写的。共享层没有导出行级 API，而工单**不允许**我改
   `src/aicore/**`，故我没有为它新增公开 API。这是"本文件唯一的局部解析"的**残余**，
   不是完全零重复。
4. **阴性用例自身的"阴性"没有做**：我没有验证"把三方向红用例里的改动去掉后它们会失败"
   （那需要临时改测试文件）。等价证据是：每个方向配了未改动对照（`diff == []`）+
   "改动必须反映到解析结果"的反假绿断言 + 独立脚本打印的红/绿原始输出（4.1 节）。
5. **`--with-mysql` 在"本机真实口令 + 真实库 `aicore_test`"下返回 0 这件事我没有验**
   （需要该库已按 DDL 建好；属集成用例范畴，不在工单要求的三条退出码里）。
   我验的是：缺口令 → `2`，库不存在/连不上 → `2`（两种都是"非 0、不静默降级"）。
6. **未做**任何 `git commit`、未碰 `src/**`、`docs/er.md`、`docs/openapi.yaml`、`deploy/sql/ddl/**`
   —— 这是遵守约束，不算"没做到"，但在此登记以示可核。
7. 中途我在工作区外建过一个临时基线清单文件（`D:\progrom\.dsh-task36b\baseline_names.txt`，
   仅含 61 条 ASCII 用例名）用于 `Compare-Object` 对照，**已删除**。本次**没有**在仓库里留下
   任何一次性探针脚本（探查全部走 `python -c` 内联命令）。
