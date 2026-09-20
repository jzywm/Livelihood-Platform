# Task 3.3 报告：按月分表路由（`repository/sharding.py`）

**状态**：完成。6 条门禁全绿；**0 处结构漏项**、**S1~S6 逐条有落点与用例**；
**1 处真实不一致**（`apply_ddl.py --month` 与运行期 `ensure_month_tables` 的月份校验口径不同）
+ **10 处工单未列的加严/公开项**，全部登记在第 4 节并说明理由。
**工作树**：`D:\progrom\.worktrees\aicore-architecture`，服务根 `services/aicore/`。
**MUST NOT `git commit`** —— 未提交，改动留在工作区等控制者统一提交。
**探针脚本**：**0 个**（未创建任何一次性探查脚本；诊断一律用 `python -c` 内联命令）。

---

## 1. 交付文件清单

| 文件 | 动作 | 规模 |
|---|---|---|
| `services/aicore/src/aicore/repository/sharding.py` | 修改（原为 1 行 docstring 占位） | 484 行 |
| `services/aicore/tests/repository/test_sharding.py` | 新建 | 700 行 / **75 条用例**（含 3 条 integration） |
| `services/aicore/scripts/apply_ddl.py` | 修改（**收编渲染逻辑**：删掉本地 `render_template` / `DDL_DIR` / 两张表清单，改为 import `sharding`） | 192 → 177 行 |

`sharding.py` 内容：模块 docstring（S1~S6 → 落点、UTC 口径、`task_id` 不算月、渲染唯一实现、
事务边界；仅依赖 `aicore.core.*` 与 `sqlalchemy`）、`SERVICE_ROOT` / `DDL_DIR`、
三张表清单（有序元组 + 两个 `Mapping` + 三个 `frozenset`）+ 导入期自检 `_check_table_manifests()`、
两个异常类、渲染与自检助手（`sql_skeleton` / `_assert_no_placeholder` / `_require_month`）、
路由（`shard_month_of` / `physical_table_name`）、渲染（`template_for` /
`render_shard_template` / `render_fixed_table_ddl`）、幂等建表（`ensure_month_tables`）、
跨分片守卫（`require_shard_key` / `assert_single_shard`）。

**交付接口逐条对照工单**（签名一致，无增删参数）：

| 工单签名 | 状态 |
|---|---|
| `SHARDED_TABLES: frozenset[str]` | ✅ 3 项 |
| `FIXED_TABLES: frozenset[str]` | ✅ 6 项 |
| `ALL_TABLES: frozenset[str]` | ✅ 9 项 |
| `shard_month_of(created_at: datetime, *, field: str = "created_at") -> str` | ✅ |
| `physical_table_name(logical: str, at: datetime \| str) -> str` | ✅ |
| `template_for(logical: str) -> Path` | ✅ |
| `render_shard_template(logical: str, month: str) -> str` | ✅ |
| `ensure_month_tables(conn: Connection, month: str) -> None` | ✅（`Connection` = `sqlalchemy.engine.Connection`） |
| `render_fixed_table_ddl(logical: str) -> str` | ✅ |
| `class MissingShardKeyError(ParamError)` `code = 1001` | ✅ |
| `class CrossShardOperationError(ParamError)` `code = 1003` | ✅ |
| `require_shard_key(value: object, *, field: str) -> None` | ✅ |
| `assert_single_shard(months: Iterable[str], *, operation: str) -> str` | ✅ |

文件编码实测（脚本核对，非目测）：三文件均 **UTF-8 无 BOM、LF 行尾**。

```
src/aicore/repository/sharding.py | BOM: False | CRLF: False | utf8 ok: True
tests/repository/test_sharding.py | BOM: False | CRLF: False | utf8 ok: True
scripts/apply_ddl.py | BOM: False | CRLF: False | utf8 ok: True
```

---

## 2. 验证命令与原始输出

### 2.1 本任务用例（工单原命令）

```
$ .venv\Scripts\python.exe -m pytest tests/repository/test_sharding.py -q
........................................................................ [ 96%]
...                                                                      [100%]
exit=0

$ .venv\Scripts\python.exe -m pytest tests/repository/test_sharding.py -q -m integration
...                                                                      [100%]
exit=0
```

