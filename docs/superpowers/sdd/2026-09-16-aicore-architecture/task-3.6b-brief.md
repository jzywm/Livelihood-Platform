### Task 3.6b: `test_ddl_matches_er.py` 改用共享层 + 三方向阴性用例（步骤级工单）

**为什么必须做**：Task 3.6 的价值全在"一致性检查本身可信"。但现在**同一件事有两份解析实现**
（`tests/repository/test_ddl_matches_er.py` 的本地解析器 + `src/aicore/repository/schema.py`），
它们的漂移表现是：`test_ddl_matches_er.py` 绿、`compare_schema.py` 红（或反之）——
**两个都叫"一致性检查"的工具互相矛盾**，没人知道该信谁。
Task 3.6 的工单原文要求「`test_ddl_matches_er.py` MUST 删除自己的解析实现、改为调用共享层」。

**Worktree**：`D:\progrom\.worktrees\aicore-architecture`，服务根 `services/aicore/`。
**Python**：`.venv\Scripts\python.exe`（3.14.6）。**MUST NOT `pip install`**。
**编码**：UTF-8 无 BOM；MUST NOT 用 PowerShell `Set-Content`/`Out-File` 写含中文或反斜杠路径的文件。

**Files:**
- Modify: `tests/repository/test_ddl_matches_er.py`（现 1014 行）
- Create: `tests/repository/test_schema_consistency.py`（三方向阴性用例）

**MUST 先读**：
- `src/aicore/repository/schema.py`（**共享层**：`ColumnSpec` / `TableSpec` / `parse_ddl` /
  `parse_ddl_directory` / `parse_er_md` / `from_metadata` / `from_information_schema` / `diff` /
  `normalize_type` / `normalize_table_name` / `strip_sql_comments` / `load_metadata` / `SchemaParseError`）
- `tests/repository/test_schema.py`（共享层已有的 36 条用例，**不要重复它已覆盖的东西**）
- `scripts/compare_schema.py`（CLI 门禁，已可跑通四源）
- `docs/superpowers/specs/2026-09-16-aicore-architecture-design.md` **§5.6**（三源交叉校验的图与"任一条边不一致即失败"）

---

#### 第一部分：重构（**行为 MUST 不变**）

`test_ddl_matches_er.py` 的**本地解析器**（下列符号）MUST 删除并改为调用共享层：

```
Column / DdlTable / ErFormatError            -> schema.ColumnSpec / schema.TableSpec / schema.SchemaParseError
_iter_er_rows / parse_er_tables              -> schema.parse_er_md
_normalize_type                              -> schema.normalize_type
_parse_enum_values                           -> 共享层内部已有；如需可自行小工具
_split_markdown_row / _strip_outer_empty / _is_separator_row  -> 共享层已有（如未导出可加下划线函数调用）
_split_top_level / parse_ddl_columns / parse_ddl_tables      -> schema.parse_ddl
normalize_logical_name                       -> schema.normalize_table_name
strip_sql_comments                           -> schema.strip_sql_comments
parse_all_ddl_tables                         -> schema.parse_ddl_directory
parse_er_defaults                            -> 见下（**er.md 的「默认」列在共享层未导出**）
diff_columns                                 -> schema.diff（注意：语义不同，见下）
```

**必须保留（这些是本文件独有的、共享层不管的东西）**：
- `er.md` 的「**默认**」列解析（`parse_er_defaults`）：时间列默认值口径的断言依赖它。
  共享层的 `ColumnSpec` 不含默认值——**MUST NOT** 为此改共享层的 `ColumnSpec`（那会让四源比对多一个
  只有两源表达得了的维度）。做法：在本文件里**只保留这一件**局部解析（它只读 `er.md` 的「默认」列，
  与共享层不重叠），并在注释里写明"这是本文件唯一的局部解析，理由是 ColumnSpec 不承载默认值"。
- `DDL_ENUM_TO_OPENAPI` / `OPENAPI_ENUM_SPOT_CHECK` 及其接线自检（共享层不管 `openapi.yaml`）。
- 中文注释断言（`COMMENT_COUNT_RE` / `TABLE_CN_COMMENT_RE` / `COLUMN_COMMENT_RE` / `COLUMN_CN_COMMENT_RE`）
  与 `split_column_clauses` / `collect_column_clauses`（它们是**注释维度的检查**，共享层不比注释）。
  可保留在本地，但 MUST 在模块 docstring 里说明"这是本文件独有的注释维度检查"。
- `first_create_table_block` / `read_ddl` / `ddl_file` / `collect_index_names`（文本级检查用）。
- 所有 `test_*` 函数的**断言语义 MUST 保持不变**；只换底层解析来源。

