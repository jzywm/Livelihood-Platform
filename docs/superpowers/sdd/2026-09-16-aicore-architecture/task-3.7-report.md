# Task 3.7 报告：repository 层数据访问

**Worktree**：`D:\progrom\.worktrees\aicore-architecture`（服务根 `services/aicore/`）
**工单**：`.superpowers/sdd/2026-09-16-aicore-architecture/task-3.7-brief.md`
**Python**：`.venv\Scripts\python.exe`（3.14.6，未 `pip install` 任何东西）
**提交**：**未 `git commit`**（遵守铁律 5）

---

## 一、交付文件清单

| 文件 | 状态 | 内容 |
|---|---|---|
| `services/aicore/src/aicore/repository/base.py` | 改写（原 1 行占位） | `ShardKey`（frozen dataclass + 构造期不变式）/ `BaseRepo[ModelT]`（`physical_name`、`require_same_shard`、`_table`/`_insert`/`_select_one`/`_select_many`/`_update`/`_to_entity`）/ `cross_shard_transaction_guard` / `physical_table()`（物理表对象，带缓存）/ `entity_values()` |
| `services/aicore/src/aicore/repository/task_repo.py` | 改写 | `TaskRepo`（insert / get_by_id / list_by_account / update_status / find_by_idem_key）+ 模块级 `status_update_statement()` |
| `services/aicore/src/aicore/repository/ocr_repo.py` | 改写 | `OcrRepo`（insert / get_by_id） |
| `services/aicore/src/aicore/repository/correction_repo.py` | 改写 | `CorrectionRepo`（**只增**：insert / list_by_task） |
| `services/aicore/src/aicore/repository/verdict_repo.py` | 改写 | `VerdictRepo`（insert_review / get_review / insert_verdict / get_verdict）+ `DuplicateVerdictError` |
| `services/aicore/tests/repository/test_repos.py` | **新建** | 41 条用例（37 条默认段 + 4 条 `@pytest.mark.integration`） |

未改动（MUST NOT 碰）：`models.py`（`__tablename__` 一个字符没动）、`sharding.py`、`schema.py`、
`session.py`、`deploy/sql/**`、`tests/repository/test_ddl_matches_er.py`、`tests/unit/**`。
`git status --porcelain` 只有上述 5 个 M 与 1 个 `??`（另有他人未跟踪的 `.sdd-tools.py`）。

**探针**：2 个（工单上限 2 个），`_probe_repo_paths.py` / `_probe_repo_paths2.py`，**跑完已删除**
（`git status` 里看不到它们）。

---

## 二、验证命令的原始输出

### 2.1 `pytest tests/repository/test_repos.py -q`（工单原命令）

```
........................................                                 [100%]
============================== warnings summary ===============================
.venv\Lib\site-packages\_pytest\cacheprovider.py:469
  ... PytestCacheWarning: could not create cache path ...\.pytest_cache\v\cache\nodeids:
  [WinError 5] 拒绝访问。 ...

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
```

**说明（不是省事，是必须写清楚）**：`pyproject.toml` 的 `addopts = "-q"` 与命令行 `-q` 叠加成
`-qq`，pytest 因此在 `-qq` 下**不打印计数行**；同一命令加 `-p no:cacheprovider` 即可看到计数
（下面的 2.2）。41 个点 = 41 passed。警告是本机沙盒不允许写 `.pytest_cache`（环境artifact，
与代码无关）。

### 2.2 `pytest tests/repository/test_repos.py -p no:cacheprovider --no-header`

```
41 passed in 1.65s
```

### 2.3 `pytest tests/repository/test_repos.py -p no:cacheprovider --no-header -m integration`（真实 MySQL）

```
4 passed, 37 deselected in 2.33s
```

工单原命令 `... -q -m integration` 的输出：

```
....                                                                     [100%]
```

**没有 skip**：`127.0.0.1:3306` 可达，凭据由 `conftest.py` 从本机 `.env` 回填到
`DSH_IT_MYSQL_PASSWORD`（未硬编码，未手启 `mysqld`）。

### 2.4 全量基线 `pytest -p no:cacheprovider --no-header -m "not integration"`

我的实现与用例全部落地、且**并发任务尚未写入新文件**时的一次捕获：

```
864 passed, 8 skipped, 14 deselected in 23.00s
```