> **计数行为说明**（与 Task 3.2 报告登记的同一现象）：`pyproject.toml` 的 `addopts = "-q"`
> 与命令行 `-q` 叠加成 `-qq`，该模式**不打印末行计数**。故去掉重复的 `-q` 各跑一次取计数：

```
$ .venv\Scripts\python.exe -m pytest tests/repository/test_sharding.py -p no:cacheprovider
........................................................................ [ 96%]
...                                                                      [100%]
75 passed in 1.81s

$ .venv\Scripts\python.exe -m pytest tests/repository/test_sharding.py -m integration -p no:cacheprovider
...                                                                      [100%]
3 passed, 72 deselected in 1.26s
```

**注意**：`integration` 标记在 `pyproject.toml` 里**没有**配 `-m "not integration"` 的默认排除，
故上面的 75 条里**已含** 3 条真实 MySQL 用例，且它们是 **passed 而非 skipped**
（本机 `.env` 有可用凭据）——即"真实库门禁"这次真的生效了，不是静默跳过。

### 2.2 全量回归（基线 669 passed / 8 skipped）

```
$ .venv\Scripts\python.exe -m pytest -p no:cacheprovider
........................................................................ [ 95%]
.................................                                        [100%]
745 passed, 8 skipped in 28.25s
```

计数口径（**不是**"多了一条来路不明的用例"）：

```
745 passed + 8 skipped = 753 collected
  = 669 passed（Task 3.1 基线，实测复现）+ 75（本任务新增）
  + 1（并发兄弟任务的 src/aicore/repository/schema.py 让
       tests/structural/test_source_guards.py::test_model_http_calls_only_in_provider
       这个「按 src 下 .py 文件参数化」的用例多出 1 条）
skipped 恒为 8（与本任务基线逐数一致，未变红、未新增 skip）
```

### 2.3 其余门禁

```
$ .venv\Scripts\ruff.exe check . --no-cache
All checks passed!
（stderr 另有若干 `warning: Encountered error: 拒绝访问。 (os error 5)`：
  来自服务根下**既有的**、沙箱不可读的 `pytest-cache-files-*` 目录，非本任务代码，
  本任务开工前的首次 `ruff check .` 就有同样警告；退出码 0）

$ .venv\Scripts\mypy.exe src
Success: no issues found in 52 source files

$ .venv\Scripts\lint-imports.exe --config .importlinter --no-cache

api 层不得直接依赖 repository / provider KEPT
service 层只可与 provider.base 交互，不得依赖具体通道实现 KEPT (1 warning)
repository / provider / port 不得反向依赖 service KEPT
core 不得依赖任何业务层 KEPT

Contracts: 4 kept, 0 broken.
（那 1 warning 是 `.importlinter` 里已登记的「放行表达式暂无匹配」既有告警，与本次改动无关）
```

追加核对（不在验收命令内，供参考）：`ruff format --check` 对**本任务两个新/改文件**
（`sharding.py` / `test_sharding.py`）报 **already formatted**；`apply_ddl.py` 仍报 2 处差异，
**均在我未改动的那两行多行 `print`（Task 3.1 原文）上**——用 HEAD 版本喂给同一命令同样以
`exit 1` 结束，即该差异**非本次引入**，我按"最小改动"原则逐字保留了它。

### 2.4 真实 MySQL 的行为证据（比"用例通过"更硬的两条）

（1）**建表顺序反序 MUST 失败** —— 集成用例里 `pytest.raises(DBAPIError)` 捕获到的原文：

```
反序建表报错 = OperationalError | (pymysql.err.OperationalError)
(1824, "Failed to open the referenced table 'ocr_result_209901'")
```

（2）**清理边界**：运行我的集成用例后，`aicore_test` 的表清单里**没有** `209901` 残留，
6 张固定名表完好；清单里那 3 张 `_202607` 是**别的会话/任务**早先留下的，不是本任务产物：

```
aicore_test 表清单 = ['ai_task_202607', 'kitchen_anomaly', 'ocr_correction_202607',
 'ocr_result_202607', 'review_verdict', 'risk_predict_result', 'vision_marker',
 'vision_qa_log', 'vision_review']
```

