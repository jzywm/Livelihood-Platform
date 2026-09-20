# Task 3.6 交付报告（三源/四源一致性比对）

**日期**：2026-09-18 ｜ **worktree**：`.worktrees/aicore-architecture`
**提交**：`45fb9b8`（`repository/schema.py` + 36 条用例）、
`c604dfa`（`scripts/compare_schema.py` + 3.6b 重构与三方向阴性用例）

> **本报告为补档**：第 3 组独立评审指出 `task-3.6-report.md` 缺失（只有 `task-3.6b-report.md`）。
> 本任务的控制者做的是底座与 CLI、subagent `df4ca778` 做的是 1014 行用例的重构与三方向阴性，
> 完整证据在 `progress.md` 的「Task 3.6 完成」一节与 `task-3.6b-report.md`。
> 本文件把 Task 3.6 的整体结论集中到一处，便于评审与追溯。

## 1. 执行方式（如实登记）

| 部分 | 执行者 | 产物 |
|---|---|---|
| 四源解析与归一化层 | **控制者** | `src/aicore/repository/schema.py`（`ColumnSpec` / `TableSpec` / 四个解析入口 / `diff`） |
| CLI 门禁 | **控制者** | `scripts/compare_schema.py` |
| 1014 行用例改用共享层 + 三方向阴性 | subagent `df4ca778` | `test_ddl_matches_er.py`（1014→714 行）、`test_schema_consistency.py`（10 条） |
| 三方向阴性的独立复现 | **控制者** | 见 `progress.md`（先于 subagent 的用例完成） |

**为什么底座由控制者写**：它是本组最值钱一项的核心，且与当时在跑的 Task 3.3
（只碰 `sharding.py` / `apply_ddl.py`）**无文件重叠**，属真正可并行的工作。
**代价**：底座是"自实现自验收"，已纳入第 3 组整体独立评审的必审项——**评审已复跑通过**。

## 2. 交付物

| 路径 | 说明 |
|---|---|
| `src/aicore/repository/schema.py` | 四源解析与归一化的**唯一实现处**（`parse_ddl` / `parse_ddl_directory` / `parse_er_md` / `from_metadata` / `from_information_schema` / `diff`） |
| `scripts/compare_schema.py` | CLI 门禁（两源/四源、退出码 0/1/2） |
| `tests/repository/test_schema.py` | 36 条（归一化 / 表格解析 / 元数据方言编译 / 差异清单六类各有报警证据） |
| `tests/repository/test_schema_consistency.py` | 10 条（三方向阴性 + CLI 三条退出码） |
| `tests/repository/test_ddl_matches_er.py` | 改为复用共享层（行为不变，61 条用例名逐条一致） |

## 3. 核心设计动因

**为什么必须有共享层**：Task 3.1 已在 `test_ddl_matches_er.py` 里写过 DDL 与 `er.md` 的解析。
Task 3.6 若再写一份，同一件事就有**两份实现**，漂移表现是
**`test_ddl_matches_er.py` 绿、`compare_schema.py` 红（或反之）**——
两个都叫"一致性检查"的工具互相矛盾，**没人知道该信谁**，那是最坏的一类故障。
故 `schema.py` 是唯一实现处，测试与 CLI 都 import 它。

## 4. 四源一致（控制者实测）

```
[INFO] DDL(deploy/sql/ddl)      解析到 9 张表
[INFO] er.md §6 数据字典          解析到 9 张表
[INFO] SQLAlchemy 元数据          解析到 9 张表
[ OK ] DDL vs er.md ｜ DDL vs 元数据 ｜ DDL vs information_schema(aicore_test)
[ OK ] er.md vs 元数据 ｜ er.md vs information_schema ｜ 元数据 vs information_schema
[DONE] 4 个来源两两一致（9 张表）
```

**反向（失败模式也必须验）**：
- 未传 `--with-mysql` → 打 `[WARN]` 明确说明"**真实库结构未被校验**"，不假装验过；
- 传了但**口令为空** → `exit 2` 并给可操作提示（指出该设哪个变量）；
- 指向**不存在的库** → `exit 2`（**连不上 MUST 非 0，不得静默降级成"两源通过"**）。