**基线随并发变化（如实说明）**：本任务执行期间，另一个 subagent 正在写 Task 3.5 的迁移模块，
它把新文件 `tests/repository/test_migration.py`（`??` 未跟踪）与 `deploy/sql/migration/*` 落进同一棵树。
该文件落地后的基线变为：

```
FAILED tests/repository/test_migration.py::test_env_py_excludes_shard_tables_and_exposes_shard_hook
FAILED tests/repository/test_migration.py::test_downgrade_is_refused_without_explicit_flag
2 failed, 874 passed, 8 skipped, 19 deselected in 11.72s
```

**这 2 个失败与 Task 3.7 无关**（我一次都没改 `deploy/sql/**`、`test_migration.py` 也不 import 我的模块），
按工单口径单跑确认：

```
> pytest tests/repository/test_repos.py tests/repository/test_sharding.py -p no:cacheprovider --no-header
116 passed in 1.70s
```

（同一时点 `pytest tests/repository`：`2 failed, 249 passed`，两处失败都落在 `test_migration.py`。）

（8 skipped 是既有的"需要真实 MySQL/Redis 且未配置"的用例；14 deselected 是 integration 段。）

### 2.5 覆盖率 `pytest -m "not integration" --cov --cov-report=term-missing`

```
src\aicore\repository\base.py                 83      0   100%
src\aicore\repository\correction_repo.py      19      0   100%
src\aicore\repository\ocr_repo.py             17      0   100%
src\aicore\repository\task_repo.py            37      0   100%
src\aicore\repository\verdict_repo.py         37      0   100%
TOTAL                                       1313     36    97%
Required test coverage of 80.0% reached. Total coverage: 97.26%
```

本任务 5 个模块 **100% 行覆盖**（门禁 `fail_under = 80` 通过）。

### 2.6 `ruff check . --no-cache`

```
Found 3 errors.
  --> deploy\sql\migration\env.py:83:101  (E501)
  --> deploy\sql\migration\env.py:166:5   (E501)
  --> deploy\sql\migration\env.py:188:71  (E501)
```

**这 3 个错误不在我的文件里**（`deploy/sql/migration/env.py` 属 Task 3.5 的迁移模块，我没有改动它，
`git status` 可证）。我这 6 个文件单独跑：

```
> ruff check src/aicore/repository/{base,task_repo,ocr_repo,correction_repo,verdict_repo}.py tests/repository/test_repos.py --no-cache
All checks passed!
```

（`grep E501` 的实测踩坑记录：首轮有 10 处 E501，全部是中文 docstring 的行——东亚宽字符按 2 列计，
写长中文注释必须主动折行；已逐条折行修完。）

### 2.7 `mypy src`

```
Success: no issues found in 52 source files
```

`Generic[ModelT]` + `Sequence[...]` 返回类型在 strict 下干净标注；`to_metadata` 的副本、
`RowMapping → 实体构造`、`CursorResult.rowcount` 三处必要的 `cast` 都写了理由（见 4.1 与偏离 1/3）。

### 2.8 `lint-imports --config .importlinter --no-cache`

```
Contracts: 4 kept, 0 broken.
--------
Warnings
--------
service 层只可与 provider.base 交互，不得依赖具体通道实现
- No matches for ignored import aicore.service.** -> aicore.provider.base.
```

（该警告是 `unmatched_ignore_imports_alerting = warn` 的既有产物——service 层还没写真实
Protocol 导入，与 Task 3.7 无关。）

---

## 三、R1~R7 逐条证据