（3）**收编后的 `apply_ddl.py` 真的还能建表**：`tests/repository/test_apply_ddl_mysql.py`
的 5 条真实 MySQL 用例（子进程跑脚本、退出码、9 表齐备、外键带月份且 RESTRICT、
索引与 er.md 一致、幂等、非法月份被拒）在本次 `-m integration` 跑里全过：

```
$ .venv\Scripts\python.exe -m pytest -m integration -v -p no:cacheprovider
collected 753 items / 745 deselected / 8 selected

tests\repository\test_apply_ddl_mysql.py .....                           [ 62%]
tests\repository\test_sharding.py ...                                    [100%]

===================== 8 passed, 745 deselected in 12.22s ======================
```

### 2.5 交付边界

```
$ git status --short
 M services/aicore/scripts/apply_ddl.py              ← 我的（收编渲染逻辑）
 M services/aicore/src/aicore/repository/sharding.py ← 我的
?? services/aicore/tests/repository/test_sharding.py ← 我的
 M services/aicore/src/aicore/core/idgen.py          ← **并发兄弟任务**的改动（非我的）
?? .sdd-tools.py                                              ← 开工前就在（非我的）
?? services/aicore/src/aicore/repository/schema.py            ← **并发兄弟任务**的产物（非我的）

$ git diff --stat
 services/aicore/scripts/apply_ddl.py              |  75 ++--
 services/aicore/src/aicore/repository/sharding.py | 485 +++++++++++++++++++++-
 2 files changed, 514 insertions(+), 46 deletions(-)
```

> **本工作树正被多个任务并发使用**：`schema.py`（未跟踪）与 `core/idgen.py`（已修改）
> 都不是本任务的产物，我**没有**碰过它们；`git status` 因此做不到"只有我的 3 个文件"，
> 这属于环境事实而非本任务越界。`git diff --stat` 里只有我的两个文件被跟踪修改。

### 2.6 一次瞬时红灯的现场登记（已定位原因，三轮复跑全绿）

最终门禁复跑中有**一次**出现 `1 failed, 744 passed, 8 skipped`：

```
FAILED tests/structural/test_layering.py::test_layering_contracts_pass - asse...
1 failed, 744 passed, 8 skipped in 29.99s
```

**定位**（不是猜的）：`tests/structural/test_layering.py` 会把违规探针文件
**真实写进共享源码树**（`src/aicore/repository/repo_probe.py`、
`src/aicore/api/routes_probe.py` 等，`finally` 里删除），而**同一工作树里还有别的任务
在并发跑同一套用例**——那一刻别的进程写入的探针文件被我这次 lint 扫描看到，
于是"干净代码上四条契约必须 KEPT"这条断言变红。

证据：
- 同一时刻**独立**跑 `.venv\Scripts\lint-imports.exe --config .importlinter --no-cache`
  = `Contracts: 4 kept, 0 broken.`（我的代码本身没有任何违规导入）；
- 该用例**单独**跑 = `8 passed`；
- 随后**连续三轮**全量跑 = `745 passed, 8 skipped`（26.47s / 26.42s / 26.52s）；
- 跑完后 `src` 下无任何 `*_probe.py` 残留（探针文件已被其 `finally` 清掉）。

结论：这是**共享工作树 + 多进程并发跑同一套用例**的既有竞态（探针写真实源码树），
与 Task 3.3 的改动无关；我的模块在测试期不写任何文件。

---

## 3. 逐项验收结论

### 3.1 硬约束 S1~S6

