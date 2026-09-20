### Task 3.6: 三源一致性自动比对（步骤级工单）

> **本组最值钱的一项**（spec §5.6 原话）。tasks 原文只要求「DDL ↔ `er.md`」**两方**比对，
> 那样**模型层写错了照样漏检**——而模型才是业务代码真正使用的东西。
> 三源之后，「文档改了代码没改」「代码改了文档没改」「模型与 DDL 走偏」三类全部会被抓到。

**Worktree**：`D:\progrom\.worktrees\aicore-architecture`，服务根 `services/aicore/`。
**Python**：`.venv\Scripts\python.exe`（3.14.6）。**MUST NOT `pip install`**。
**编码**：UTF-8 无 BOM；MUST NOT 用 PowerShell `Set-Content`/`Out-File` 写含中文的文件。

**Files:**
- Create: `scripts/compare_schema.py`
- Create: `src/aicore/repository/schema.py`（**共享解析与归一化层**，见下"为什么"）
- Modify: `tests/repository/test_ddl_matches_er.py`（改为调用共享层，**MUST NOT 保留第二份解析实现**）
- Modify: `scripts/apply_ddl.py`（渲染函数改 import `repository/sharding.py`，见"协作注意"）
- Create: `tests/repository/test_schema_consistency.py`

**权威依据（MUST 先读）**：
- spec **§5.6**（三源交叉校验的图与"任一条边不一致即失败"；无需数据库即可跑通两源；有 MySQL 时叠加 `information_schema`）、**§5.5**（DDL 与 Alembic 分工：**纯 SQL DDL 是权威定义**）、**§5.9**（本组验收第 2 条：**三个方向各验一次**）
- `services/aicore/docs/er.md` **§6**（数据字典：9 张表 6 列口径）、**§5.2**（分片矩阵）、**§5.4**（ID 与主键策略）
- `deploy/sql/ddl/**`（Task 3.1 交付，列定义已实测干净）

---

#### 为什么新增 `src/aicore/repository/schema.py`（**这是本工单的架构决策，理由必须落地**）

Task 3.1 已在 `tests/repository/test_ddl_matches_er.py` 里写了 DDL/`er.md` 两套解析器。
若 Task 3.6 再写一套，**同一件事会有两份实现**，而它们的漂移表现是：
`test_ddl_matches_er.py` 绿、`compare_schema.py` 红（或反之）——**两个都叫"一致性检查"的工具互相矛盾**，
是最坏的一类故障（没人知道该信谁）。

故：**解析与归一化的唯一实现放在 `src/aicore/repository/schema.py`**，两边都 import 它。
`tests/repository/test_ddl_matches_er.py` MUST 删除自己的解析实现、改为调用共享层
（断言与用例名可以保留）。

**分层检查影响（已核对，MUST 遵守）**：`repository` 层 MUST NOT import `service`、`core` 不得 import 业务层。
`schema.py` 只允许 import stdlib + `sqlalchemy`；**MUST NOT** import `aicore.core.*` 里的配置/日志
（避免把"纯文本解析"绑到配置上）。`scripts/compare_schema.py` 是**脚本**（不在 `src/` 下，
不受 import-linter 的包契约约束），但 MUST 只 import stdlib + `aicore.repository.schema`。

#### `repository/schema.py` 交付接口

```python
MAX_TABLE_NAME_LEN: Final[int]
@dataclass(frozen=True)
class ColumnSpec:
    name: str
    type: str          # 归一化后（见下"类型归一化"）
    nullable: bool
    enum_values: tuple[str, ...] | None = None   # 非枚举列为 None

@dataclass(frozen=True)
class TableSpec:
    name: str          # **逻辑名**（分片表的物理名已归一化）
    columns: tuple[ColumnSpec, ...]

def normalize_table_name(physical: str) -> str          # `ai_task_202601` -> `ai_task`
def logical_table_names() -> frozenset[str]             # 9 张
def is_sharded(logical: str) -> bool

def parse_ddl(text: str, *, month: str) -> dict[str, TableSpec]
def parse_ddl_directory(ddl_dir: Path, *, month: str) -> dict[str, TableSpec]
def parse_er_md(text: str) -> dict[str, TableSpec]
def from_metadata(metadata: MetaData) -> dict[str, TableSpec]
def from_information_schema(conn: Connection, database: str) -> dict[str, TableSpec]
def diff(a: Mapping[str, TableSpec], b: Mapping[str, TableSpec]) -> list[str]
```

