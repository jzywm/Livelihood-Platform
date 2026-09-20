# Task 4.9 报告：任务提交幂等与跨账号越权拦截

**基线**：HEAD `98dbb1f`（第 5 批已提交，工作树干净）
**工单**：`task-4.9-brief.md`（目标逐字取自 `tasks.md:45`）
**交付形态**：1 个提交（建议 `feat(aicore): 并发同键提交回读原任务，并补严越权不泄露的判据`）
**纪律**：未 `git add` / `git commit`；探针 **0 个新文件**（`D:\progrom\.dsh-probe\` 为空）；
判别力自证两处（本工单点名）**都能判红**，见 §4。

---

## 0. RECON（**先读代码，再动手**）

### 0.1 已有什么（T1 铺好的机制，逐项给出落点）

| # | 机制 | 落点 | 现状 |
|---|---|---|---|
| 1 | **幂等键派生**（显式优先 / 否则 `sha256(imageKey ␀ docType)[:32]`；空白当没给；`len>64` → `ParamError(1003)`，MUST NOT 截断） | `service/task/submit.py::compute_idem_key` | ✅ 完整，四条硬约束写在 docstring 里 |
| 2 | **幂等查询**（`uk_idem(account_id, idem_key)`、同月表、账号必填） | `repository/task_repo.py::find_by_idem_key` | ✅ 有；`require_shard_key` 校验两参 |
| 3 | **提交编排**（先查幂等 → 命中即返回且**不改任何列** → 否则 `new_task` + `insert` → **写后立即读**） | `service/task/submit.py::submit_ocr_task` | ⚠️ 1~4 步完整；**并发分支缺失**（见 0.2 G1） |
| 4 | **受理回执**（202 + `TaskAccepted{taskId, status:"PROCESSING"}` + 信封 `code=0`） | `api/ocr.py` | ✅ 有；准入（`assert_submittable`）在落库之前 |
| 5 | **越权判定**（先取行 → `3006`；再比账号 → `ForbiddenError 2002`） | `service/task/query.py::load_owned_task` | ✅ 有；顺序与理由写在模块 docstring |
| 6 | **输出白名单**（`TaskSnapshot` 只装 7 列：`account_id`/`idem_key`/`model_meta`/`is_eval_sample` 根本不进） | `service/task/query.py::snapshot_of` | ✅ 有（结构性保险） |
| 7 | **会话选型**（提交 `write_session()`、轮询 `primary_read_session()`） | `api/ocr.py::_submit_in_session` / `api/tasks.py::_load_in_session` | ✅ 有；已有 AST 判据钉住 |
| 8 | **openapi 声明** | `docs/openapi.yaml:54`（同 imageKey+docType 返回原任务号 + `Idempotency-Key` 头）、`:113`（跨账号报 2002）、`TaskAccepted:780`、`TaskResult:787` | ✅ 与实现逐字对齐 |
| 9 | **已有用例** | `tests/api/test_ocr_submit.py`（11 条）、`tests/api/test_task_poll.py`（12 条） | 见 0.2 的缺口 |

已覆盖的行为（**不重复造**）：显式键幂等、派生键幂等（含派生口径本身）、不同 `docType` → 不同任务、
不同账号同图 → 不同任务（且 `idem_key` 相同 ⇒ 账号没被拼进键）、月边界跨月不幂等（设计）、
`X-User-Id` 缺失/空/空白 → 401 且零落库、`docType` 非法与 `imageKey` 缺失 → **400（不是 422）**、
`scene` 校验但不落库、注册表闸门真的在链路上、404/3006、跨账号 403/2002 + `data is None`、
账号过滤双向对照、openapi 字段集现读比对、会话入口 AST 扫描。

### 0.2 缺什么（**本任务的活**，逐项）

| # | 缺口 | 依据 | 本任务处置 |
|---|---|---|---|
| **G1** | **并发同键提交**：`find` 与 `insert` 之间没有冲突处置，第二个 `insert` 撞 `uk_idem` → `IntegrityError` → `5000`（T1 自己登记的已知缺口） | `spec.md:25`「重复提交 MUST 幂等，返回**原任务标识**而不重复产生任务与调用费用」 | **FIXED**（§2） |
| **G2** | **幂等的"调用费用"代理判据**缺失：全仓没有把"提交两次 ⇒ 可领取任务只有一条 ⇒ 处理器只被调用一次"串起来的用例 | 工单 §2.1（字面判据在 M1 无处落点，用等价形态） | **FIXED**（§3.1）；字面版（真 Provider 调用次数）**登记待第 5 组** |
| **G3** | **越权判据不够严**：只断言了 8 个**字段名**不出现 + `set(body) <= {5 字段}`（子集），没有"字段集合恰好"与"**业务取值**不出现"；**没有判别力自证** | `spec.md:35`「不泄露该任务的**任何**结果内容」 | **FIXED**（§3.2） |
| **G4** | **"键写死"的判别力自证**缺失：`test_different_doc_type_makes_a_different_task` 是行为判据，但没有"把 key 写死 ⇒ 必红"的证据 | 工单 §2.4 | **FIXED**（§3.3） |
| **G5** | 真 MySQL 上的 `uk_idem` 联合唯一 / 真并发 / 写后立即读走主库 | 工单 §4 的验收命令 | **待 MySQL**（§5，**不用沙盒顶替**） |

**结论**：本任务**不是重写**——机制已在，缺口集中在"**并发分支**"与"**判据的强度**"两处。

---

## 1. 交付物（行数取自交付后重算）

| 文件 | 行数 | 改动 |
|---|---|---|
| `services/aicore/src/aicore/service/task/submit.py` | 332 | **G1**：`IntegrityError` → 回滚 → 回读 → 返回原任务；新增 `_resubmit_after_key_conflict`；把"已知缺口"那段 docstring 改成"并发同键"的处置口径 |
| `services/aicore/tests/api/test_ocr_submit.py` | 614 | **G2/G4**：计数 handler 用例、并发冲突用例、"键写死"自证；把第 13/14 条的判据抽成 `_assert_distinct_tasks` |
| `services/aicore/tests/api/test_task_poll.py` | 578 | **G3**：越权判据抽成 `_assert_denial_leaks_nothing` 并补严（字段集合恰好 + 取值不出现）；新增"码对但泄露"的内存变异自证；会话入口扫描扩到 `submit.py` |

**改了 2 个既有测试文件**（工单允许，逐条说明）：

1. `test_ocr_submit.py` 的第 13/14 条**只把内联断言换成对 `_assert_distinct_tasks` 的调用**，
   语义逐字不变（每一条断言都还在，只是从两处内联变成一处共用）——目的是让 §3.3 的自证
   与真判据**是同一份**；
2. `test_task_poll.py` 的第 22 条**判据变严**（子集 → 恰好、字段名 → 取值），
   并把它抽成 `_assert_denial_leaks_nothing` 供自证复用；`test_session_entries_match_the_declared_split`
   增加一条对 `service/task/submit.py` 的断言（它 MUST NOT 自己开会话）。
   两处都是"**补严**"，没有删除任何既有断言。

---

## 2. G1 的修法与依据（并发同键 → 回读原任务）

### 2.1 改了什么

```python
try:
    repo.insert(session, task)