| # | 约束 | 证据（用例名 → 断言） |
|---|---|---|
| **R1** | 读取方法 MUST 收分片键；缺失由 Task 3.3 的守卫抛错；MUST NOT 退化为全表扫描 | ① `test_every_read_method_requires_the_shard_key`：`inspect.signature` 遍历四个仓储**全部公开读取方法**，断言有 `shard` 且是 `KEYWORD_ONLY`；写方法/非分片读取用**显式白名单**分类，任何新方法不归类就报红。② `test_r1_whitelists_have_no_stale_entries`：白名单无失效条目。③ 守卫是**复用** Task 3.3 的 `require_shard_key`（五个模块共 17 处出现：import 与调用，未各写一份判据）。④ `test_missing_in_table_routing_key_raises_1001`：空 `task_id` / 空 `idem_key` / 空 `account_id` → `MissingShardKeyError(1001)`。⑤ `test_sharded_access_always_targets_the_physical_table`：捕获执行过的 SQL，断言全部打到 `ai_task_202607`，且**没有**任何 `\bai_task\b` 逻辑名裸查询（即不可能退化成"扫逻辑表"）。 |
| **R2** | 单表一事务；跨分片拆多次独立事务；MUST NOT 分布式事务 | ① `require_same_shard` / `cross_shard_transaction_guard` 的判据**委托** `assert_single_shard`（3.3 的唯一实现）。② `test_cross_shard_transaction_guard_really_rejects_two_months`：跨月 → `CrossShardOperationError(1003)`，且**被装饰函数一行都没执行**（正面证明"真会拒"，不是先跑再报）。③ `test_repository_layer_never_manages_the_transaction`：标识符扫描五模块 MUST NOT 出现 `commit`/`flush`/`rollback`/`begin_twophase`/`two_phase`/`prepare`。④ `test_repo_writes_open_no_two_phase_transaction`（sqlite）+ `test_cross_shard_write_is_rejected_and_no_two_phase_on_real_mysql`（MySQL，`event.listen(engine, "begin_twophase")` 计数）：**零次触发**。⑤ 集成用例里跨月写入后两个月表都查不到那两行 → 拒绝发生在写之前。 |
| **R3** | 写后立即读强制走主库 | ① 机制：本层**不自开引擎/会话**（`test_repository_modules_do_not_open_sessions_or_reach_upward` 扫描 `EngineFactory`/`create_engine`/`sessionmaker`/`read_session`/`replica` 全为 0），写方法与读方法收**同一个** `Session`。② `test_task_repo_round_trip_and_write_then_read`（sqlite）与集成用例：`insert` 后立刻 `get_by_id` **在未提交的同一会话里**读到该行（主库连接）。③ `base.py` 的 R3 条目明写：本层 MUST NOT 提供"读不到就回落从库"的路径。**局限见第五节第 2 条**（无真实从库，无法验证主从延迟场景）。 |
| **R4** | `review_verdict` 每审核记录至多一条结论；只增不改 | ① `test_verdict_repo_round_trip_and_at_most_one_verdict`（sqlite）与 `test_verdict_repo_at_most_one_verdict_on_real_mysql`：第二次插同一 `review_id` → `DuplicateVerdictError`，且**原结论未被覆盖**（仍 `CONFIRM`）。② `test_verdict_concurrent_duplicate_is_converted_by_the_primary_key`：模拟 TOCTOU 窗口，主键冲突同样转成业务异常，且"转换前 MUST 回查一次"。③ `test_verdict_foreign_key_failure_is_not_reported_as_duplicate`：外键失败 MUST NOT 被误报成"已有结论"。④ `test_verdict_repo_has_no_update_or_delete_for_verdict`：`dir()` 下无任何 `update*`/`delete*`。 |
| **R5** | `ocr_correction` 只增不改 | `test_correction_repo_has_no_update_or_delete_entry_point`：`dir()` 无 `update*`/`delete*`/`remove*`/`replace*`，且本类自己声明的方法恰为 `{insert, list_by_task}`。 |
| **R6** | 任务仅本人可查；repository MUST 提供按 `account_id` 过滤的能力，MUST NOT 提供"只按 task_id 查、不带账号"的入口 | ① `list_by_account` 的账号**取自分片键**（`table.c.account_id == shard.account_id`），`test_list_by_account_filters_and_paginates` 断言另一个账号的行不出现；② `find_by_idem_key` 的 `account_id` 是必填关键字参数，`test_find_by_idem_key_is_scoped_to_the_account` 断言同 `idem_key` 的两个账号各查各的；③ 四个仓储**没有**任何"只按 task_id 查"的入口（见 R1 的方法分类表，方法集合是穷尽的）；④ 集成用例 `test_task_idem_key_round_trip_on_real_mysql` 用真实库确认账号隔离。 |
| **R7** | `repository` MUST NOT import `service` / `provider` | ① `lint-imports`：`Contracts: 4 kept, 0 broken`。② `test_repository_modules_do_not_open_sessions_or_reach_upward`：按 **AST 标识符**扫描五模块，禁止出现 `service`/`provider`/`api`/`port` 标识符，并断言 import 顶层名落在白名单内。 |