**`parse_ddl` 的 `month` 参数为何必需**：三个 `.template.sql` 含 `{table}` / `{month}` 占位符，
必须渲染后才谈得上"与 `er.md` 逐列比对"；`month` 由调用方给（**MUST NOT** 用当前时间——
测试会随日期漂移，且这套比对与"今天是几月"无关）。

**类型归一化（MUST 双向都做，且 MUST 可解释）**：
四个来源的类型文本长得不一样，例如同一列：
| 来源 | 文本 |
|---|---|
| DDL | `varchar(32)` / `int unsigned` / `datetime(3)` / `decimal(3,2)` |
| `er.md` | `varchar(32)` / `int UNSIGNED` / `datetime(3)` / `decimal(3,2)` |
| SQLAlchemy 元数据 | `VARCHAR(32)` / `INTEGER UNSIGNED`? / `DATETIME(3)` / `DECIMAL(3, 2)` |
| `information_schema` | `varchar` + `CHARACTER_MAXIMUM_LENGTH=32` / `int unsigned` / `datetime` + `DATETIME_PRECISION=3` / `decimal` + `NUMERIC_PRECISION/NUMERIC_SCALE` |

> **`from_metadata` MUST 用 MySQL 方言编译类型，不能只读 `str(column.type)`**（Task 3.2 的实测结论）：
> `int unsigned` 与 `datetime(3)` 在模型里是用 `with_variant(..., "mysql")` 表达的
> —— 通用 `Integer` 在 SQLAlchemy 2.0.54 上**不接收 `unsigned` 参数**（`TypeError: Integer() takes no arguments`），
> 而通用 `DateTime()` 在 MySQL 上会渲染成 `DATETIME`（**丢毫秒**，与 DDL 的 `datetime(3)` 不符）。
> 故本任务取类型文本时 MUST 走
> `column.type.compile(dialect=mysql.dialect())`（或等价方式），
> 否则会得到 `INTEGER` / `DATETIME` 而与 DDL 的 `int unsigned` / `datetime(3)` 假性不等——
> **假性不等的下一步就是有人把这条检查关掉**，那是最坏结局。
> 对应证据：`tests/unit/test_models.py::test_unsigned_columns_render_integer_unsigned` 与
> `::test_datetime_columns_render_millisecond_precision`。

归一化 MUST 压到**同一个规范形**（建议：小写、去多余空白、`decimal(3, 2)` → `decimal(3,2)`），
并 MUST 在 `schema.py` 的 docstring 里给出**完整的映射表**（每类类型 ↓ 规范形）。
**枚举列特殊**：SQLAlchemy 的 `Enum(...)` 在元数据里是 `VARCHAR(n)`/`ENUM(...)` 视方言而定，
`information_schema` 侧是 `enum('A','B')` 形态的 `COLUMN_TYPE`——**MUST 单独处理并给出枚举值元组**，
MUST NOT 让枚举列在某一源里退化成 `varchar(N)` 而与另两源"不等"（那会让比对永远红，
然后有人会把这条检查关掉——那是最坏结局）。

**`diff` 的输出 MUST 是人可读清单**（哪张表 / 哪个字段 / 期望 vs 实际），
MUST NOT 退化成 `a != b` 一句话。差异分类至少区分：
① 表集合差异（仅 A 有 / 仅 B 有）② 列集合差异 ③ 列顺序差异
④ 类型差异 ⑤ 可空性差异 ⑥ 枚举值差异。

#### `scripts/compare_schema.py`

```
用法：
  python scripts/compare_schema.py                # 两源（DDL ↔ er.md）+ 两源（DDL ↔ 模型）
  python scripts/compare_schema.py --with-mysql    # 叠加 information_schema 第四路
  python scripts/compare_schema.py --month 202601  # 渲染模板用的月（缺省取一个固定值，MUST NOT 取当前月）
```
- **有 MySQL 时跑四路、无则跑两路并 `print` 一句明确说明"未校验真实库结构"**（spec §5.6）；
- 退出码：全部一致 0、任一不一致非 0（**可作 CI 门禁**）；
- `--with-mysql` 连不上时 MUST 用**非 0 退出码 + 明确说明**，MUST NOT 静默降级成"两源通过"；
- 口令从环境变量（`AICORE_MYSQL_*`）取，**MUST NOT** 硬编码、**MUST NOT** 打印；
- 逐条打印比对结论（哪两源、多少张表、是否一致），不一致时打印完整差异清单。