except IntegrityError:
    if effective_key is None:      # 没有幂等键就撞不到 uk_idem ⇒ 别的约束失败，原样上抛
        raise
    absorbed = _resubmit_after_key_conflict(session, repo, shard=..., account_id=..., idem_key=...)
    if absorbed is not None:
        return absorbed            # 回读到了原任务 → 返回它（created=False）
    raise                          # 读不到 ⇒ 原样重抛（不把写失败伪装成幂等命中）
```

`_resubmit_after_key_conflict` 做三件事，缺一条都会变成"看起来收口了、其实没有"：

1. **`session.rollback()`**：`IntegrityError` 之后会话处于"失败事务"状态，
   不先回滚后面的 `SELECT` 会被驱动/ORM 直接拒绝；
2. **用同一个会话回读**——它来自 `factory.write_session()`（**主库**）：
   `er.md:287` 逐字「关键**写后立即读**（任务提交后立即轮询）**强制走主库**，避免主从延迟读到旧状态」。
   另开只读会话有可能读到从库的空结果，于是"回读为空 ⇒ 重抛"变成常态——**收口反而把并发冲突变回 5000**；
3. **回读带 `account_id` + 同一个分片月**（`uk_idem` 是两列；月必须与插入同源，
   否则去另一张表里找一个不在那里的行）。

成功吸收时记一条 **INFO**（不是 WARNING）：这是设计内的并发形态、且已正确收口。

### 2.2 依据

| 依据 | 逐字/口径 |
|---|---|
| `spec.md:25` | 重复提交 MUST 幂等，返回**原任务标识**而不重复产生任务与调用费用（并发重复是"重复提交"的一种） |
| `er.md:22` / `:325` | `idem_key` `uk_idem(account_id, idem_key)` **NULL 豁免（同月表内唯一）** |
| `er.md:287` | 关键「写后立即读」强制走主库 |
| `repository/base.py::_insert` | 「不 `commit()`、不 `flush()`：事务边界归调用方」⇒ 在 service 里回滚是**在职责内**的 |

---

## 3. 判据（新增/补严）

### 3.1 §2.1 幂等的"调用费用"代理判据

`test_duplicate_submit_yields_one_claimable_task_and_one_handler_call`，三件事一起断言：

1. `ai_task` **只多一行**；
2. 第二次返回**原 `taskId`**；
3. **可领取任务只有一条**（用执行器自己的 `SqlTaskLeaseStore.list_claimable` 取窗口）
   ⇒ 把它交给**计数 handler** ⇒ `handler.calls == [task_id]`。

**为什么不用 `runner.run_once()`**：它用执行器自己的墙钟算分片月（今天是 2026-09），
而沙盒只有 `ai_task_202607`/`202608`；执行器的时钟**没有注入点**（A9 刻意删掉了
`TaskRunner(clock=)`）。故显式传 `now=JULY` 给执行器自己的窗口函数，再按执行器的顺序执行。
理由写在用例 docstring 里。

### 3.2 §2.3 越权不泄露：**从"字段名不出现"补严到"取值不出现"**

判据本体 `_assert_denial_leaks_nothing(response, forbidden_values=…)` 五条：

| 断言 | 挡住的形态 |
|---|---|
| `status_code == 403` | 越权被判成 404（与"不存在"混同） |
| `code == 2002` | 状态码对但业务码写错 |
| 字段集合**恰好**是信封那五个 | 顺手多带 `detail` / `task` / `result` |
| `data is None` | **"码对但把结果塞进 `data`"**（§2.3 点名要防的那类） |
| `forbidden_values` 一个都不出现 | 把状态/结论写进 `message` 或别的字段 |

为了让第 5 条有判别力，用例先用裸 SQL 把这行改成**有辨识度的终态**
（`FAILED` / `4003` / `progress=100` / `finished_at`），再断言
`{task_id, account_id, "FAILED", "4003", FINISHED_AT_ISO}` 在响应里**一个都不出现**。

### 3.3 §2.4 键来源的两条路径 + 阴性判据

- 显式 `Idempotency-Key`（第 11 条）、派生键（第 12 条）、**不同 `docType` → 不同任务**（第 13 条）、
  不同账号 → 不同任务且 `idem_key` 相同（第 14 条）——**四条都已存在**，本轮只把 13/14 的
  判据抽成 `_assert_distinct_tasks`（供 §4.2 的自证复用）。

### 3.4 §2.2 的会话口径补充判据

`test_session_entries_match_the_declared_split` 增加：`service/task/submit.py` 的会话入口集合
MUST 为空（"回读走调用方给的主库会话"在源码层可机械检查）。

---

## 4. 判别力自证（工单点名的两处，**都能判红**）

### 4.1 §2.3「码对但把结果塞进 `data`」→ 判据变红

`test_cross_account_leak_guard_discriminates`：把 `core/errors.py::_error_body`
（失败响应的**唯一** body 构造器）在**内存里**换成"顺手把上下文带上"的版本 ⇒ 响应路径真的产出
`403 + 2002 + data 带行内容 + message 带 taskId`。

- ① 先断言变异**生效**（仍是 403/2002、`data is not None`）——即"**码是对的**"；
- ② 再把**同一个场景**喂给 `_assert_denial_leaks_nothing` ⇒ **必须抛**，且红在 `data` 那一条
  （`match="data 必须是 null"`，不是别的偶然原因）。

**只断言状态码的判据对它是绿的**——这正是要防的形态，也是本条自证的意义。

### 4.2 §2.4「键写死」→ 阴性判据变红

`test_hard_coded_idem_key_guard_discriminates`：把 `submit.compute_idem_key` 在内存里换成
**恒返回常量**的实现 ⇒ 同一账号、同 `imageKey`、**换 `docType`** 的两次提交拿到**同一个 `taskId`**
（变异生效）⇒ 把这两次响应喂给 `_assert_distinct_tasks`（**与第 13 条逐字同一份判据**）⇒ **必须抛**
（`match="同一个 taskId"`）。

### 4.3 §2.2 的冲突路径自证（本轮新增判据自身的判别力）

`test_racing_duplicate_submit_returns_the_original_task` 的"成因断言"（日志里出现
「撞了 uk_idem …… 已回读」）就是这条的判别力：若哪次改动把 `except IntegrityError` 整段删掉，
响应会变成 5000（第 1 条断言红）；若回读逻辑被换成"直接返回刚造的那个 task"，
日志与行数断言会红。

---

## 5. 待 MySQL 起来后补（**MUST NOT 用沙盒顶替**）

| 待补项 | 为什么沙盒顶替不了 | 起来后怎么补 |
|---|---|---|
| **真 `uk_idem` 联合唯一**（MySQL 8 + 原生 ENUM + 真 DDL 的 `UNIQUE KEY`） | 沙盒的表是从 `models.py` 复制的 sqlite 表，**约束语义同源但实现不同**（且沙盒抹掉了时间类 `server_default`） | `@pytest.mark.integration`：真库上同键插两次 → 断言 `IntegrityError` 与 `find_by_idem_key` 命中同一行 |
| **真并发**（两个连接同时提交同一键） | sqlite 沙盒是 `StaticPool` **单连接**，"并发"在那里被序列化，撞不出来 | 两个线程各开一个 `write_session()` 同时 POST，断言**两个响应都 202 且 `taskId` 相同**、库里一行 |
| **回读走主库的端到端验证** | 本机**只有主库**（`EngineFactory` 回落主库并记日志），没有从库可对照 | 起一个从库（或把 `read_engine` 指向延迟从库）后：断言冲突回读**没有**走从库（`read_session()` 被调用即失败）——**当前环境下这条无法验证**，而它在结构上已由 §3.4 的 AST 判据钉住 |
| **§2.1 的字面版**（真 Provider 的调用次数） | M1 的受理路径不调 Provider（`handlers={}`、`ocr_service.py` 是空壳） | 第 5 组注入真 OCR 处理器后补一条端到端用例（工单 §2.1 要求登记） |

> 本轮**没有**用沙盒结果声称上述任一条通过；§4.3 的沙盒用例只覆盖**冲突分支的处置逻辑**，
> 它的 docstring 里逐字写明了这一点。

---

## 6. 验收命令的原始输出

```powershell
cd D:\progrom\.worktrees\aicore-architecture\services\aicore
. .\.venv\Scripts\activate.ps1
```

### 默认段

```
$ python -m pytest -p no:cacheprovider -o addopts="" -m "not integration" -q
1298 passed, 13 skipped, 50 deselected, 1 warning in 55.08s
```

> 1294 → **1298 passed**（+4：§2.1/§2.2/§2.4 各一条 + §2.3 的自证一条）。

### 集成段（**MySQL 未运行 ⇒ 不完整**）

```
$ python -m pytest -p no:cacheprovider -o addopts="" -m "integration" -q
25 passed, 25 skipped, 1307 deselected      # 25 条 skip 全部是 "Can't connect to MySQL … 10061"
```

### ruff / mypy / lint-imports

```
$ ruff check --no-cache src tests scripts
All checks passed!          EXIT=0