| # | 约束 | 落点 | 用例 |
|---|---|---|---|
| S1 | 分片表只有 3 张，物理名 `xxx_YYYYMM` | `SHARDED_TABLES` / `FIXED_TABLES` / `ALL_TABLES` / `physical_table_name` | `test_table_manifests_are_exactly_three_six_nine`（3/6/9 逐项）、`test_physical_table_name_across_two_months`（3 表 × 2 月）、`test_physical_table_name_rejects_fixed_tables`（6 表逐个抛错） |
| S2 | 分片键 `(account_id, created_at)`；结果表随 `task_id` 同月同分片 | `shard_month_of` / `SHARDED_TABLE_ORDER` / `ensure_month_tables` | `test_physical_table_name_*`、`test_build_order_*`（真实库）、`test_rendered_correction_template_carries_month_into_foreign_key_name` |
| S3 | 查询必须携带分片键下推；缺失直接抛错 | `require_shard_key` / `MissingShardKeyError(1001)` | `test_require_shard_key_rejects_missing_values`（`None`/`""`/`"   "`/`"\t\n"`）、`test_assert_single_shard_rejects_empty` |
| S4 | 禁止跨分片 JOIN / 聚合 / 事务 | `assert_single_shard` / `CrossShardOperationError(1003)` | `test_assert_single_shard_rejects_cross_month`（码值逐字 1003 + operation + 月份）、`..._deduplicates_same_month`、`..._consumes_generator_once` |
| S5 | 只认业务字段所在月，不依赖内嵌时间戳 | `shard_month_of` 只收 `datetime`；模块内**无任何** `task_id` 解析代码 | `test_shard_month_of_rejects_string_input`（3 种字符串形态）、docstring 与实现均无 `task_id` 解析 |
| S6 | 结果表同分片，1:1 查询不跨分片 | 同月同后缀（`{month}` 同时进表名与约束名） | `test_rendered_correction_template_carries_month_into_foreign_key_name` + 真实库外键指向 `ocr_result_209901` |

### 3.2 时区口径（4 条边界，全部显式构造、无 `sleep`、不依赖当前时间）

| 输入 | 期望 | 结果 |
|---|---|---|
| `2026-01-31T23:59:59.999Z` | `202601` | ✅ `test_shard_month_of_adjacent_millisecond_boundary`（同用例断言两者相差恰好 1ms） |
| `2026-02-01T00:00:00.000Z` | `202602` | ✅ 同上 |
| `2026-01-01T00:00:00+08:00` | **`202512`** | ✅ `test_shard_month_of_utc_plus_eight_crosses_year` |
| `2028-02-29T12:00:00Z` | `202802` | ✅ `test_shard_month_of_leap_day` |
| naive `2026-01-01 00:00` | 抛 `ParamError`（1002，含"时区"） | ✅ `test_shard_month_of_rejects_naive_datetime` |

### 3.3 交付接口细则

| 要求 | 结果 |
|---|---|
| `physical_table_name` 的 `str` 入参校验「6 位数字 + 月份 01~12」，否则 `ParamError(1002)` | ✅ 8 种非法形态参数化（含全角数字、`202613`、`202600`、长度不符） |
| 非分片表传入 `physical_table_name` / `render_shard_template` / `template_for` → `ParamError(1002)` | ✅ 三处各有用例（6 表逐个参数化） |
| `render_shard_template` 传非分片表抛错（与 `render_fixed_table_ddl` 传分片表反向同理） | ✅ 双向都有用例 |
| `render_shard_template` 渲染后自检「骨架无 `{` 残留」 | ✅ 三表渲染后骨架无残留；**并有反证**：`test_shard_template_self_check_fires_on_broken_template`（坏模板 MUST 抛 `RuntimeError`） |
| 渲染实现与 `apply_ddl.py` **共用同一份** | ✅ 脚本已删掉本地实现改为 import；`plan_statements` 直接用 `sharding` 的渲染函数与顺序表 |
| `{month}` MUST 同时替换到外键约束名 | ✅ `fk_ocr_correction_task_202601` / `..._202602` 两月对照断言 + 真实库 `information_schema` 核对 |
| `ensure_month_tables` 顺序 `ai_task`→`ocr_result`→`ocr_correction` | ✅ 假 `Connection` 记录 SQL 顺序（默认段就拦住"循环写反"）+ 真实库"反序失败/正序成功"双向探测 |
| 幂等、零错误复跑 | ✅ 真实库 `CREATE_TIME` 前后一致（只看"没抛异常"不够：先 DROP 再 CREATE 也不抛异常） |
| 用 `conn.exec_driver_sql` | ✅ 假 Connection 只实现 `exec_driver_sql`（改成 `execute` 会 `AttributeError` 变红）+ 真实库路径 |
| MUST NOT DROP / MUST NOT commit | ✅ 假 Connection 记录 `calls == ["exec_driver_sql"]*3` 且语句里无 `DROP` |
| 两个异常 MUST 继承 `ParamError`，校验仍生效 | ✅ `issubclass` 断言 + 假码 `9999` 构造抛 `ValueError` + `ParamError(code=2001)` 抛 `ValueError` |
| 码值 `1001` / `1003` 逐字 | ✅ 缺键、跨片、语义三个用例各自逐字断言，**不靠继承推断** |
| 集成用例连不上 → 显式 `skip` | ✅ `_require_mysql()` 用 `pytest.skip` 带原因（本机未走该分支，实测是 passed） |
| 集成用例清理只 DROP 自己建的 3 张 `_<月>` 表 | ✅ `finally` 里逆序 DROP；用例末尾正面断言「3 张已消失 + 6 张固定表仍在」 |
| 用例内 MUST NOT `sleep`；跨月用显式 datetime | ✅ 全文无 `sleep`；全部用 `datetime(...)` 字面量构造 |

