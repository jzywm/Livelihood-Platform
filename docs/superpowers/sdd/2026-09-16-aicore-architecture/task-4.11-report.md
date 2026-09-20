# Task 4.11 报告：通道失败降级与异常区分（`4003` / `5002` 分别计数）

**基线**：HEAD `d409118` + `c924c6d`（Task 4.10 的两次提交），工作树干净
**工单**：`task-4.11-brief.md`（目标逐字取自 `tasks.md:47`；§2 已由用户裁定为 **(a)**）
**环境**：MySQL 与 Redis 均可用（集成段 **58 passed / 0 skipped**，连跑 3 次一致）
**纪律**：未 `git add` / `git commit`；探针 **0 个新文件**；未动 `er.md`、`openapi.yaml`、
`core/errors.py`、`core/task_runner.py`、`core/lease.py`、`.importlinter`、`pyproject.toml`、
`provider/**`（mock 的故障注入本来就够用）。

---

## 0. 一行结论

**本任务不需要改任何生产代码**：`4003` / `5002` 的**分类**（执行器取异常自带的
`AiCoreError.code`）与**落库**（`mark_failed(error_code=…)`）在 T2 已实现且已被 T2 的用例覆盖；
本任务的活是**把"两码分别落库、可分组计数、不阻塞受理、两条路径各自触发"钉成判据**，
外加一条**机械判据**守住"M1 不使用 `MANUAL_REVIEW`"这条将来才可能被违反的约定。
交付是**两个测试文件（新建）**：`tests/integration/test_failure_codes_mysql.py`（457 行）、
`tests/structural/test_no_manual_review_writes.py`（149 行）。

---

## 1. §2 的裁定及其对实现的影响（工单 §5 要求写明）

**裁定：用户 2026-09-20 选定 (a)——M1 不使用 `MANUAL_REVIEW`。**
`4003` 与 `5002` **都是** `status = FAILED` + `error_code = 对应码`；
"已转人工"是 `4003` 这个码**自带的语义**（`er.md:329` 逐字），**不是**状态迁移；
"人工复核队列" = 运维按 `error_code` 的查询视图（`WHERE status='FAILED' AND error_code='4003'`），
M1 不新建队列表、不新增状态；第四态留给 M2。

依据（我逐处核对过原文，与裁定一致）：`error_code` 在 `er.md:26`/`:329` **两处**都被定义为
「**FAILED** 业务码」；`design.md:210` 亦写「置 **`FAILED`** 并转人工复核队列」。

### 1.1 对实现的影响（**零代码改动 + 三处判据收窄**）

| 影响面 | 具体 |
|---|---|
| 生产代码 | **不改**。执行器本来就写 `FAILED` + `error_code`（T2 已实现），`MANUAL_REVIEW` 本来就**没有触发者** |
| §3.1 的判据 | 断言 `status='FAILED'` **+** `error_code` 各自正确（**不是**断言 `MANUAL_REVIEW`） |
| §3.2 的判据 | `WHERE status='FAILED' GROUP BY error_code` 即可，**不需要跨两个 status 聚合** |
| §3.5 的判据（新增） | 机械守住"没有代码路径把任务写回成 `MANUAL_REVIEW`"（见 §4） |

---

## 2. 已有什么 / 缺什么（RECON）

### 2.1 已有什么（T2 铺好的，**不重做**）

| 关切 | 落点 | 现状 |
|---|---|---|
| 两码的平台语义 | `core/errors.py`：`CHANNEL_FAILURE_CODE=4003`（"等到了失败"，HTTP 502）、`DEPENDENCY_TIMEOUT_CODE=5002`（"没等到响应"，HTTP 504）；类 `ChannelFailureError` / `DependencyTimeoutError` 是**兄弟** | ✅ 平台定档，**不许改** |
| 通道层的码与可分辨性 | `provider/errors.py`：`ProviderChannelFailureError(4003)` / `ProviderTimeoutError(5002)` / `ProviderCircuitOpenError(5002)` 多重继承自上面两个平台类；可分辨性由 `reason`/`operation` 承担 | ✅ 已实现（含一处控制者修正过的错误：熔断归 `5002`） |
| 故障注入 | `provider/mock.py`：`MockScript(latency_s, fault)` + `MockFault(kind="timeout"/"error"/"empty", on_call)` | ✅ **够用** ⇒ 按工单 §4"若已由 mock 支持则不改"，**没动 `provider/`** |
| 失败分流与码的来源 | `core/task_runner.py::_handle_failure`：终态走 `mark_failed(error_code=str(error.code))`——**取异常自带的 code，不由执行器猜** | ✅ T2 已实现 |
| 码真的落库 | `repository/task_repo.py::status_update_statement` 的 `error_code`（B3 修复）+ `task_lease_store.py::mark_failed` | ✅ T2 已闭合（此前 `FAILED` 行该列恒为 `NULL`，那样"分别计数"根本无法验收） |
| `MANUAL_REVIEW` 的现状 | 只出现在 `state.py`（定义 + `ALLOWED_TRANSITIONS` + `TERMINAL_STATUSES`）、`api/tasks.py`（读侧的 `Literal`/`DECLARED_STATUSES`）、`models.py`（列定义） | ✅ **没有任何写回调用使用它**（本轮把它变成机械判据） |