**判据（MUST 自证）**：重构前后，`pytest tests/repository/test_ddl_matches_er.py` 的**通过条数相同**，
且**没有任何用例名变化**。请把重构前的计数与用例名清单先跑出来记在报告里，重构后再跑一次对照。

**注意 `Column`/`TableSpec` 的接口差异**（会影响到断言改写）：
- 共享层的 `TableSpec.columns` 是 **tuple**（不是 list），且 `TableSpec` 有 `column_names()`；
- `ColumnSpec` 字段是 `name/type/nullable/enum_values`，与本地 `Column` 的 `name/type/nullable` 兼容；
- `schema.diff(a, b)` 的返回是**人可读字符串清单**，而本地 `diff_columns` 返回的也是清单但格式不同。
  逐列比对的断言可以直接用 `schema.diff` 的空/非空，**但若某条用例断言了差异消息的具体措辞，
  MUST 调整为该消息的新措辞**（`schema.diff` 的措辞已在 `test_schema.py` 里被钉住）。

#### 第二部分：三方向阴性用例（**spec §5.9 第 2 条的硬要求**）

新建 `tests/repository/test_schema_consistency.py`，必须包含**三个方向各自独立**的阴性证据。
**MUST NOT 改动仓库里的真实源文件**（改真实文件再还原是危险做法，且与并发跑测试冲突）——
一律**在内存里改文本或临时 MetaData**：

| 方向 | 做法（内存内） | 断言 |
|---|---|---|
| ① 改 DDL | 读某个 `.sql` 文本，把某列类型改成别的（如 `varchar(32)`→`varchar(64)`），`schema.parse_ddl` 后与 `er.md` 比 | `diff != []`，且清单**点名该表该列**、且含"期望 vs 实际"两个值 |
| ② 改 `er.md` | 读 `er.md` 文本，把某列的「空」从 `NO` 改成 `YES`，`schema.parse_er_md` 后与 DDL 比 | `diff != []`，且清单含"可空性" |
| ③ 改模型 | 用**临时 `MetaData`**（从 `Base.metadata` 深拷贝或新建同结构表）改某列 `nullable`/类型，`from_metadata` 后与 DDL 比 | `diff != []`，且清单点名该列 |

**额外 MUST 有（防"看着严、其实是空的"）**：
- **正常态对照**：三个方向各自的"未改动"版本 `diff == []`（证明上面的红是改动引起的，不是本来就红）；
- **非空下限**：断言解析出的表数 = 9（三个方向都要，防解析塌了导致"两边都空、彼此一致"）；
- **`compare_schema.py` 的退出码**：
  - 正常态 `main([])` 返回 `0`；
  - `--with-mysql` 在**口令为空**时返回 `2`（本机无凭据场景；用 `monkeypatch.delenv` 清掉两个变量）；
  - `--with-mysql` 指向不存在的库时返回 `2`（连不上 MUST 非 0，不得静默降级成"两源通过"）。
  用 `compare_schema.main([...])` 直接调（脚本已在 `sys.path` 上插了 `src`；
  测试里可用 `importlib` 从 `scripts/` 载入，或直接 `sys.path` 加 `scripts/`）。

**MUST NOT**：改动 `docs/er.md`、`docs/openapi.yaml`、`deploy/sql/ddl/**`、`src/aicore/**`。
本次只允许改/加测试文件。

---

#### 验收（自证，全部贴原始输出）

```
.venv\Scripts\python.exe -m pytest tests/repository/test_ddl_matches_er.py -q
.venv\Scripts\python.exe -m pytest tests/repository/test_schema_consistency.py -q
.venv\Scripts\python.exe -m pytest -p no:cacheprovider --no-header -m "not integration"   # 基线 773 passed, 8 skipped
.venv\Scripts\ruff.exe check . --no-cache
.venv\Scripts\mypy.exe src
.venv\Scripts\lint-imports.exe --config .importlinter --no-cache
.venv\Scripts\python.exe -m pytest --cov src/aicore --cov-report=term -m "not integration" | findstr TOTAL
```
- **并发注意**：控制者可能同时在跑别的测试。若出现与你的改动无关的失败
  （尤其 `tests/structural/test_layering.py`——它把探针写进共享源码树，并发时会互扰，属已知约束），
  先单跑确认再判断。
- 覆盖率门禁 `fail_under = 80`。
- **MUST NOT `git commit`**；报告写入
  `.superpowers/sdd/2026-09-16-aicore-architecture/task-3.6b-report.md`，含原始输出、
  **重构前后用例计数与用例名对照**、三方向阴性证据、**偏离项 + 理由**、**没做到的事**。