**另有一条"物理表名"的核心证据（工单选型要求的实测依据）**：
`test_sharded_access_always_targets_the_physical_table` + `test_status_update_statement_only_sets_three_columns`
+ `test_physical_table_names_are_computed_not_written_down` + `test_model_metadata_still_holds_only_logical_names`
（元数据里只有逻辑名，没有 `_YYYYMM`），以及集成用例在真实 MySQL 上按 `ai_task_2098xx` 落库/读回。

---

## 四、逐项验收结论

| 工单要求 | 结论 |
|---|---|
| `base.py`：`ShardKey`（`account_id` + `created_at`，`month` 为派生属性，naive → `ParamError(1002)`） | ✅ `test_shard_key_requires_aware_created_at`（1002）、`test_shard_key_month_is_derived_and_matches_task_3_3`（`month` 不在 `fields()` 里、frozen、与 `shard_month_of` 恒等）、`test_shard_key_month_is_utc_normalized`（`+08:00` 元旦 → `202512`） |
| `base.py`：`BaseRepo`（`logical_table` / `physical_name` / `require_same_shard`） | ✅ `test_physical_name_agrees_with_the_same_shard_guard`、`test_require_same_shard_*`（同月通过、跨月 1003、空集 1001） |
| `base.py`：`cross_shard_transaction_guard`（MUST 有用例正面证明"真会拒"） | ✅ `test_cross_shard_transaction_guard_really_rejects_two_months` + 4 条配套（容器收集 / fail closed / 签名保持） |
| 四个仓储的方法签名（照工单） | ✅ 除 **2 处刻意偏离**（`OcrRepo.insert` / `CorrectionRepo.insert` 多一个必填关键字 `shard`，见偏离 2）外逐字一致；签名由 `test_every_read_method_requires_the_shard_key` 与 `test_task_derived_tables_require_shard_key_on_insert` 机械钉住 |
| `VerdictRepo` 非分片、docstring MUST 写明"为什么不收分片键" | ✅ `verdict_repo.py` 模块 docstring 与两个读取方法 docstring 都写明（R1 的前提"分片表"不成立），并由豁免白名单在用例里可核对 |
| 分片表名 MUST 现算；选一条路径并给实测依据 | ✅ 选了**第 4 种落点**（`to_metadata` 物理表对象），理由与实测报错见偏离 1 |
| `update_status` MUST 只更新允许的列、返回受影响行数、MUST NOT `merge` | ✅ `test_status_update_statement_only_sets_three_columns`（`_values` 键恰为三列 + 编译 SQL 无 `created_at`/`model_meta`/`is_eval_sample`）、`test_update_status_leaves_non_target_columns_untouched`、集成用例实测 rowcount（同值 1 / 不存在 0） |
| R4 落地（前置检查或主键冲突转换，二选一须说明理由） | ✅ **两道都做**，理由写在 `insert_verdict` docstring（检查负责可读性、主键负责无竞态正确性）；覆盖 3 条用例 |
| R5 落地（无 update/delete） | ✅ `test_correction_repo_has_no_update_or_delete_entry_point` |
| `find_by_idem_key` 不得在无 `account_id` 下被调用 | ✅ 账号是必填关键字参数 + `require_shard_key`（空 → 1001）+ 用例 |
| 用例 1~5（不连库）、6~9（integration） | ✅ 1/2/3/4/5 全有；6 ✅ 四类存取各一次（真实 MySQL）；7 ✅ 跨分片被拒 + `begin_twophase` 零次；8 ✅ R4 实证（MySQL）；9 ✅ 只 DROP 自己建的分片表 + `DROP TEMPORARY TABLE`，**无 `DROP DATABASE`**、未碰固定名真实表（见偏离 5） |
| 禁止 `sleep`、禁止在生产库写入 | ✅ 测试文件里 `sleep` 只出现 1 次，位于模块 docstring 的约定句（"测试内 MUST NOT 出现 \`sleep\`"）——**没有任何 `time.sleep` 调用**；集成用例只用 `aicore_test` |
| 覆盖率门禁 80 | ✅ 97.26%（本任务 5 个模块 100%） |

---

## 五、偏离工单之处 + 理由

### 偏离 1（最重要）：物理表名的落点选了"第 4 种"，工单给的三条路径实测不成立

工单要求"三条候选路径选一条并说明实测依据"，实测结论如下（探针原始输出）：