## 5. 三方向阴性（spec §5.9 第 2 条的硬要求）

控制者**先独立复现**（不依赖 subagent 的用例），subagent 后补成用例并加了两层防护
（"未改动时 diff 为空"的对照 + "改动必须反映到解析结果"的反假绿断言）。两边结果一致：

```
正常态对照：DDL vs er.md 0 处差异；DDL vs 元数据 0 处差异
方向① 改 DDL   : 表 vision_review 字段 review_id 类型不一致：左 varchar(64)，右 varchar(32)
方向② 改 er.md : 表 vision_review 字段 review_id 可空性不一致：左 NO，右 YES
方向③ 改模型   : 表 vision_review 字段 review_id 可空性不一致：左 NO，右 YES
```

**变异一律在内存内做、不碰真实源文件**——避免"改真实文件再还原"这种危险做法，
也避免与并发跑测试的进程冲突（本组确实存在并发：多个 subagent 同时跑测试）。

## 6. 类型归一化（这块踩过两次同一个坑）

**`normalize_type` 的判据是"只小写类型名，括号内的参数保原样"**。理由：

- 首版用整体 `.lower()`，实测**直接爆出 15 处差异**，一半是枚举值被小写：
  `er.md` 的 `enum('VALID',...)` 变成 `enum('valid',...)`，与模型侧必然不等。
  **这与 Task 3.1 修的是同一个错误**（枚举值是 SQL 字符串字面量、大小写敏感，类型名不敏感）。
- 实现用**显式扫描**（引号优先 + 深度计数）而非正则：枚举值里可能出现 `)`，
  正则 `^([^(]*)[(](.*)[)]$` 会在错的括号处断句。
- 剩余 6 处差异是**同义名未归一**（MySQL 里 `NUMERIC`≡`DECIMAL`、`BOOL`≡`tinyint(1)`、
  `INTEGER`≡`INT`）。归一时又踩一次：整串精确匹配让 `numeric(3,2)` 落空 →
  改为**取前导字母作基名、其余原样拼回**（`integer unsigned` 里的 `unsigned` 一度被吞掉）。

**`from_metadata` MUST 按 MySQL 方言编译类型**（`compile(dialect=mysql.dialect())`）：
Task 3.2 的模型用 `with_variant(..., "mysql")` 表达 `unsigned` 与 `fsp=3`，
只读 `str(column.type)` 会得到 `INTEGER` / `DATETIME`，与 DDL 的 `int unsigned` / `datetime(3)`
**假性不等**。实测对照：
```
progress    generic=INTEGER    mysql=INTEGER UNSIGNED
created_at  generic=DATETIME   mysql=DATETIME(3)
```
**假性不等的下一步往往是"有人把这条检查关掉"**，故这一步是必需的。

## 7. 门禁（控制者复跑）

```
877 passed, 8 skipped, 19 deselected   （含 3.5 的 17 条）
ruff All checks passed!
mypy Success: no issues found in 52 source files
lint-imports 4 kept, 0 broken
覆盖率 97.26%（≥80%）
验收检查表 10/10 PASS（其中第 2、3 项即本任务的核心验收）
```

## 8. 未做到 / 遗留（诚实登记）

| 项 | 说明 |
|---|---|
| `scripts/compare_schema.py` **不在 mypy 与 import-linter 覆盖内** | `mypy` 的 `files=["src"]`，脚本在 `scripts/` 下。已加完整类型标注，但**没有工具强制** |
| "阴性用例自身的阴性" | subagent 未做（未临时改测试文件验证那些阴性断言会失败）；**控制者的独立复现补上了这一层**（先于用例完成，两边结果一致） |
| `parse_er_defaults` 仍是 `test_ddl_matches_er.py` 里的局部解析 | `ColumnSpec` 刻意不承载"默认值"（不为它给共享层加一个只有两源表达得了的维度）；理由已写在注释里 |
| 列/表 COMMENT 不在比对维度内 | `er.md` 有中文 COMMENTS，但四源里只有 DDL 与 `er.md` 表达得了；`ColumnSpec` 不收 comment，故"模型与库的注释漂移"本任务抓不到。**登记为已知覆盖面缺口** |