### 2.2 缺什么（本任务的活）

1. **没有判据**证明"两码分别落库且互不串"（既有用例只覆盖 `4003` 那一条：
   `test_runner_redis.py::test_failure_backs_off_then_exhausts_to_failed`）；
2. **没有判据**证明"`WHERE status='FAILED' GROUP BY error_code` 能分出两组"（= 分别计数的可验收形态）；
3. **没有判据**证明"通道不可用期间受理链路不受影响"；
4. **没有判据**区分"两条异常路径"（`5002` 必须来自依赖超时，不能复用通道失败）；
5. **没有机械判据**守住"没有任何代码路径写回 `MANUAL_REVIEW`"（§3.5 新增，因 §2 的裁定 (a)）。

---

## 3. §3 的五条判据（判据本体与自证都抽成助手，**自证喂的是同一份判据**）

### 3.1 + 3.2 两码不混用 / 分别计数

`tests/integration/test_failure_codes_mysql.py::test_two_failure_codes_land_separately_on_the_real_db`

两条任务各自经过**真实通道故障**由**真执行器**写回（先跑通道失败那条、再跑依赖超时那条，
一次只留一条未处理的任务 ⇒ `run_once` 领到的必然是本条）：

- `_assert_codes_are_separated(rows, expected={task_a: "4003", task_b: "5002"})`：
  **每行 `status == 'FAILED'`** + `error_code` 各自正确 + 两行的码集合恰好是 `{4003, 5002}`；
- `_assert_counts_are_separated(_counts_by_error_code(...), expected={"4003": 1, "5002": 1})`：
  裸 SQL `select error_code, count(*) from ai_task_<当月> where account_id=… and status='FAILED'
  group by error_code`。

**为什么必须同时断言 `status='FAILED'`**：M1 的裁定把两个码都定义在 `FAILED` 上；
只断言 `error_code` 会让"把 4003 写成 `MANUAL_REVIEW` 但 `error_code` 照写"的实现绿着通过。

**判据的一处实现错（已修，写下来备案）**：第一版我把中文标签拼进 `expected` 的键
（`f"{task_id}（通道失败）"`），而 `rows` 是按纯 `task_id` 索引的 ⇒ 判据自己在 `rows[key]`
上抛 `KeyError`。那是**判据的实现错**，不是被测对象的失败——`expected` 的键现在明确是
`task_id`，注释里写清了这条契约。

### 3.2 的登记（工单 §5 要求）：接指标时做成 counter

`design.md:98` 的 Prometheus 指标属**第 11 组**（可观测性与健康检查）——那只是**暴露方式**。
**本任务只保证事实源可分**：`WHERE status='FAILED' GROUP BY error_code` 现在就能分组。
接指标时把它做成 counter（`aicore_task_failed_total{error_code="4003|5002"}`），
**计数逻辑不重写**：指标直接读这条分组结果（或与执行器的写回同源计数），
MUST NOT 在执行器里再写一份"按码分类"的分支（那会造出第二份口径）。

### 3.3 降级不阻塞核心业务

`test_channel_downtime_does_not_block_new_submissions`（真组合根 + 真 MySQL 的 `TestClient`）：

1. **先把通道打到不可用**：真调一次 mock 通道的 `MockFault(kind="error")`，当场拿到
   `ProviderChannelFailureError`（`code == 4003`）——"降级状态"是**观测到的**，不是用例假定的；
2. **不可用期间提交新任务**：`POST /aicore/ocr` ⇒ **202 + `taskId`**，且库里那行是 `PROCESSING`；
3. **附带一条分辨性断言**：本次受理**不产生任何失败码**（`_counts_by_error_code == {}`）
   ——把"受理不阻塞"与"失败计数"两件事分开，免得两者混成一个信号。