#### 用例 `tests/repository/test_schema_consistency.py`

**正常态**：
1. `parse_ddl_directory` / `parse_er_md` / `from_metadata` 三者对**全部 9 张表**两两一致
   （`diff` 返回空列表），且 MUST 断言**表数 = 9**（非空下限，防解析塌了静默全绿）。
2. `from_metadata` 覆盖 9 个模型（从 `repository/models.py` 的 `Base.metadata` 取）。

**三个方向的阴性用例（spec §5.9 第 2 条的硬要求，缺一即返工）**——
每个方向 MUST 用**临时副本 + 单边改动**验证"改一侧就红"，**MUST NOT** 改动仓库里的真实文件
（改真实文件再还原是危险做法；MUST 在 `tmp_path` 下造副本，或在内存里改文本后传给解析器）：

| 方向 | 做法 | 断言 |
|---|---|---|
| ① 改 DDL | 造一份 DDL 文本副本，把某列类型从 `varchar(32)` 改成 `varchar(64)` | `diff(ddl_variant, er_md) != []` 且差异清单**点名**该表该列 |
| ② 改 `er.md` | 造一份 `er.md` 文本副本，把某列「空」从 `NO` 改成 `YES` | `diff(ddl, er_variant) != []` 且差异清单点名"可空性" |
| ③ 改模型 | 用一个**临时 `MetaData`**（在同表同列上改 `nullable` 或类型）调 `from_metadata` | `diff(ddl, metadata_variant) != []` 且差异清单点名该列 |

三方向 MUST **各自独立**（不能只验一个方向就宣称"三源交叉有效"），
且 MUST 断言差异清单里出现**期望与实际**两个值（防止 `diff` 退化成布尔）。

**第四路（`@pytest.mark.integration`，默认不跑；连不上 MUST `pytest.skip` 并说明）**：
4. 在 `aicore_test` 上执行 `apply_ddl` 建出演练月的结构 → `from_information_schema(...)`
   与 DDL/`er.md`/元数据三者比对一致；末尾清理自己建的分片表。

**契约注意**：`scripts/` 不在 `src/` 下，`mypy`（`files = ["src"]`）与 import-linter **都不会覆盖它**。
故 MUST 在报告里**如实说明**该脚本未被 mypy 检查；并且 MUST 在脚本内加 `from __future__ import annotations`
与完整类型标注（人工可读的强类型），不要因为"工具不查"就放弃标注。

#### 协作注意（避免与 Task 3.3 撞车）

Task 3.3 会把模板渲染逻辑落到 `repository/sharding.py`，并要求 `scripts/apply_ddl.py` 改为 import 它。
**本任务 MUST NOT 重复渲染逻辑**：`parse_ddl` / `parse_ddl_directory` 需要渲染时，
MUST 复用 `repository/sharding.py` 的函数（若 Task 3.3 尚未落地而你先做，
MUST **停下报告**，不要自己再写一份渲染）。

---

#### 验收（自证，全部贴原始输出）

```
.venv\Scripts\python.exe -m pytest tests/repository/test_schema_consistency.py -q
.venv\Scripts\python.exe -m pytest tests/repository -q                   # 3.1 的用例必须仍绿
.venv\Scripts\python.exe scripts\compare_schema.py                        # 两源，贴完整输出
.venv\Scripts\python.exe scripts\compare_schema.py --with-mysql           # 四源，贴完整输出
.venv\Scripts\python.exe -m pytest -q                                     # 全量基线不得变红
.venv\Scripts\ruff.exe check . --no-cache
.venv\Scripts\mypy.exe src
.venv\Scripts\lint-imports.exe --config .importlinter --no-cache
```
- **MUST NOT `git commit`**；报告写入 `.superpowers/sdd/2026-09-16-aicore-architecture/task-3.6-report.md`，
  含原始输出、**三个方向各自的阴性证据**、逐项验收结论、**偏离项 + 理由**、**没做到的事**。