- **② `aliased(Model, name=物理名)`：读错表 + 写不可用。**
  ```
  select(aliased(AiTask, name="ai_task_202607"))
  → SELECT ai_task_202607.task_id, ... FROM ai_task AS ai_task_202607 WHERE ...
  ```
  `name=` 是 **SQL 别名**，底表仍是逻辑表 `ai_task`（生产上不存在这张表；若真存在同名表就会静默
  读写**另一张表**）。写入路径：
  ```
  insert(aliased(AiTask, name=...)).values(...)
  → AttributeError: 'AnnotatedAlias' object has no attribute '_autoincrement_column'
  insert(inspect(A).selectable)  → 同一 AttributeError
  aliased(AiTask, <物理表副本>)   → InvalidRequestError: Query contains no columns with which to SELECT from
  ```
- **① `table_prefix` + `before_cursor_execute` 语句改写：结构上不可行。** 官方示例要在**引擎**上注册
  事件监听，而本层只收调用方传入的 `Session`（工单硬要求：MUST NOT import `EngineFactory`、MUST NOT
  自开引擎），注册全局监听既越权又会影响进程内所有语句；且占位前缀要写进 `__tablename__`，而
  Task 3.2 已定"元数据只放逻辑名"、Task 3.6 的三源比对依赖它（工单明确 MUST NOT 改）。
- **③ `text()` 手写 SQL：未采用**（丢类型与参数绑定，与"模型是唯一代码侧映射"相悖）。

**实际落点**：`Table.to_metadata(MetaData(), name=物理名)` 复制出**物理表对象**，读 / 写全部走它上面的
Core 语句。实测编译结果：

```
SELECT ai_task_202607.task_id, ... FROM ai_task_202607 WHERE ai_task_202607.task_id = %s
INSERT INTO ai_task_202607 (task_id, account_id, ...) VALUES (%s, %s, ...)
UPDATE ai_task_202607 SET status=%s, progress=%s, finished_at=%s WHERE ai_task_202607.task_id = %s
```

理由与性质：列定义**全部来自 `models.py` 的元数据**（不是第二套模型，`__tablename__` 一字未改，
Task 3.6 的三源比对不受影响）；参数是真绑定参数；副本按 `(逻辑表, 物理名)` 缓存（每副本独立
`MetaData` + `dict.setdefault` 无锁去重，规避多线程下的 `Table ... is already defined`）。
**代价（如实登记）**：分片表的读路径返回的是 `Model(**row)` 构造的**游离实体**（不进 identity map）——
本项目模型无 relationship，故无懒加载语义损失。

### 偏离 2：`OcrRepo.insert` / `CorrectionRepo.insert` 多一个必填关键字 `shard`

工单签名是 `insert(self, session, entity)`，但 `ocr_result` / `ocr_correction` **没有自己的业务时间列**，
而分片月 MUST 来自"该任务的 `created_at`"（`sharding.py` 的 S5：`task_id` 是 `task_` + UUID，
**不含时间戳**，MUST NOT 从它解析月份）。没有月份来源就只剩两条路：猜当前时间（静默错片）或回查
所有分片（R1 明禁的全表扫描）。故补 `*, shard: ShardKey`，并由
`test_task_derived_tables_require_shard_key_on_insert` 钉死（含反面对照：`ai_task` 自带 `created_at`、
复核两表不分片，都不收分片键）。

### 偏离 3：`base.py` 增加了 `model` 类属性与三个模块级工具

- `BaseRepo.model`（工单只点名 `logical_table`）：四个仓储都要"逻辑名 → 物理表对象 / 行 → 实体"。
  声明成**普通类属性**而不是 `ClassVar[type[ModelT]]`，因为 mypy 拒绝 `ClassVar` 里出现类型变量
  （`ClassVar cannot contain type variables`）。
- `physical_table(logical, month)`：物理表对象的唯一构造与缓存处（选型理由见偏离 1）。
- `entity_values(entity)`：实体 → Core INSERT 参数字典，`None` 的列整体不进列清单（让
  `status`/`progress`/`created_at` 的 `server_default` 生效；可空列省掉与写 NULL 等价）。
- `task_repo.status_update_statement(...)`：把"只更新三列"做成**可机械断言**的纯函数接缝
  （工单用例 5 要求检查 `_values`）；同时把逻辑表名字面量收敛到 `TASK_LOGICAL_TABLE` 一处。