**M1 的边界（如实登记）**：M1 的受理路径**不调通道**（`handlers={}`、没有 OCR 执行），
故这条判据证明的是"**受理链路不被通道健康状态阻塞**"（它压根不查询通道状态）。
端到端形态（真通道失败 → 任务 `FAILED(4003)` → 期间新单仍被受理）由**两条用例共同**覆盖：
上一条证明失败被正确分类，本条证明受理不受影响。**MUST NOT** 被读成"真的有一个降级开关
被拨动过"——M1 没有那个开关。

### 3.4 两条异常路径分别触发（工单 §5 要求写明"怎么做的"）

`test_timeout_path_comes_from_a_real_timeout_not_a_reused_channel_failure` 分两段：

1. **来源对**（不碰执行器）：真调 mock 通道的两种故障，断言
   - `MockFault(kind="error")` ⇒ `isinstance(exc, ProviderChannelFailureError)` 且 `exc.code == 4003`；
   - `MockFault(kind="timeout")` ⇒ `isinstance(exc, ProviderTimeoutError)` 且 `exc.code == 5002`；
   - **并断言超时那个 `not isinstance(..., ProviderChannelFailureError)`**——两者是**兄弟类**
     （`ProviderChannelFailureError` 继承 `ChannelFailureError`、`ProviderTimeoutError` 继承
     `DependencyTimeoutError`），谁把超时路径改成"抛通道失败"，这一条当场红；
2. **落库对**（真执行器 + 真库）：用超时那条再跑一次，断言该行
   `status='FAILED'`、`error_code='5002'`。

**为什么用 `MockFault` 而不是"处理器里 `raise ChannelFailureError(...)`"**：前者是**通道层真实抛的**
异常（`_enter` 的故障分支），执行器与写回路径两端都是生产代码；后者是替身直接抛，
把"通道 → 执行器"这一段换掉了——而这一段正是本任务要验的。

### 3.5 没有任何代码路径把任务置成 `MANUAL_REVIEW`（机械判据）

`tests/structural/test_no_manual_review_writes.py`：

- `manual_review_write_targets(tree)` 扫**全 `src/`**，只看白名单里的**写回调用**
  （`update_status` / `status_update_statement` / `mark_failed` / `mark_succeeded` /
  `requeue` / `begin_attempt` / `_write_back`）的**实参**：
  **标识符**（`status=MANUAL_REVIEW`）与**字符串字面量**（`status="MANUAL_REVIEW"`）两种形态都拦；
- **取窄是刻意的**（与裁定逐字一致）：`state.py` 定义它、`ALLOWED_TRANSITIONS` 包含它、
  `api/tasks.py` 的读侧 `Literal`/`DECLARED_STATUSES`、`models.py` 的 `Enum(...)` 列定义
  ——**全部合法**，判据一律不拦；
- **判别力自证**：内存变异 `repository/task_lease_store.py` 的 `mark_failed` 里那行
  `status=FAILED_STATUS` → `status=MANUAL_REVIEW`（**标识符**）与 `status="MANUAL_REVIEW"`
  （**字符串**）各一次 ⇒ 扫描函数**必须报出命中**；并用**未变异**的源码做阳性对照
  （MUST NOT 是"一律判红"）。

这条判据守的是"**将来才可能被违反**"的约定：M2 接视觉审核时最自然的动作就是顺手把
`4003` 接到 `MANUAL_REVIEW` 上，而那会推翻本条裁定且**没人会注意到**。

---

## 4. 判别力自证（工单 §3 末段点名的那条，**能判红**）

| 变异（**内存变异，文件从不被写**） | 结果 |
|---|---|
| `core/task_runner.py::_handle_failure` 的 `error_code=str(error.code)` → `'error_code="4003"'`（"都写死通道失败码"） | 变异体跑完同样两条任务后，库里**两个码都是 4003**（先断言变异生效）⇒ 同一份判据 `_assert_codes_are_separated` **必红**在"两个码被写成了同一个"、`_assert_counts_are_separated` **必红**在"分组的计数" |

复现的正是要防的形态：`design.md:210` 逐字要求「外部通道失败与依赖超时**分别计数**，
避免把『通道挂了』误判成『任务有问题』」——写死一个码会让两个视图合并、运维失去区分能力。