$ mypy --strict src
Success: no issues found in 61 source files

$ lint-imports --config .importlinter
Contracts: 4 kept, 0 broken.
```

### 第 3 组验收脚本

```
$ python scripts/group3_acceptance.py
结果：PASS 9 / FAIL 1 / INFO 0      # FAIL = 第 1 项「DDL 在真实 MySQL 8 执行」（MySQL 停摆）
```

---

## 7. 没做到的事（如实写）

1. **§5 的四条待补**：MySQL 停摆（`Get-Service MySQL` → Stopped，`Start-Service` 需管理员权限）。
   本轮**没有**用沙盒顶替其中任何一条。
2. **§2.1 的字面判据**（真 Provider 调用次数）按工单登记，待第 5 组 K-01。
3. **"回读走主库"在网络层没有被验证**：本机没有从库可对照；结构层判据（§3.4）+ 行为层
   冲突用例已就位，但没有"真的读到了从库的旧值"这种反例可造。
4. **`test_racing_duplicate_submit_returns_the_original_task` 不是真并发**：它把竞态在代码视角下
   的形态（`find` 返回 `None` → `insert` 撞唯一键）确定性地复现出来。真并发那条在 §5。
5. **未动** `provider/**`、`core/lease.py`、`core/task_runner.py`、`core/errors.py`、
   `core/config.py`、`.importlinter`、`pyproject.toml`（工单"不许改"清单）。
   `repository/task_repo.py` **没有改**——本轮不需要新查询（`find_by_idem_key` 已够用）。

---

# Task 4.9 收口（MySQL 已启动后的第二轮）

**触发**：控制者确认 MySQL 已起（CMD3 `50 passed / 0 skipped`、验收脚本第 1 项转绿），
要求补齐 §5 的待办（**第 4 条不做**）并补一条"回读为空 ⇒ 重抛"的判据。

## 8. §5 待办的收口（①②③）

| # | 状态 | 落点与判据 |
|---|---|---|
| **①** 真 `uk_idem` 联合唯一 | **FIXED（真库实测）** | `tests/integration/test_submit_mysql.py::test_real_uk_idem_rejects_the_second_row_and_the_repo_reads_the_first`：**真 DDL 的真唯一键**上同 `(account_id, idem_key)` 插第二行 → `IntegrityError` 且**报错信息里出现 `uk_idem`**（证明拦它的是那个索引，不是主键）；随后 `find_by_idem_key` 回读到**第一行**、真库里恰好一行 |
| **②** 真并发 | **FIXED（真库实测）** | 同文件两条：`test_concurrent_submits_from_two_connections_yield_one_task`（3 轮，每轮 2 个并发请求：两个 `202`、`taskId` 相同、库里一行）与 `test_a_widened_race_window_really_hits_the_conflict_branch`（把窗口加宽到**必然**撞，并用日志断言**成因**：确实走了"撞 `uk_idem` → 回读"那段） |
| **③** "回读走主库"的端到端 | **如实登记（无从对照）** | `test_primary_read_has_no_replica_to_compare_against`：本机 `mysql_readonly_host == mysql_host`（没有独立从库）⇒ **造不出"从从库读到旧值"这个反例**，故只钉两件真能钉的事：`service/task/submit.py` **不自开会话**（AST）+ **一旦真配了从库本用例立刻变红**，提示必须补真对照。**没有编一个对照出来** |
| **④** §2.1 字面版 | **不做**（控制者指示） | 属第 5 组 K-01，已登记 |

### 8.1 真并发怎么才算"真"（**实测踩过一次，值得后人读**）

第一版用 `TestClient` + 两个线程各 `post` 一次，并在 `find_by_idem_key` 里放 `threading.Barrier(2)`：
**15 秒后 `BrokenBarrierError`**——第二个请求根本没进到服务端。
即 **`TestClient` 是单 portal 的同步客户端，同时 `post` 会被串行化**。

改用 **`httpx.ASGITransport` + `asyncio.gather`**：两个请求成为**同一个事件循环里的两个 task**，
路由在 `await run_in_threadpool(...)` 处让出 ⇒ 各自在线程池里开**独立会话**
（`factory.write_session()` ⇒ 连接池里各自一条连接）⇒ **两条连接同时在 MySQL 上执行**。
栅栏因此必定被满足（"加宽窗口"那条用例正是靠它才**必然**走到冲突分支）。

**第二处实测**：栅栏必须放在"**查完且没查到之后**"。第一版放在**查询之前**，
两个线程放行后仍各自去查，先查完的可能**已经把行插进去了** ⇒ 后查的直接命中、冲突没发生
（三条断言全绿，只有"成因"那条日志断言把我拦住了——**成因断言的价值就在这里**）。

## 9. 复核补漏：「回读为空 ⇒ 重抛」的判据（**FIXED**）

**问题**（复核者指出）：`if absorbed is not None: return absorbed / raise` 这条**安全分支**
此前**没有任何判据**——把"读不到也返回成功"改进去，全套测试照样绿，
而**一个根本没落库的任务会被当成创建成功返回给调用方**（回执给一个查不到的任务号，轮询永远 404）。

**判据**（`tests/api/test_ocr_submit.py`，**不需要真 MySQL**）：

- `test_conflict_without_a_rereadable_row_is_not_absorbed`：显式幂等键（⇒ 回读那一步真的执行）
  + **主键冲突**（先插一行占住即将生成的 `task_id`，那行 `idem_key` 是别的值）
  ⇒ `rollback` 后按 `(account_id, 幂等键)` 回读**必然为空** ⇒ **MUST 重抛**。
  判据本体 `_assert_conflict_was_not_absorbed` 两种观测形态都判：**异常形态**（`TestClient`
  默认 `raise_server_exceptions=True`，服务端未处理异常原样抛回 = "没吞掉"）与
  **响应形态**（吞掉了 ⇒ MUST 是 500/5000/`data is None`）；两种形态下都还要断言**库里没有幻影行**。
  另外用 `caplog` 断言确实记了 `code=5000`（"没吞掉"还必须意味着"信封把它报成了 5000"）。
- `test_conflict_safety_guard_discriminates`：**内存变异** `submit.py` 的吸收分支为
  "读不到就返回本次刚造的那个对象（`created=True`）" ⇒ 接口回 **202 + 库里不存在的 `taskId`**
  ⇒ 同一份判据**必红**，且红在「**本应抛出却返回了成功**」那一条上（`match=` 钉死成因）。

### 9.1 `effective_key is None` 那条重抛分支：**经 API 不可达**（已按控制者的两条路都做了）

- **判定**：不可达。`compute_idem_key` 的 docstring 逐字写着"当前实现永远不会返回 `None`"
  （显式键非空即原样返回，否则 `sha256(...)` 的 hex 切片）；经 API 更绕不到——
  `imageKey` 缺失会先被 `require_image_key` 挡成 `400/1001`。
- **处置**：**直接单元测那条分支**（绕过 API）：`test_none_idem_key_conflict_is_not_absorbed`
  显式注入"`compute_idem_key` 返回 `None`"+ 主键冲突 ⇒ 断言 `submit_ocr_task` **抛出
  `IntegrityError`** 而不是被吸收；用例 docstring 里**逐字写明它经 API 不可达**，
  MUST NOT 被读成"这条行为已被端到端覆盖"。

## 10. 收口后的验收命令（**全部满绿**）

```powershell
cd D:\progrom\.worktrees\aicore-architecture\services\aicore
. .\.venv\Scripts\activate.ps1
```

### 默认段

```
$ python -m pytest -p no:cacheprovider -o addopts="" -m "not integration" -q
1301 passed, 13 skipped, 54 deselected, 1 warning in 54.28s
```

> 1298 → **1301 passed**（+3：重抛分支的判据、它的自证、`effective_key is None` 的直测）。

### 集成段（真 Redis + 真 MySQL，**0 skipped**）

```
$ python -m pytest -p no:cacheprovider -o addopts="" -m "integration" -q
54 passed, 1314 deselected in 31.18s
```

> 50 → **54 passed**（+4：本文件新增的 ① 一条、② 两条、③ 一条）。
> **连跑 5 次：4 次 `54 passed / 0 skipped`，1 次 `53 passed / 1 skipped`**
> （瞬时探测失败，`-rs` 没赶上是哪一条；随后连跑 3 次均 0 skipped，未复现）。
> 这条如实登记：夹具的"探测式 skip"（`integration_engine_factory` / `redis_is_available`）
> 本身在这台机器上偶有抖动，与本任务新增的用例无关。
> 跑完核查：`aicore:* = []`、`dbsize = 0`、本月表里本文件账号的残留行 = **0**。

### ruff / mypy / lint-imports / 验收脚本

```
$ ruff check --no-cache src tests scripts
All checks passed!          EXIT=0

$ mypy --strict src
Success: no issues found in 61 source files

$ lint-imports --config .importlinter
Contracts: 4 kept, 0 broken.

$ python scripts/group3_acceptance.py
结果：PASS 10 / FAIL 0 / INFO 0
```

## 11. 交付物（第二轮增量）

| 文件 | 行数 | 改动 |
|---|---|---|
| `tests/integration/test_submit_mysql.py` | 393 | **新建**：真 `uk_idem`（①）、真并发两条（②）、"走主库无从对照"的如实登记（③） |
| `tests/api/test_ocr_submit.py` | 868 | 补"回读为空 ⇒ 重抛"的判据 + 自证 + `effective_key is None` 的直测（§9） |
| `services/aicore/src/aicore/service/task/submit.py` | 332 | **未变**（第一轮已修；第二轮全是判据） |
| `tests/api/test_task_poll.py` | 578 | **未变**（第一轮已补严） |

**建议 2 个提交**（控制者给的分法）：

1. `test(aicore): 真库上验 uk_idem 与并发同键提交`（`tests/integration/test_submit_mysql.py`）；
2. `test(aicore): 补严"回读为空 ⇒ 重抛"的判据与自证`（`tests/api/test_ocr_submit.py`）。

**没做到的事（第二轮）**：

1. **③ 的端到端对照**仍然没有——本机无从库，**没有编造**；只登记了"结构层已钉"与
   "一旦配了从库本用例会变红，提示补真对照"。
2. **真并发没有走真 HTTP 服务器**：用的是进程内 `ASGITransport`（真实 ASGI 应用 + 真实数据库
   连接，但不是 TCP）。要走真 TCP 得在测试里起 uvicorn——那会让集成段多一个端口与就绪等待，
   本轮**没有**做；如实登记。
3. **CMD3 的一次瞬时 skip**（见 §10 的说明），未复现。