---

## 4. 偏离工单之处 + 理由

### 4.1 真实不一致（必须让控制者知道）

1. **月份校验口径在两条入口上不同**：`apply_ddl.py --month` 只做「6 位数字」检查
   （Task 3.1 的 CLI 契约，`test_apply_ddl_rejects_bad_month` 钉着"6 位数字"这句文案，
   且 `test_apply_ddl_mysql.py` 的演练月就是非法的 `202613`）；而**运行期**入口
   `ensure_month_tables` 与 `physical_table_name(at: str)` 会卡 `01~12`。
   故 `apply_ddl.py --month 202613` 能建表、运行期 `ensure_month_tables(conn, "202613")` 会拒。
   **为什么不统一**：统一成"渲染也卡 01~12"会让 Task 3.1 的 5 条既有集成用例全红，
   而修它们必须改 `tests/repository/test_apply_ddl_mysql.py`——**不在工单允许改动的文件清单内**。
   故选择「CLI 宽松（保持既有契约）、运行期严格（不让路由永远指不到的表被建出来）」，
   并在 `render_shard_template` 的 docstring 里写明这条口径的来源与边界。
   建议：Task 3.5（迁移）或后续统一时，把 `202613` 这个演练月改成合法月份，再让渲染也卡月份。

### 4.2 工单未列的加严项（均为"更严"，不放松任何 MUST）

| # | 加严 | 理由 |
|---|---|---|
| 2 | `ensure_month_tables` 增加 `YYYYMM` + `01~12` 校验（**且在任何 SQL 之前**） | 不校验时运行期能建出 `ai_task_202613` 这类"路由永远指不到"的表，写入成功、查询永远落空 |
| 3 | `assert_single_shard` 对去重后剩下的那一个月额外做格式校验 | 它是"拼物理表名前的最后一道守卫"，放行畸形月份等于给出**假放行信号**（fail-open）；工单三条判据（空/跨片/单月）行为**未变** |
| 4 | `render_fixed_table_ddl` 也做「骨架无 `{`」自检 | 固定名表出现占位符 = 该文件被误当模板或本该改名 `.template.sql`；与分片渲染共用同一助手，无额外实现 |
| 5 | 公开 `sql_skeleton` / `SERVICE_ROOT` / `DDL_DIR` / `SHARDED_TABLE_ORDER` / `SHARDED_TABLE_FILES` / `FIXED_TABLE_FILES` | `apply_ddl.py` 必须复用顺序与渲染、用例必须复用骨架判据；各写一份就是漂移源（工单已定"渲染只有一份实现"） |
| 6 | 自检失败抛 `RuntimeError`（工单只写"立刻炸"未定档类型） | 模板缺陷是**内部错误**：抛 `ParamError` 会被报成 400「参数错误」，误导排查方向；`RuntimeError` 经兜底处理器成 5000 才是对的语义 |
| 7 | `physical_table_name` 对既非 `datetime` 也非 `str` 的 `at` 抛 `ParamError(1002)` | 把 `None`/`int`/`bytes` 从 `AttributeError`（→5000）变成可预期的参数错误 |
| 8 | 模块导入期自检 `_check_table_manifests()` | 三个**静默失效点**：顺序元组与模板字典键集不等（新表不会被建）、同表既分片又不分片、表数不是 9。放用例里是第二道防线，导入期就该炸 |
| 9 | 用例额外覆盖：模型清单交叉核对、假 `Connection` 的顺序/无 commit/无 DROP、自检反证×2、`sql_skeleton` 口径、生成器输入、非法单月 | 每条都是"把 MUST 变成可执行断言"；假对象那条尤其重要——MySQL 对 DDL 有**隐式提交**，"实现有没有 commit"在真实库上根本观测不出来 |
| 10 | 不用 `tmp_path`，改用「假 DDL 目录对象」（`_FakeDdlDir` / `_FakeSqlFile`） | 本沙箱**禁止在系统临时目录建目录**（`PermissionError: [WinError 5]`，`tests/unit/test_config.py` 已登记同一限制）。假对象让自检反证用例完全不碰文件系统，比写临时文件更干净 |
| 11 | 全角数字用例用字符码现拼（`FULLWIDTH_MONTH = "".join(chr(0xFF10 + int(d)) ...)`） | RUF001 会拦下源码里的全角数字（规则本身正确），而全角数字**正是被测数据**（`str.isdigit()` 对它返回 True）；不以字面量出现即可两全 |