**为什么这条自证是"内存变异"而不是改文件**：`core/task_runner.py` 在本工单的"不许改"清单里，
且工单纪律要求变异一律在内存里（`read_text` → `replace` → `compile` → `exec`，
工作树里的 `.py` 从头到尾没被写过）。

---

## 5. 交付物与门禁

### 5.1 文件

| 文件 | 行数 | 内容 |
|---|---|---|
| `tests/integration/test_failure_codes_mysql.py` | **457（新建）** | §3.1/§3.2/§3.3/§3.4 四条判据 + §3.6 的判别力自证（真 MySQL + 真 Redis + 真 mock 通道故障） |
| `tests/structural/test_no_manual_review_writes.py` | **149（新建）** | §3.5 的机械判据 + 它的判别力自证 |

**生产代码零改动**（`git status` 只有这两个新文件 + 既有的无关 `.sdd-tools.py`）。

### 5.2 验收命令的原始输出（全部满绿）

```powershell
cd D:\progrom\.worktrees\aicore-architecture\services\aicore
. .\.venv\Scripts\activate.ps1
```

```
$ python -m pytest -p no:cacheprovider -o addopts="" -m "not integration" -q
1325 passed, 13 skipped, 58 deselected, 1 warning in 54.14s
```

> 1323 → **1325 passed**（+2 = §3.5 的两条结构判据）。

```
$ python -m pytest -p no:cacheprovider -o addopts="" -m "integration" -q
58 passed, 1338 deselected in 30.21s        # 连跑 3 次：58 passed / 0 skipped ×3
```

> 54 → **58 passed**（+4 = 本文件的四条判据），**0 skipped**。
> **一处按工单要求逐条登记的 skip**：某一次运行的 `-rs` 显示
> `SKIPPED [1] tests/repository/test_apply_ddl_mysql.py:317: 随机值碰巧是纯数字，本用例只验证非数字月份被拒`
> ——那是**既有的、用例自己声明的随机 skip**（随机生成的月份恰好全为数字时该用例不适用），
> 与本任务无关，随后连跑 3 次均 `0 skipped`。

```
$ ruff check --no-cache src tests scripts
All checks passed!          EXIT=0

$ mypy --strict src
Success: no issues found in 62 source files

$ lint-imports --config .importlinter
Contracts: 4 kept, 0 broken.

$ python scripts/group3_acceptance.py
结果：PASS 10 / FAIL 0 / INFO 0

aicore:* = []   dbsize = 0        # 连跑 3 次集成段之后复核
```

> **残留处置（如实登记）**：本轮早期一次失败的中间运行（异步/同步循环混用的 teardown 崩溃）
> 在 Redis 上留下 **2 个 `:attempts` 键**（清理由夹具的终结器负责，那次没跑到）；
> 发现后按前缀 + 任务号**精确删除**（MUST NOT `FLUSHDB`），随后连跑 3 次集成段并复核
> `aicore:* = []`、`dbsize = 0`。

---

## 6. 没做到的事（如实写）

1. **降级开关本身不存在**（§3.3 的 M1 边界）：`handlers={}` ⇒ 没有真实 OCR 执行，
   故"通道不可用期间"是**用例构造**的（真调通道拿到 4003），不是"生产里某个开关被拨动了"。
   端到端的降级链路（真通道失败 → 任务 `FAILED(4003)` → 新单仍受理）由本文件两条用例**共同**覆盖；
   **"降级状态可观测"里"状态"那一半**（熔断器开/半开、`provider/guard.py` 的状态）
   归 Task 4.3 的护栏用例与第 11 组的指标，**本任务没有新增观测点**。
2. **指标没接**：`design.md:98` 的 Prometheus counter 属第 11 组；本任务只保证事实源可分
   （§3.2 的登记写了接法）。
3. **`4003` 的"转人工队列"没有实体**：按裁定 (a) 它是**查询视图**
   （`WHERE status='FAILED' AND error_code='4003'`），M1 **不新建队列表、不新增状态**——
   我没有建任何表/列/状态，这是**裁定要求**而不是遗漏。
4. **第一次写的两个同步用例把 Redis 夹具弄崩了**（`asyncio.run()` 另起循环 ⇒
   `redis_store` 的异步终结器在已关闭的循环上收尾：`AttributeError: 'NoneType' object has no
   attribute 'send'` + `RuntimeError: Event loop is closed`）。已改成 `async def` 用例
   在**同一个循环**里 `await`（与 `test_runner_redis.py` 同口径），并把这条例律写进了
   `_run_one_task` 的 docstring。