- `BaseRepo` 的 `Generic[ModelT]` 写法**加了 `# noqa: UP046`**：工单逐字要求该形状且验收项点名
  "mypy strict 下 `Generic[ModelT]` 必须过"，故不用 PEP 695 改写；豁免处写了理由。

### 偏离 4：`DuplicateVerdictError` 暂借业务码 `1003`（**待收紧项**）

平台 `_common/openapi.yaml` 的 `ErrorCode` 枚举里，语义最贴的是 **`3007 # 状态不允许该操作`**（锁 409）；
但 `core/errors.py` 的 `AICORE_ERROR_CODES` 只收 10 个码、**不含 3007**，而"新增一个码"要按该文件顶部
的四处清单同步（含 `tests/unit/test_errors.py` 的两张字面量表）——那超出本任务的文件边界
（我只能改 `repository/` 五个模块 + `test_repos.py`）。故暂借 `1003`（`1xxx` 参数段：调用方对已结论的
审核记录再次发起写入属**请求**不合规，而非服务端故障），口径与 `sharding.py` 的
`CrossShardOperationError` 借 1003 表达"取值组合越界"一致。类继承 `ParamError`（唯一做了码值构造期
校验的类）。**建议**：平台补 409 档位后将本类收紧为 3007（属 Task 2.3 的文件范围）。

### 偏离 5：集成用例里的固定名表用**会话级临时表**（同名但连接私有）

工单说"若测验需要 `review_verdict` 等固定表，MUST 用**独立前缀**的临时表而非真实表"。实测无法照做的
原因是：`VerdictRepo` 的 SQL 由代码写死为物理名 `vision_review` / `review_verdict`，"独立前缀"的表
根本不会被仓储访问到（若为此给仓储加"表名前缀参数"，等于为测试污染生产 API）。
故改为 **MySQL 会话级临时表**：`CREATE TEMPORARY TABLE vision_review/review_verdict`（DDL 由模型元数据
编译后替换 `CREATE TABLE` 前缀，并去掉外键——MySQL 临时表不支持外键）。性质：只在**本连接**可见、
真实表不受任何影响、连接归还即消失；用例 additionally `DROP TEMPORARY TABLE IF EXISTS` 并
`engine.dispose()`，避免脏临时表留给同进程后续用例。这既满足"不得碰真实固定表"的意图，
又让 `VerdictRepo` 真的跑在 MySQL 上（R4 的 MySQL 实证）。
**残留差异（如实登记）**：临时表没有物理外键，故"`review_verdict` → `vision_review` 外键"的真实验证
仍由 `test_apply_ddl_mysql.py`（DDL 层）承担。

### 偏离 6：`rowcount` 口径——我最初的写法是**错的**，实测后改正

我最初按"裸 MySQL 默认"写 docstring：同值更新返回 0。集成用例第一次跑就报
`AssertionError: assert 1 == 0`。实测结论：**SQLAlchemy 的 MySQL 方言在连接时硬编码加上
`CLIENT.FOUND_ROWS`**（`sqlalchemy/dialects/mysql/base.py` 的 "rowcount Support" 一节明写
"SQLAlchemy standardizes the DBAPI cursor.rowcount ... number of rows matched ... always add
constants.CLIENT.FOUND_ROWS ... This setting is currently hardcoded"），故本栈上 `rowcount` 是
**匹配行数**：同值重放 **1**、不存在的行 **0**。docstring 与用例已按实测改正，并把这条差异写成
"按裸 MySQL 语义写代码的人会以为返回 0"的提醒。

### 偏离 7：`cross_shard_transaction_guard` 在"零个分片键"时 fail closed

工单只规定"两个不同月份 MUST 抛 `CrossShardOperationError`"。我额外让"一个分片键都没收到"抛
`MissingShardKeyError(1001)`（与 `assert_single_shard` 的空集口径一致）：守卫判断不了这次操作落在
哪个分片时放行，等于让"忘了传分片键"静默通过。用例 `..._fails_closed_without_any_key` 钉住。
docstring 也如实写明它**挡不住**"跨事务的跨分片"（两次独立事务本就允许）与"函数从别处取分片键"。

### 偏离 8：`base.py` 的守卫语义边界写进 docstring（而非代码）