### 4.3 与 `errors.py` 口径的张力（登记，未擅自偏离）

`MissingShardKeyError` / `CrossShardOperationError` 的消息是**诊断型中文文案**
（点名 `field` / `operation` / 涉及月份），会随 `1xxx` 码进响应体 `message`；
而 `errors.py` 的口径是"响应 `message` 只取平台固定文案，不回显内部细节"。
**这是工单明写的例外要求**（"消息 MUST 点名 `operation` 与涉及月份，便于运维定位"），
故照工单执行；文案里**不含用户数据值**（只含字段名、操作名、6 位月份码）。
若控制者认为该文案外泄过多，改法是把诊断细节挪进日志、`message` 传 `None` 取平台文案——
一行改动，但会丢掉工单要的可定位性，故未擅自改。

---

## 5. 我没做到 / 未做（诚实登记）

1. **`apply_ddl.py` 的 2 处 `ruff format` 差异未消除**（我未改动的那两行多行 `print`）。
   理由：格式检查不在验收命令内；HEAD 版本同样 `exit 1`，证明非本次引入；动它会让 diff 混入
   Task 3.1 的无关改动。**若控制者要求全仓 format 干净，需要单独一轮统一做。**
2. **未在正式库 `aicore` 上执行任何 DDL**（只动 `aicore_test`，符合工单）。
3. **未清理 `aicore_test` 里 `_202607` 的 3 张分片表**：它们**不是本任务建的**（我的演练月是
   `209901`，已清理干净），且"只 DROP 自己建的"是工单的清理边界，故未越权删。
4. **未做 `git commit`**（工单禁止）。`git status --short` 里除我的 3 个文件外，还有
   `.sdd-tools.py`（开工前既有）、`src/aicore/repository/schema.py`（未跟踪）与
   `src/aicore/core/idgen.py`（已修改）——后两者是**并发兄弟任务**的产物，不在我的交付范围，
   我也未修改它们；全量用例数 +1 正来自 `schema.py`（见 2.2），一次瞬时红灯来自并发跑用例
   写入的探针文件（见 2.6）。
5. **未校验 `task_id` 与 `created_at` 的一致性**：工单与 S5 明确本模块 MUST NOT 从
   `task_id` 解析月份，故"调用方传进来的 `created_at` 确实属于该 `task_id`"由调用方保证
   （Task 3.7 的仓库层）。这是一条**已知的信任边界**，未加运行时校验。
6. **未接线到 service / 仓库层**（Task 3.4 / 3.7 的职责）：`ensure_month_tables` 的调用时机、
   "写前确保当月表存在"的落点都不在本任务范围，本模块只提供能力。
7. **`ensure_month_tables` 不管理事务，也管不了 MySQL 对 DDL 的隐式提交**：docstring 已写明
   ——"本函数不 commit"不等于"调用方能在同一事务里回滚建表"。
8. **失败日志/指标未加**：本模块抛异常但不打日志（日志口径归 core/logging 与上层），
   若控制者希望"建表失败必须留痕"，需要在上层接线时补。
9. **`sharding.py` 的 `at: str` 分支只接受纯 `YYYYMM`**：不接受 `2026-01`、`2026/01` 等
   人类可读形态（工单如此定档）。调用方的友好解析（如从 API 参数来）需自行先转 `YYYYMM`。