`er.md` §5.5 的"写后立即读走主库"在本层能做的只有：不自开会话、不给只读旁路、写读同会话。
R3 的最终保证在 service 层"注入哪个会话"。这一点写进了 `base.py` 的 R3 条目，未在仓储里加
"检测是否从库"的运行时判断（那需要引擎身份，本层拿不到，也不该拿）。

---

## 六、我没做到的事（诚实登记，不美化）

1. **R3 只在"机制层"证明，未验证主从延迟场景**：本机只有一个 MySQL 实例（无真实从库），
   `er.md` §5.5 的"主库写、从库读、写后立即读走主库"里，**从库一致性未被验证**
   （Task 3.4 的 `session.py` docstring 也登记了同一局限）。我的证据是：本层不自开会话/不挑库
   （AST 扫描）+ 写读同会话可见 + docstring 明确要求。若要更强，需要在 service 层用真实的
   `write_session` / `primary_read_session` 走一遍。
2. **没有使用 Task 3.4 的 `session.py` 做端到端**：3.4 已提交（`4c58544`），但工单明确说"不要为它
   停下"，且它的 `Settings` 走 `AICORE_MYSQL_*`（`conftest` 注入的是 `test_*` 假凭据），把它接进我的
   用例需要另建一套配置注入，收益（R3 的机制级复证）小于耦合别人 API 的风险。**故按工单许可跳过**，
   并在第 1 条里登记为可补强项。
3. **`_to_entity` 返回游离实体**：分片表读回来的对象不在 session 的 identity map 里（同一行读两次是
   两个对象）。这是"不改 `__tablename__` + 不建第二套映射"的代价，已写进 `base.py` docstring。
   当前模型无 relationship，实际影响为零；若将来加了 relationship，需要重新评估。
4. **sqlite 沙盒有三处缩水**（写进测试模块 docstring）：时间类 `server_default` 被抹掉
   （`CURRENT_TIMESTAMP(3)` 是 sqlite 语法外）、分片表外键不建（指向逻辑名，无法随物理名解析）、
   sqlite 默认不校验外键（只在"外键失败不得误报成重复"那条用例里显式打开）。故沙盒证明的是
   **语句语义与对象映射**，"库默认值 / 真实外键"的行为由 MySQL 集成用例与 `test_apply_ddl_mysql.py` 覆盖。
5. **`ruff check .` 全仓仍有 3 个 E501，位于 `deploy/sql/migration/env.py`**（Task 3.5 的文件，
   我没有改它的权限也没有改它）。我的 6 个文件全绿。
   另外：全量基线在我的任务进行中被并发任务（Task 3.5）改写，出现 2 条
   `tests/repository/test_migration.py` 的失败——**与我的改动无关**（我未碰 `deploy/sql/**`，
   该测试文件也不 import 我的模块），已按工单单跑确认（见 §2.4）。
6. **缺少的一条用例（工单有、我按"不得碰真实固定表"改写了形态）**：`review_verdict` 指向
   `vision_review` 的**真实物理外键**约束在仓储路径上未被验证（临时表无外键），见偏离 5 的残留差异。
7. **一次自我违规（必须记下）**：调试探针 2 时我用 PowerShell
   `(Get-Content -Raw) -replace ... | Set-Content -Encoding UTF8` 改过 `_probe_repo_paths2.py`
   ——该文件含中文，违反铁律 2（MUST NOT 用 `Set-Content`/`Out-File`/`>` 写含中文的文件）。
   文件是一次性探针、已删除，未影响交付物（也证明我之后所有正式文件都用 write/edit 工具写入，
   实测 BOM=False、CRLF=False）。**这是我的操作失误，不是环境限制。**

---

## 七、给下一个读者的两个关键提醒

1. **分片表的读写 MUST 走 `physical_table(logical, month)`**：直接用 ORM 实体查询会打到逻辑名
   （`ai_task`）——生产库里没有这张表；`aliased(Model, name=物理名)` 更危险（编译成
   `FROM ai_task AS 物理名`，若真有同名表就静默读写另一张表）。用例
   `test_sharded_access_always_targets_the_physical_table` 会拦下这两类写法。
2. **`OcrRepo.insert` / `CorrectionRepo.insert` 的 `shard` 参数不是可选装饰**：它必须等于
   **该任务**所在月（`ai_task.created_at` 的月份），MUST NOT 用"现在的时间"或 `corrected_at` 推算
   （见 `correction_repo.py` 的 docstring）。
