# Task 4.7 + 4.8 **修复轮**报告

**Worktree**：`D:\progrom\.worktrees\aicore-architecture`；服务根 `services/aicore/`
**依据**：`task-4.7-fix-brief.md`（第 1 批：B1/B2/B3/M1–M5）+ 第 2 批（A1–A9/R1/R2/R4/R5，
证据在 `review-task-4.7-independent.md`）+ 第 3 批（B2 结论更正 / A5(c) 补测 / 组合根装配用例）
**判据**：全部写成「**EXIT=0 且 failed == 0**」；报告里的每个数字**取自交付后重算**（见 §4）

---

## 0. 一行结论

七条验收命令**全部 EXIT=0**（`67 passed` / `1268 passed,13 skipped` / `41 passed` /
`ruff All checks passed` / `mypy Success` / `Contracts: 4 kept, 0 broken` /
`group3_acceptance PASS 10 / FAIL 0`）。

- **B1 / A1 / A2 都修了，且各自带"能判红的自证"**；
- **B2 修了，且本轮补上了真正的"能判红的自证"**——我上一轮"结构上不可能超过 1"的结论
  **被控制者的探针否证**，根因是**我自己那个测试替身的窗口语义**，不是 store 契约（见 §2.1）；
- **M1 的 5.01s ×2 消失**（现在 0.02s）；
- **B3 的 `error_code` 落库**；**A5(c) 的抛错本轮补上了真库用例**；
- **组合根的装配与关停顺序本轮补上了集成用例（4 条）**——那是此前几轮一直登记的最大空白。

---

## 1. 交付物（行数取自交付后重算，§4 说明口径）

### 新建（2 个）

| 文件 | 行数 | 说明 |
|---|---|---|
| `tests/repository/test_task_lease_store.py` | 149 | A7：就地状态字面量的多源一致性（8 条用例） |
| `tests/integration/test_main_assembly.py` | 312 | **本轮新增**：组合根装配 + 关停顺序 + A2 的关停块（4 条用例） |

### 修改（既有）

| 文件 | 行数 | 本任务改了什么 |
|---|---|---|
| `src/aicore/core/task_runner.py` | 1251 | B1 取消、B2 背压、A1 解析顺序、A2 有界退避、M2 删 `clock`、`registered_policy_types` |
| `src/aicore/core/lease.py` | 667 | A3 计数键到期 + TTL 校验、A4 `defer` 口径、A9 删死接口 |
| `src/aicore/repository/task_lease_store.py` | 436 | B3 落 `error_code`、A5(b) docstring 改准、A5(c) `rowcount==0` 抛错 |
| `src/aicore/repository/task_repo.py` | 202 | **授权改动**：`status_update_statement` / `update_status` 加**可选** `error_code` |
| `src/aicore/main.py` | 264 | A2：关停块 `try/except` + `_log_runner_death` done-callback |
| `tests/conftest.py` | 612 | A6 登记守卫第三条边界；`integration_settings(env=...)` 形参 |
| `tests/unit/test_lease.py` | 407 | A3/A4 的 12 条新用例（21 条） |
| `tests/unit/test_task_runner.py` | 1961 | B1/B2/A1/A2/M1/M5/R1 的用例 + 4 个变异体类（37 条） |
| `tests/unit/test_cpu_pool.py` | 357 | M3 改名、R2 真传 `None`（9 条） |
| `tests/integration/test_lease_redis.py` | 345 | A3 跨实现一致性（10 条） |
| `tests/integration/test_runner_redis.py` | 566 | B3 断言真实码值、R4 阳性对照、**A5(c) 真库用例**（8 条） |
| `tests/repository/test_repos.py` | — | **授权改动**：保留"不传时恰好三列" + 新增"传了时恰好四列" |

**用例总数（本任务相关 7 个文件）**：21 + 37 + 9 + 8 + 10 + 8 + 4 = **97 条**。

---

## 2. 逐项状态表（每项：状态 + 证据）

图例：`FIXED` = 改了 + 有用例；`ADDRESSED-BY-REFACTOR` = 重构后**实测**不再有该问题；
`STILL-PRESENT`；`DEFERRED` = 本轮按裁定不做，已登记。

| 项 | 状态 | 证据（新版本上的实测 / 代码位置） |
|---|---|---|
| **B1** 租约丢失即中止执行 | **FIXED** | `task_runner.py` 的 `execute`：处理器是 `create_task`，`asyncio.wait({handler, heartbeat}, FIRST_COMPLETED)`，`heartbeat in done → _dissolve_task(handler_task)`。<br>用例 `test_renew_failure_abandons_without_any_terminal_write`（两个参数）断言 ① `execute` < 0.5s 返回（实测 **0.02s**，处理器耗 1.0s）② `completed is False` ③ `paid_calls == 0` ④ 三类终态零调用。<br>**判别力自证** `test_lease_loss_cancel_guard_discriminates`：`_DetachedOnCancelHandler`（被取消时把工作挪到脱离的 task 上继续）**实测复现** `completed=True, paid_calls=1`。 |
| **B2** 领取受信号量约束 | **FIXED**（本轮**重做**判据） | `run_forever`：`await semaphore.acquire()` → `claim_once()`。<br>**行为判据** `test_leases_held_never_exceed_the_concurrency_limit`：`exclude_begun=True` 的窗口 + 事件闸住的处理器 + `concurrency_limit=1`，断言峰值租约 `<= 1`、`"task-b" not in acquire_calls`、`entered == ["task-a"]`；**阳性对照**放行后 `entered == ["task-a","task-b"]`（事件驱动）。<br>**判别力自证** `test_b2_guard_discriminates` 本轮实测：<br>`shipped  peak_leases=1  acquire_calls=['task-a']`<br>`pre-fix  peak_leases=2  acquire_calls=['task-a','task-b','task-b',…]`<br>**补充** `test_run_forever_acquires_the_permit_before_claiming`（AST 顺序判据，**已不是唯一判据**）。 |
| **B3** `error_code` 落库 | **FIXED** | `task_repo.py` 的 `status_update_statement(error_code=None)`：**仅非 None 时**进列清单。用例 `test_status_update_statement_sets_error_code_when_given`（传了恰好四列 + 值正确）+ 原有 `..._only_sets_three_columns`（**未削弱**）。集成 `test_failure_backs_off_then_exhausts_to_failed` 断言 `row["error_code"] == str(CHANNEL_FAILURE_CODE)`。`mark_failed` 的 WARNING 已删。 |
| **M1** 假绿 + 5s 耗时 | **FIXED** | `--durations` 实测：该用例两个参数现在 **0.02s**（原 5.01s ×2）；它现在断言 `completed is False` + `paid_calls == 0`（判别力见 B1）。 |
| **M2** `TaskRunner(clock=)` 死接口 | **FIXED** | 形参、`_clock` 字段、`StepClock` / `system_clock` 导入全部删除；`__init__` docstring 写明**为什么时间不可注入**（写库只能墙钟、心跳必须真等）。测试侧 `clock=` 实参全删。 |
| **M3** 误导命名 + 恒真断言 | **FIXED** | 改名 `test_runner_module_has_no_blocking_sleep_calls`；删掉 `assert TaskClaim and InMemoryLockStore` 与那两个无用导入。 |
| **M4** 报告失准 | **FIXED** | §1/§4 的数字**全部取自交付后重算**（用 Python 数行，不用 PowerShell 的 `Measure-Object -Line`——它不计空行/末行，正是我上轮数字偏小的原因）。 |
| **M5** docstring 承诺不存在 | **FIXED** | 原用例已重写为 `test_leases_held_never_exceed_the_concurrency_limit` + `test_no_claim_happens_while_every_permit_is_busy`，两处 docstring 描述的都是**用例体里真的有的断言**。 |
| **A1** 心跳泄漏（`timeout_s()` 抛异常） | **FIXED** | `execute` 把 `handler` / `policy` / `declared_timeout` 的解析**全部前移到 `create_task(_heartbeat())` 之前**。用例 `test_handler_timeout_bug_does_not_leak_the_heartbeat`：① 异常照旧上抛 ② `asyncio.all_tasks()` 里没有 `_heartbeat` ③ `renew` 调用次数不再增长。<br>**判别力自证** `test_a1_guard_discriminates`：`_PreFixA1Runner`（解析放回心跳之后）**实测复现**心跳泄漏 + 继续续期。<br>两处假文案都改了（`TaskHandler.handle` docstring 的边界段、`_settle` 的日志）。 |
| **A2** 领取无兜底 / 关停块被跳过 | **FIXED** | ① `run_forever` 的 `claim_once()` 包在 `try/except Exception` 里：记 ERROR（含"连续第 N 次"）+ **有界**退避（`CLAIM_FAILURE_BACKOFF_BASE_S=0.5` → `..._MAX_S=30.0`）+ **可被 `stop` 打断**（用 `stop.wait()` 当计时器）。<br>② 用例 `test_transient_claim_failure_does_not_kill_the_loop`（循环没死 + 记了 ERROR + 之后仍领到任务）与 `test_claim_failure_backoff_can_be_interrupted_by_stop`（`stop` 后 < 0.5s 退出）。<br>③ **判别力自证** `test_a2_guard_discriminates`：`_PreFixA2Runner`（裸调 `claim_once`）**实测**被一次 `RuntimeError` 结束、且零日志。<br>④ `main.py` 关停块：`await runner_task` 包 `try/except`，异常记 ERROR 后**继续** `runner.stop()` → `locks.close()` → `dispose()` → `flush_logging()`。<br>⑤ `runner_task.add_done_callback(_log_runner_death)`：异常死亡**当场**记 ERROR（"进程仍存活但不会再领任务"）。 |
| **A3** 内存替身未建模计数键到期 | **FIXED** | `_increment_attempts` 改走 `live_attempt_counter`（唯一按 `expires_at` 判过期的方法，此前是死代码）。<br>离线段两条**成对**用例：`test_attempt_counter_expires_after_its_own_ttl`（`[1,1,1]`）+ `test_attempt_counter_does_not_expire_before_its_ttl`（`[1,2,3]`）。<br>**跨实现一致性**（评审要求的"两侧语义一致性用例"）：`test_attempt_counter_semantics_match_the_in_memory_store`——同一 TTL 下真 Redis 与替身**实测同序列**（集成段，真等 3×0.4s）。<br>`attempt_count_ttl_ms <= 0` 在**两侧构造期**都 `ValueError`（`test_attempt_count_ttl_must_be_positive` + `test_redis_store_rejects_non_positive_count_ttl`）。 |
| **A4** `defer` 三处口径打架 | **FIXED** | 三处统一到一个**可实现**的行为：`delay_s` 非正/非有限 → **不写键 + 清掉已有退避**（真 Redis 的 `PX 0` 是错误，故"写一个立即到期的键"这条路走不通）。<br>用例：`test_defer_with_non_positive_delay_does_not_defer`（0.0 / -3.0 / **nan** / inf 四个参数）+ `..._clears_a_previous_window` + 阳性对照 `test_defer_with_positive_delay_still_blocks`。**nan 的"永久退避"已消除。** |
| **A5(a)** docstring 声称原子性 | **FIXED** | `mark_failed` 的 docstring 改为「这是**写回旧快照**，读与写之间没有锁；评审实测丢失更新 `80 → 10`」，并写明它**不是**原子地保住并发写入。 |
| **A5(b)** 真修复（"不动这一列"） | **DEFERRED** | 按控制者裁定：要给 `update_status` 一个"不写 `progress`"的表达，属**共享列契约**，应与 5.x「处理器开始回写进度」一起设计。本轮不做，已在 docstring 与本节登记。 |
| **A5(c)** `rowcount == 0` 被丢掉 | **FIXED**（本轮补测） | `_write_back` 与 `mark_failed` 都检查返回值，`0` → 抛 `TaskRowMissingError`（新类，`RuntimeError` 系）。意义：此前执行器会以为写成功并**释放租约**，行留在旧状态等重放（可能重复付费）。<br>**本轮新增真库用例** `test_write_back_to_a_missing_row_raises`：把当月表建好、**不插那一行**，对不存在的 `task_id` 调四个写方法逐个断言抛错（并断言错误消息含任务号）；**反向对照**：行存在时 `begin_attempt` / `mark_failed` 正常写回（否则那四条可能只是"这个方法恒抛"的平凡真）。 |
| **A6** socket 守卫看不见异步建连 | **FIXED（登记）** | `tests/conftest.py` 的能力边界一节新增"### ⚠ 第三条边界"，含评审的原始探针输出（异步 0 条 / 同步 1 条）与**它为什么最容易被误信**（项目代码的出向调用全是 async，恰好全在盲区里）。按裁定**不真修**。 |
| **A7** 承诺指向不存在的文件 | **FIXED** | 新建 `tests/repository/test_task_lease_store.py`（8 条用例）：现读 DDL 的 `status` enum、`er.md` §6.1、ORM 模型、`service/task/state.py` 的常量，与就地字面量**逐字比对**。`task_lease_store.py` 的 docstring 同步指向它。 |
| **A9** `RedisLockStore.monotonic_now()` + `clock=` 死接口 | **FIXED** | 形参、`_clock` 字段、`monotonic_now()`、`StepClock` 导入全删；类 docstring 写明**为什么 Redis 侧不该有时钟**（过期判据唯一是服务端 `PX`）。 |
| **R1** 死断言（`if codes:`） | **FIXED** | 改为**参数化两条分支**：`max_retries=0` → `mark_failed` 且 `error_code=5002`；`max_retries=3` → `requeue` + 退避 1.0s 且 `mark_failed` 零调用、**不出现** `error_code=`。原来那行"业务码断言"在 requeue 分支上不可达（死代码），现已消除。 |
| **R2** 声称测 `None` 实际传自建池 | **FIXED** | `test_default_executor_path_still_runs_off_the_event_loop_thread` 直接 `run_cpu_bound(..., executor=None)`；辅助函数 `_run_with_none_executor` 删除。 |
| **R4** 只用否定断言 | **FIXED** | 集成用例加**阳性对照**：本月任务**在**结果里 + 下月任务**不在**结果里，同一次调用里一起断言。 |
| **R5** `select(table)` 取全部列 | **DEFERRED（只登记）** | 按裁定：M1 量级可忽略。 |
| **本轮①** 删 `extra_busy_permits` | **FIXED** | 字段与信号量里的减法都删了（`asyncio.Semaphore(concurrency_limit)`）。它有两个问题：① 生产接口上的测试专用字段；② 更要紧——它让"门判据"（`len(_inflight) >= concurrency_limit`）与"许可容量"**不一致** ⇒ 走到 `await semaphore.acquire()` 时许可数为 0，**那一行没有超时、`stop` 也打断不了它，执行器永久卡在那里**。删掉后两个数字重新恒等。`run_forever` 的 docstring 新增一节把这条**不变式**写下来（任何让两处不一致的改动都会造出永久卡死）。 |
| **本轮②** B2 判据换成行为判据 + 真自证 | **FIXED** | 见 B2 行。`exclude_begun=True` 是对 `TaskStore` 的**合法替身实现**，它让 running-count 判据**当场**有判别力（峰值 1 vs 2）。`test_no_claim_happens_while_every_permit_is_busy` **已被替换**（不是并存）；`test_run_forever_acquires_the_permit_before_claiming` 保留为**补充**判据。 |
| **本轮④** 组合根装配 / 关停用例 | **FIXED** | 新建 `tests/integration/test_main_assembly.py`（4 条）：<br>① `env="test"` **不装配**（`app.state` 无 `task_runner`；关停序列**只有** `dispose`——那一半更严，同时排除"装配了但没挂上"）；<br>② `env="dev"` 装配，且 `registered_handlers == ()`（M1 事实）+ `set(registered_policy_types) == set(REGISTRY)`；<br>③ 关停顺序**逐项**：`run_forever.start → run_forever.end → runner.stop → locks.close → dispose`；<br>④ **A2**：执行器异常死亡后清理仍跑完（实测序列 `['run_forever.raise','runner.stop','locks.close','dispose']`）+ 死亡留下 ERROR 日志；<br>⑤ 结构判据：`await runner_task` 在 `try` 里且 `except` 非裸 `raise`。<br>**边界（如实登记）**：这个文件**不验轮询**——记录版 `run_forever` 只等 `stop`，因为真轮询会在 `handlers={}` 下把真库里扫到的任何任务判成 `FAILED`（**改动别的用例共用的数据**）。"真的会领任务并执行"由 `test_runner_redis.py` 覆盖。 |

---

### 2.1 我上一轮关于 B2 的结论**是错的**（如实记录，MUST NOT 再写成那个更强的断言）

我上轮写：「`TaskStore.list_claimable` 的窗口宽度是 `limit = concurrency_limit`，
故『同时持有的租约数』在原契约下**对两种实现给同一个答案**」，并据此把运行期判据降级成
AST 顺序判据、把"能判红的自证"登记为做不到。

**控制者的探针否证了它**：

```
PROBE: running-count criterion vs loop shape  (store window excludes begun rows)
  (a) shipped run_forever      acquire 序列 ['task-0','task-1','task-2']   峰值租约 1
  (b) pre-fix shape            acquire 序列 ['task-0','task-1','task-1',…] 峰值租约 2
VERDICT: CRITERION DISCRIMINATES
```

**根因是我的替身，不是契约**：我的 `FakeStore` 把**已开工的行留在窗口里**，
于是许可满时窗口恰好只剩"自己领不到的那一行"。
而「**排除本轮已 `begin_attempt` 的行**」是对 `TaskStore` 的**另一种合法实现**
（"我自己正在处理的行，对我自己而言不是可领取的"）。
换成那种语义之后判据**立刻**有判别力：我在新版本上实测到的数字与控制者一致
（`shipped peak=1` / `pre-fix peak=2`，且后者的 `acquire_calls` 里 `task-b` 被反复尝试）。

**两处 docstring 里那句更强的断言已按控制者要求改掉**（`run_forever` 的
§"这个契约不依赖存储层谓词的副作用"、`test_run_forever_acquires_the_permit_before_claiming`
的理由段），并写明了教训：**「不可能」是替身的性质，不是契约的性质——
不要把某个测试替身的行为写成对接口的断言。**

顺带：我上轮自认易碎的"让出 400 轮"判据随之消失（新用例是**事件驱动**的）。

---

## 3. 验收命令的原始输出

```powershell
cd D:\progrom\.worktrees\aicore-architecture\services\aicore
$env:PYTHONUTF8='1'
```

### CMD1（`--durations=8`：**两条 5.01s 已消失**）

```
$ .\.venv\Scripts\python.exe -m pytest -p no:cacheprovider -o addopts="" tests/unit/test_lease.py tests/unit/test_task_runner.py tests/unit/test_cpu_pool.py -q --durations=8
...................................................................      [100%]
============================= slowest 8 durations =============================
1.02s call     tests/unit/test_task_runner.py::test_missing_handler_does_not_break_the_running_loop
0.52s call     tests/unit/test_task_runner.py::test_transient_claim_failure_does_not_kill_the_loop
0.34s call     tests/unit/test_task_runner.py::test_lease_loss_cancel_guard_discriminates
0.11s call     tests/unit/test_cpu_pool.py::test_criteria_discriminate_against_a_direct_call
0.10s call     tests/unit/test_cpu_pool.py::test_event_loop_keeps_running_while_cpu_work_is_in_flight
0.06s call     tests/unit/test_task_runner.py::test_a1_guard_discriminates
0.06s call     tests/unit/test_task_runner.py::test_begin_attempt_is_written_before_the_heartbeat_starts
0.06s call     tests/unit/test_task_runner.py::test_handler_timeout_bug_does_not_leak_the_heartbeat
67 passed in 2.65s
```

> 上一版这里的两条 **5.01s**（`test_renew_failure_abandons_without_any_terminal_write` 的两个参数）
> 现在都在 `--durations` 之外（< 0.005s 档，实测 0.02s）：它们不再靠 `timeout_s=5.0` 结束。
> 全文件从 11.75s 降到 2.65s。

### CMD2 默认段

```
$ .\.venv\Scripts\python.exe -m pytest -p no:cacheprovider -o addopts="" -m "not integration" -q
1268 passed, 13 skipped, 41 deselected, 1 warning in 48.18s
```

> 唯一那条 warning 是**既有的**（sqlite3 的 default datetime adapter DeprecationWarning）。
> 连跑 3 次全量确认稳定（`1268 passed` × 3）——B2 的新判据此前有一次全量下的假红，已修（见 §5.7）。

### CMD3 集成段（真实 Redis + 真实 MySQL）

```
$ .\.venv\Scripts\python.exe -m pytest -p no:cacheprovider -o addopts="" -m "integration" -q
41 passed, 1281 deselected in 48.69s
```

> 本任务新增的集成用例 **22 条**（`test_lease_redis.py` 10 + `test_runner_redis.py` 8 +
> `test_main_assembly.py` 4），**0 skipped**（Redis 与 MySQL 都真连上了）。
> 跑完核查：`aicore:* = []`、`dbsize = 0`。

### CMD4 ruff（完整范围 `src tests scripts`）

```
$ .\.venv\Scripts\ruff.exe check --no-cache src tests scripts
All checks passed!
EXIT=0
```

### CMD5 mypy strict

```
$ .\.venv\Scripts\python.exe -m mypy --strict src
Success: no issues found in 61 source files
```

### CMD6 import-linter

```
$ .\.venv\Scripts\lint-imports.exe --config .importlinter
api 层不得直接依赖 repository / provider KEPT
service 层只可与 provider.base 交互，不得依赖具体通道实现 KEPT (1 warning)
repository / provider / port 不得反向依赖 service KEPT
core 不得依赖任何业务层 KEPT
Contracts: 4 kept, 0 broken.
```

### CMD7 第 3 组验收脚本

```
$ .\.venv\Scripts\python.exe scripts\group3_acceptance.py
结果：PASS 10 / FAIL 0 / INFO 0
```

### Redis 残留

```
$ .\.venv\Scripts\python.exe -c "import redis; c=redis.Redis(decode_responses=True); print(list(c.scan_iter('aicore:*',count=1000)), c.dbsize())"
[] 0
```

---

## 4. M4 的数字怎么重算的（**两个因素**，我上轮只归了一个）

上轮我用 PowerShell 的 `(Get-Content $f | Measure-Object -Line).Lines` 数行——**它不计空行**
（`Measure-Object -Line` 只数"非空行"），于是每个文件都偏小，且**比值随各文件的空行密度而变**。
这解释了评审观察到的"比值逐文件不同（1.37~1.61）"。

**但口径错只解释了一部分**（控制者指出，我复核同意）：按"不计空行"的口径，
交付态 608 行的 `lease.py` 应是约 **480** 行非空，而我报告当时写的是 **394** ——
两者仍然差着一大截。故那批数字**同时也取自更早的版本**（实现中途取数、之后又改了不少）。
**两个因素都有**：口径错 + 取数时点早于交付态。别只归一个。

本轮改用 Python 的 `len(text.splitlines())`（与评审口径一致），
且表格里的数字**都取自交付后重算**（§1 的每一行都在最后一次改完之后重新数过一次）。
用例数同样重算：`pytest --collect-only -q` 逐个文件数（§1 的 97 = 21+37+9+8+10+8+4）。

---

## 5. 没做到的事（如实写，不美化）

1. ~~**B2 没有"能判红的自证"**~~ → **本轮已解决**（控制者的探针指出根因是我的替身）。
   保留下来的教训：我上轮把"我的替身做不到"写成了"契约上不可能"——那正是本组反复在修的
   那类毛病（把局部观察写成普遍断言）。已改掉两处 docstring，并把这件事写进 §2.1。
2. ~~**A5(c) 没有测试覆盖**~~ → **本轮已补真库用例**（控制者指出我漏了集成段那条路）。
3. ~~**`main.py` 的装配与关停没有集成用例**~~ → **本轮已补**（4 条，见 §2 本轮④）。
   **但仍有一条边界**：那个文件**不验轮询**（记录版 `run_forever` 只等 `stop`），
   因为在 `handlers={}` 下真轮询会把真库里扫到的任务判成 `FAILED`、**改动别的用例的数据**。
   「装配线 + 关停顺序」有了判据；「lifespan 里的执行器真的会领任务」**没有**——
   那条仍只由 `test_runner_redis.py`（自建执行器、不走 lifespan）间接覆盖。
4. **`_PreFixA1Runner` / `_PreFixA2Runner` / `_PreFixB2Runner` 是"复制控制流"的变异体**：
   它们与生产的差别是**人读出来的**（A1 是两行顺序、A2 是 `try` 的有无、
   B2 是"领取与许可的先后 + 那道门"），不是机器保证的。生产代码若在别处改动，
   这些变异体**不会自动跟上**——代价是自证可能随时间失真。
   替代方案（字符串变异 + exec）实测更糟：`task_runner.py` 上试过 3 次，
   三次都因缩进/锚点错位而报 `IndentationError`，且报错行号指向 exec 内部（难回推）。
   故保留现方案，并把代价登记在此。
5. **变异体 `_PreFixB2Runner` 必须"两处都还原"才等价**（去门 + 领取在许可之前）。
   只还原一处（我第一版就是）会让峰值停在 1、自证**假红**。
   这是"复制控制流"这类变异体的固有风险：**还原不彻底的表现是判据看着有判别力、
   实际没有**。已在它的 docstring 里写明这一点。
6. **A3 的跨实现一致性用例真等约 1.2s**（3 步 × 0.4s）。集成段允许真等且已带豁免，
   但它让 CMD3 变慢；若将来要压这个时间，得把 TTL 再调小（`PX` 精度与网络抖动会开始干扰）。
7. **`test_b2_guard_discriminates` 里仍有一段"让出 50 轮"**。
   它与行为判据不同：它**先**等到"`begin_attempt` 已记账"这个**事件**（有界循环），
   再让出若干轮等循环做完"该不该领第二个"这件事。后者无法用事件表达（要观察的正是
   "它会不会多领一个"），故保留按轮让出。**实测过一次全量套件下的假红**
   （线程池调度慢 → `begin_attempt` 未记账 → 变异体峰值停在 1），
   修法是先等事件再让出；此后连跑 3 次全量稳定。
8. **A5(b) 的丢失更新仍然存在**（按裁定 `DEFERRED`）：`mark_failed` 读到 `10` 之后
   并发写入 `80`，最终仍是 `10`。真正的修复需要 `update_status` 支持"不动 `progress`"。
9. **R5 未做**（`select(table)` 取全部列含 `model_meta`）：按裁定只登记。
10. **A6 的盲区仍在**：asyncio 的非环回建连对本守卫不可见。按裁定只登记。
    这意味着「provider 层全程无网络依赖」这条保证，**异步路径上目前只由源码级规则 5 兜住**。

---

## 6. 本轮新增的 `ai-allow-sleep` 豁免

全量豁免 **22 处**（验收脚本第 4 项 PASS，与上一版同数——本轮的替换是**等量**的：
删掉了旧的"让出 400 轮"，新增了 B2 行为判据/A5(c)/组合根用例里的几处）。逐条：

| 位置 | 理由（同行注释原文） |
|---|---|
| `test_task_runner.py:337` | 模拟处理器耗时 50ms，让心跳触发 |
| `test_task_runner.py:541` | 模拟处理器耗时（1.0s），由取消结束 |
| `test_task_runner.py:1098` / `:1104` | 0 秒，等 `begin_attempt` 落到替身账上 / 让出控制权给执行器协程 |
| `test_task_runner.py:1296` | 让出控制权给执行器协程（循环等待） |
| `test_task_runner.py:1362` / `:1363` | 0 秒，把控制权让给可能泄漏的心跳 task / 50ms，给泄漏的心跳足够时间再跑几轮 |
| `test_task_runner.py:1417` | 0 秒，把控制权让给执行器协程 |
| `test_task_runner.py:1458` / `:1460` | 0 秒，把控制权让给执行器协程 / 确保循环已进入退避等待 |
| `test_task_runner.py:1507` | 变异体心跳间隔 10ms，仅证明泄漏 |
| `test_task_runner.py:1582` | 让出控制权给执行器协程（循环等待） |
| `test_task_runner.py:1953` | 等脱离的处理器跑完（循环等待） |
| `test_cpu_pool.py:57` / `:109` / `:169` | 模拟 CPU 密集工作 0.1s / 定时协程 0.01s ×2 |
| `test_lease_redis.py:166` / `:298` | 集成段验真 PX 过期（1.1s）/ 验真 PX + 计数 TTL（每步 0.4s） |
| 其余 4 处 | `test_provider_guard.py` / `test_provider_mock.py` / `test_provider_selector.py` 的**既有**豁免 |

> `test_main_assembly.py` **没有**新增任何豁免：它的推进手段是**发一条真请求**
> （`client.get("/health")`），不是 `sleep`。

**探针纪律**：本任务累计共建 **5 个**一次性探针（`probe_bp.py` / `probe_mutant.py` /
`probe_anchor.py` / `probe_b1.py` / `count_lines.py`），全部位于仓库外
`D:\progrom\.dsh-probe\`，**已全部删除**（目录现为空）。
`tests/` 与 `src/` 下**无任何** `_probe*` / `_dsh*` 残留（含 `__pycache__` 里的 `.pyc`，已核）。

---

## 7. 提交计划（5 个；**MUST NOT 自行 `git add`/`commit`**）

| 提交 | 内容 |
|---|---|
| 1 `fix(aicore): 租约丢失即中止执行，且领取受信号量约束` | B1、B2（含新判据与自证、删 `extra_busy_permits`）、M1、M2、M5、M3、A9、R1、R2 |
| 2 `fix(aicore): 执行器不再被瞬时错误永久杀死` | A1、A2（含 `main.py` 关停块与死亡日志）、A6（守卫边界登记，同在 `conftest.py` 一档） |
| 3 `fix(aicore): 内存锁店与真 Redis 语义对齐` | A3、A4 |
| 4 `feat(aicore): 失败终态落 error_code，供 4.11 分别计数` | B3、A5(a)(b)(c)、A7、R4 |
| 5 `test(aicore): 覆盖执行器在组合根的装配与关停顺序` | 本轮④：`tests/integration/test_main_assembly.py` + `conftest.integration_settings(env=...)` 形参 + `TaskRunner.registered_policy_types` |

**需要拆 hunk 的地方**（控制者若要求每个提交单独 checkout 全绿）：
`task_runner.py` 被提交 1（B1/B2/M2/新增属性）与提交 2（A1/A2）同时改到；
`test_task_runner.py` 被提交 1 与提交 2 同时改到。
我这边**未做拆分**，`git add -p` 由提交者执行。

---

# 第 4 批（工单 `task-4.7-fix-brief-2.md` + 追加 `task-4.7-fix-brief-2-addendum.md`）

**基线**：HEAD `1fed477`（未改写任何既有提交；本轮全部落在工作树上，等控制者提交）
**纪律自检**：未 `git add` / `git commit`；未用「改 `src/` + `finally` 还原」做任何变异
（全部是**内存变异**：`_mutant_runner_class` / `_mutant_main`，文件从不被写）；探针 **0 个新文件**
（本轮所有验证都在已交付的用例里跑，`D:\progrom\.dsh-probe\` 仍为空目录，见 §B6）。

## B0. 一行结论

F1/F2/F3/F4/F5/F6/F7/F9/F10/F12/F13 + M1 + N1…N7 **全部 FIXED**（F8/F11 按工单 **REGISTERED**），
四条门禁 + lint-imports + 验收脚本 + Redis 残留全部干净；唯一"产品行为改动"是 **N1**（Redis 客户端
显式不重试，控制者裁定 (a)）与 **F9**（两侧在发命令前拒绝非法入参），两者都在 §B5 单列了理由与代价。

## B1. 逐项状态表

| 项 | 状态 | 证据（可判红的自证在哪） |
|---|---|---|
| **F1**（blocker）处理器抛非 `AiCoreError` 泄漏心跳 | **FIXED** | `test_programming_error_in_handler_does_not_leak_the_heartbeat`（①上抛 ②`renew` 不再增长 ③无 `_heartbeat` ④另一实例能领）；自证 `test_f1_f3_guard_discriminates`（内存变异回修复前结构 ⇒ 判据**必红**，实测红在"心跳仍在续期"） |
| **F2**（major）取消落在 `execute` 自己身上 | **FIXED** | `test_external_cancel_of_execute_does_not_leak_the_heartbeat`（`CancelledError` 原样传播 + ②③④）；自证 `test_f2_guard_discriminates` |
| **F3**（major）同步 `handle` / 缺属性 | **FIXED** | `test_sync_handle_...`（`TypeError`）+ `test_missing_handle_attribute_...`（`AttributeError`）+ ②③④；自证同 F1（参数化两态） |
| **F4** `nan`/`inf`/`<=0`/非数值 的 `timeout_s` | **FIXED** | `_declared_timeout_s` 五类声明一律不采用（见表）；`test_unusable_timeout_declaration_falls_back_and_still_times_out` 参数化 5 态，靠"把兜底值调到 0.05s + 挂死处理器仍在 5002 上超时"判红 |
| **F5** `_dissolve_task` 无上限等待 | **FIXED** | `test_dissolve_task_gives_up_after_a_bounded_wait`（①返回时间 ≤ 3×上界 ②超界记 ERROR ③确被取消过）；自证 `test_f5_bound_guard_discriminates`（摘掉 `wait_for` ⇒ 外层 `TimeoutError`，实测**红**） |
| **F6** 死亡日志断言被关停期日志满足 | **FIXED** | 判据本体 `_assert_death_logged_before_shutdown_tail`：**独有子串** `进程仍然存活` + `caplog.records` 上的**顺序**；自证 `test_death_log_criterion_discriminates`（合成"只有关停收尾"序列 ⇒ 必红；顺序反了也红；正序通过） |
| **F7** `await runner_task` 的 join 无判据 | **FIXED** | `_RecordingRunner` 在 `stop` 置位后还需 `_SETTLE_TURNS=3` 轮（`loop.call_soon` future 链，**无 sleep**）才记 `run_forever.end`；`_assert_shutdown_order` 要求 `run_forever.end` 早于 `runner.stop`；自证 `test_f7_shutdown_order_guard_discriminates`（内存变异成 `await asyncio.sleep(0)` ⇒ 实测**红**） |
| **F8** 关停块在"执行器被取消"时被整体跳过 | **REGISTERED** | `main.py` 关停块的 `except asyncio.CancelledError` 里写明这是**已知边界**（树内无生产者；取消语义就是"尽快停"，不宜在取消路径上继续 await 一串清理） |
| **F9** 替身比真 Redis 宽松 4 处 | **FIXED** | 新增 `InvalidLeaseArgumentError` + `_require_lease_ms`（两侧**同一个**函数）+ `_defer_delay_ms`（两侧同口径、按整毫秒截断）；用例：`test_acquire_rejects_lease_ms_redis_would_reject`（4 态）、`test_renew_rejects_...`、`test_defer_shorter_than_one_millisecond_does_not_defer`（3 态）、`test_defer_truncates_to_whole_milliseconds_like_redis`（`1.0009 → 1.000s`，在 `t=1.0005` 处两种实现给出**相反**答案 ⇒ 判据能分辨）；跨实现一致性扩到 3 条（`test_both_implementations_reject_the_same_lease_ms` / `..._truncate_defer_to_whole_milliseconds` / `..._do_not_defer_below_one_millisecond`）；过期边界比较符差异按 (b) **择一登记在模块 docstring §七** |
| **F10** "`error_code` 没有落库"的过期说明 | **FIXED** | `task_lease_store.py` §79-97 改为"**曾经的缺口，已闭合**"并保留成因；`test_runner_redis.py` 该函数 docstring 改为与 L349 的断言一致 |
| **F11** AST 判据可被仍错的代码满足 | **REGISTERED** | 四处 AST 判据的 docstring 都补了「**行为判据为主、AST 判据为辅**」+ 各自的已知弱点（B2 顺序、契约 4 import、`policy.timeout_s`、任务类型字面量）；关停块结构判据同措辞 |
| **F12(a)** `flush_logging()` 不可观测 | **FIXED** | 换记录版并进事件序列，`_assert_shutdown_order` 要求它**最后**一项（顺序判据里可见） |
| **F12(b)** `RunnerConfig` 取值无判据 | **FIXED** | 用例把 `Settings` 造成 `lease_ms=1234 / max_retries=7 / concurrency_limit=3`（**两两不同**），逐项断言 `runner.config.* == settings.*`；装配处对调即红 |
| **F12(c)** `SqlTaskLeaseStore` 注入无判据 | **FIXED** | `_RecordingTaskLeaseStore` 捕获构造实参，断言 `is not None` 且 `is app.state.engine_factory`（拿的是组合根自己那个工厂） |
| **F12(d)** marker/collection 事实 | **FIXED** | 见 N5：`addopts` 补 `-m "not integration"` + 新增 `tests/structural/test_pytest_config.py` 机械核对 |
| **F12(e)** 假 skip | **FIXED** | 见 N6 |
| **F12(f)** 删 `runner_stop.set()` 会挂死 | **FIXED** | 见 N7 |
| **F13** 固定让步轮数是判据本身 | **FIXED** | 3 处改成条件等待 + 有界 deadline：`_peak_leases` 的 `for _ in range(50)` → `_CountingStop` 数循环轮数（`_B2_REQUIRED_LOOP_ITERATIONS=3`）；A1 的 `for _ in range(40)` → 已随用例重写为 `_HEARTBEAT_OBSERVE_S` 有界窗口 + `renew` 计数不变；退避打断用例的 `for _ in range(5)` → 等**退避 ERROR 日志**出现（`caplog.records`）。`test_begin_attempt_...` 的"50ms 处理器 vs 10ms 心跳"5× 余量 → `RecordingLockStore.first_renew` 事件 |
| **M1**（最高优先）B1 招牌用例零杀伤 | **FIXED** | `_BadTurnHandler` 增 `stopped` 事件（`handle` 的 `finally` 置位），判据本体 `_assert_lease_lost_abandons` **先越过处理器本来的完成时刻再读 ②③**；自证 `test_m1_abandon_guard_discriminates`（内存变异：`if lease_lost or timed_out:` → `if timed_out:` **且**删掉 `finally` 里的 `_dissolve_task`）⇒ 实测**红在"处理器跑完了"**。与实测矛盾的 docstring 已重写 |
| **N1** "fails fast" 名不副实 + 25.18s | **FIXED（选 (a)）** | `RedisLockStore` 只传 `Retry(NoBackoff(), 0)`；该用例新增时延判据 `< 5s`。实测 **25.18s → 2.06s**（`--durations`）；理由与代价见 §B5 |
| **N2** 6 处"声称的判据 ≠ 实际判据" | **FIXED（6/6）** | ①`test_runner_redis.py` docstring；②`task_lease_store.py` 自相矛盾（=F10）；③`test_task_runner.py` 模块 docstring 的"没有 sleep / 没有轮询等待"改成**三类等待的真表**（3/5/4，合计 12）；④索引表第 7 行改指真实存在的 `test_leases_held_never_exceed_the_concurrency_limit`；⑤`test_cpu_pool.py` "共 2 处"→ 3 且删掉"唯一有真等待的地方"这句错话；⑥`test_lease_redis.py` "只有一处"→ 两处并列表写明。**机械判据**：`tests/structural/test_sleep_exemption_counts.py`（逐文件比对 docstring 声称数与 AST 实际数；只读文件用钉住的表核对） |
| **N3** 时序余量就是判据 | **FIXED** | 两处固定轮数 → 条件等待（见 F13）；`test_cpu_pool.py` 的"顺序**不受机器快慢影响**"改为"靠 **10× 余量**"并说明为什么保留（它要证的就是"同时发生的两件事谁先完成"，改成条件等待会把被测行为改掉）；`test_lease_redis.py` 的 1.1s 真等属集成段允许档（工单 §3.4 第 28 条） |
| **N4** 三处顺手的 | **FIXED** | ①Protocol 用例补**行为层**判据 `test_a_structurally_satisfying_object_can_really_be_injected_and_used`（不继承任何 Protocol 的三件套走完 领取→执行→写成功→释放 全链路，并逐项断言调用序列）；②删掉**恒真**的 `test_each_literal_is_a_non_empty_str`（参数化 3 条），在模块 docstring 里留痕说明删了什么、覆盖由哪四条现读判据承担；③`test_missing_handler_does_not_break_the_running_loop` 补 `poll_interval_s=0.0`（实测 1.02s 白等消失） |
| **N5**（授权改一行）`addopts` 补 `-m "not integration"` | **FIXED** | 仅改 `pyproject.toml` 这一行；自证：裸 `pytest --collect-only -q` 的**文件清单里没有 `tests/integration/`**（36 个文件全列出，见 §B4），`-m integration` 仍收集 16+7+8=31 条；两条门禁命令结果见 §B4（`-m` 由 CLI 覆盖 ini，行为不变） |
| **N6**（授权）凭据缺失造成的假 skip | **FIXED** | `_assembly_settings()` 在 `DSH_IT_MYSQL_PASSWORD` 缺失时注入**占位口令**（不连任何东西）而不是 skip；实测 `Remove-Item Env:DSH_IT_MYSQL_PASSWORD` 后仍是 **7 passed, 0 skipped**（此前会 `1 passed, 3 skipped`） |
| **N7** 无界挂死清单 | **FIXED（必须修的那一处）+ REGISTERED（其余）** | `_RecordingRunner.run_forever` 等 `stop` 有上界 `_STOP_BUDGET_S=2.0`，超界记 `run_forever.stop_missing` 后退出；自证 `test_n7_missing_stop_becomes_a_failure_instead_of_a_hang`（内存变异删掉 `runner_stop.set()`）⇒ 判据**变红**且**在 2s 量级收场**（实测断言 `elapsed < 10s` 通过）。**只登记**：裸 `await runner.execute(...)` 四处、`await 真 run_forever` 处包了 `wait_for` 但形态是 5s TimeoutError——两处按工单"登记即可"处理，写在 `test_main_assembly.py` 的模块 docstring §"所有等待都有界" |

## B2. 我自查发现的**同类漂移**（工单没列，一并修了）

| # | 位置 | 漂移 | 处置 |
|---|---|---|---|
| 1 | `tests/unit/test_task_runner.py` 的 `_MUTANT_MODULE_NAME` | 注释说"见 `_mutant_runner_class`"，而**那个函数不存在**（常量是死代码） | 实现 `_mutant_runner_class`（本轮 F1/F2/F3/F5/M1 的自证都靠它），常量变成活的 |
| 2 | 同文件的 `_LEGACY_RUN_FOREVER_BODY` | 注释说"只在 B2 顺序判据的文档里被引用"，实际**全文件无人引用**（字符串变异的实现早已被删） | 保留（对照价值）但把注释改成"**本常量没有读者**，MUST NOT 当成活判据" |

两条都属 N2 的同一病症（**声称的引用 ≠ 实际的引用**），故按 N2 的口径一起修。

## B3. 关键自证的实测读数（不是转述）

| 自证 | 变异 | 实测读数 |
|---|---|---|
| `test_m1_abandon_guard_discriminates` | `if lease_lost or timed_out:` → `if timed_out:` **且**删 `finally` 的 `_dissolve_task(handler_task)` | 变异体 `paid_calls=1`；`_assert_lease_lost_abandons` 红在 `处理器**跑完了**` |
| `test_f1_f3_guard_discriminates`（2 态） | 内存变异回"`try` 在 `create_task` 之后"的结构 | 两态都红在 `心跳仍在续期`；`all_tasks()` 里确有 `_heartbeat` |
| `test_f2_guard_discriminates` | 同上 | 红在 `心跳仍在续期` |
| `test_f5_bound_guard_discriminates` | `wait_for(shield(task), timeout=...)` → `await shield(task)` | 外层 `wait_for(…, 1.0s)` 抛 `TimeoutError`（= 判据红的形态）；放行处理器后 `execute` 才收场 |
| `test_f7_shutdown_order_guard_discriminates` | `await runner_task` → `await asyncio.sleep(0)` | `_assert_shutdown_order` 红在 `关停顺序不对` |
| `test_n7_missing_stop_becomes_a_failure_instead_of_a_hang` | 删 `runner_stop.set()` | 事件序列含 `run_forever.stop_missing` ⇒ 红；且**有界**收场（不是挂死） |
| `test_death_log_criterion_discriminates` | 合成"只有关停收尾"的记录序列 | 红在 `没有死亡**当场**那条日志`；顺序反了红在 `不早于关停收尾日志`；正序通过 |

> **一处必须说明的发现（M1 的变异需要改两处）**：复核者当初只把
> `if lease_lost or timed_out:` 变成 `if timed_out:` 就能全绿；但在本轮结构修复之后，
> `finally` 里**也无条件**收处理器 task，故**那一个变异不再等于"撤掉取消"**。
> 我的自证因此两处一起改，并在用例 docstring 里写明这一点
> ——**它本身就是 F2 修复有效的证据**：租约丢失路径的取消从"一处条件分支"变成了
> "结构上必然发生"。

## B4. 本批次的验收命令原始输出

```powershell
cd D:\progrom\.worktrees\aicore-architecture\services\aicore
. .\.venv\Scripts\activate.ps1
```

### CMD1（本任务三个单元文件；`--durations=8`）

```
$ python -m pytest -p no:cacheprovider -o addopts="" tests/unit/test_lease.py tests/unit/test_task_runner.py tests/unit/test_cpu_pool.py -q --durations=8
........................................................................ [ 80%]
..................                                                       [100%]
============================= slowest 8 durations =============================
1.02s call     tests/unit/test_task_runner.py::test_f5_bound_guard_discriminates
0.53s call     tests/unit/test_task_runner.py::test_transient_claim_failure_does_not_kill_the_loop
0.43s call     tests/unit/test_task_runner.py::test_dissolve_task_gives_up_after_a_bounded_wait
0.37s call     tests/unit/test_task_runner.py::test_m1_abandon_guard_discriminates
0.33s call     tests/unit/test_task_runner.py::test_lease_loss_cancel_guard_discriminates
0.12s call     tests/unit/test_cpu_pool.py::test_criteria_discriminate_against_a_direct_call
0.10s call     tests/unit/test_cpu_pool.py::test_event_loop_keeps_running_while_cpu_work_is_in_flight
0.10s call     tests/unit/test_task_runner.py::test_runner_never_reads_policy_timeout
90 passed in 5.54s
```

> 67 → **90 passed**（+23）；4.29→5.54s。最慢三条都是**判别力自证**（各自要跑一次变异体），
> 不是白等。

### CMD2 默认段

```
$ python -m pytest -p no:cacheprovider -o addopts="" -m "not integration" -q
1291 passed, 13 skipped, 50 deselected, 1 warning in 54.90s
```

> 1268 → **1291 passed**；deselected 41 → **50**（集成段净增 9 条）。
> 唯一那条 warning 仍是既有的 sqlite3 adapter DeprecationWarning。

### CMD3 集成段（真实 Redis + 真实 MySQL）

```
$ python -m pytest -p no:cacheprovider -o addopts="" -m "integration" -q
50 passed, 1304 deselected in 40.34s
```

> 41 → **50 passed，0 skipped**；集成段耗时 **50.10s → 40.34s**（N1 的 25.18s → 2.06s，
> 其余是新增用例本身的墙钟成本）。跑完核查：`aicore:* = []`、`dbsize = 0`。

### CMD4 ruff（`src tests scripts`）

```
$ ruff check --no-cache src tests scripts
All checks passed!
EXIT=0
```

### CMD5 mypy

```
$ mypy --cache-dir .mypy_cache src
Success: no issues found in 61 source files
```

### CMD6 import-linter

```
$ lint-imports
Contracts: 4 kept, 0 broken.
```

### CMD7 第 3 组验收脚本

```
$ python scripts/group3_acceptance.py
[PASS] 1. DDL 在真实 MySQL 8 执行
[PASS] 2. 三源交叉比对正常态
[PASS] 3. 三源比对三方向阴性
[PASS] 4. 测试内无 sleep
[PASS] 5. 无跨分片 JOIN/聚合/两阶段提交
[PASS] 6. 缺分片键抛错 / 跨分片被拒
[PASS] 7. 只读会话分离 + 池随配置
[PASS] 8. 迁移幂等（基线迁移就位）
[PASS] 9. 一万个 ID 过正则且无重复
[PASS] 10. 提交不带 [AI] 前缀且符合 Conventional Commits
结果：PASS 10 / FAIL 0 / INFO 0
```

> 第 4 项现在报告**显式豁免 21 处**（本文件 12 + `test_cpu_pool.py` 3 +
> `test_lease_redis.py` 2 + 4 处既有 provider 测试）。**本批次净增 0 处豁免**
> （F13 把两处固定轮数改成条件等待，N3 把 5× 余量改成事件，两者都**没有**引入新的 sleep）。

### N5 的机械自证（裸 `pytest` 不再收集集成用例）

```
$ python -m pytest --collect-only -q          # 不带任何 -m
$ python -m pytest --collect-only -q 2>&1 | Select-String "^tests/" | ... | Sort-Object -Unique
tests/api/test_deps.py
tests/api/test_health.py
tests/api/test_ocr_submit.py
tests/api/test_task_poll.py
tests/repository/test_ddl_matches_er.py
tests/repository/test_migration.py
tests/repository/test_repos.py
tests/repository/test_schema.py
tests/repository/test_schema_consistency.py
tests/repository/test_session.py
tests/repository/test_sharding.py
tests/repository/test_task_lease_store.py
tests/structural/test_layering.py
tests/structural/test_pytest_config.py
tests/structural/test_sleep_exemption_counts.py
tests/structural/test_source_guards.py
tests/unit/...（19 个文件）
# ⇒ 清单里**没有** tests/integration/*（N5 之前这里会有 3 个文件）

$ python -m pytest --collect-only -q -m integration
tests/integration/test_lease_redis.py: 16
tests/integration/test_main_assembly.py: 7
tests/integration/test_runner_redis.py: 8
# ⇒ -m integration（CLI）覆盖 ini，集成段照旧可跑
```

> **`-o addopts=""` 的注意点**（如实登记）：本任务的门禁命令用它来**看清汇总行**
> （ini 的 `-q` 被清掉），而它同时也**清掉了 ini 里的 `-m "not integration"`**。
> 故凡是要跑"默认段"的命令，`-m "not integration"` **必须由 CLI 显式给出**（CMD2 就是如此）。
> 这一点已写进 `pyproject.toml` 的注释与 `tests/structural/test_pytest_config.py`。

## B5. **产品行为改动**（单列：理由 + 代价）

### (1) N1：`RedisLockStore` 显式不自动重试

- **改法**：`Redis(..., retry=Retry(NoBackoff(), 0))`（此前用 redis-py 默认的
  `Retry(ExponentialWithJitterBackoff(base=1, cap=10), retries=10)`）。
- **理由**：一次调用内部最多重试 10 次 ⇒ 实测裸 `Redis(port=1).ping()` **26.0s**，
  本任务一条用例独占集成段 **25.18s / 50.10s**。更重要的是**形态**：
  它把 26 秒的长尾藏进一次"看起来很快"的调用里，而 **A2 刚刚消灭掉的就是这个形态**
  （A2 = "一次瞬时错误不该杀死轮询循环"，改法是给 `run_forever` 加**有界退避**）。
  上游两处**都已经**在没有重试的前提下正确工作：`claim_once` 抛错 → ERROR + 有界退避
  （可被 `stop` 打断）；`renew` 抛错 → WARNING + 放弃执行。
- **代价**：Redis 的一次瞬时抖动现在会**立刻**冒到执行器（一条 ERROR/WARNING + 一次有界退避），
  原先可能被客户端内部悄悄重试掉。即"更早、更响、但更快恢复"。
  用例侧新增时延判据 `< 5s` 把这条产品决定钉住（重试一旦回来即红）。
- **找不到反例**：本轮没有发现任何依赖"客户端自动重试"的路径（两次全量门禁都绿）。

### (2) F9：两个实现在**发命令之前**拒绝非法入参

- **改法**：新增 `InvalidLeaseArgumentError(ValueError)`；`_require_lease_ms`（`acquire` /
  `renew` 两侧）与 `_defer_delay_ms`（`defer` 两侧）。
- **理由**：工单 §F9 的实测——真 Redis 会拒绝 `PX <= 0` / 小数毫秒，而替身**照发租约并计数**；
  `int(delay_s*1000) == 0` 时真 Redis 报错而替身真退避；`defer(1.9999)` 两侧口径差 1~2ms。
  生产调用点今天不可达（`Settings.lease_ms ge=1`、退避下界 1.0s），但 `LockStore` 是**交付契约**，
  而"单测绿、生产抛"正是这几轮反复出现的形态。
- **代价**：真实 Redis 上原本由服务端报的错，现在提前在 Python 侧抛出（省一次注定失败的往返）；
  异常类型从 `redis.exceptions.ResponseError` 变成 `InvalidLeaseArgumentError`。
  这是**行为改动**，故在这里单列；今天无生产调用路径受影响。
- **顺带**：`renew` 的 `lease_ms` 也一并校验（工单只列了 `acquire`）——`PEXPIRE key 0` 会**删键**，
  于是"续期"变成"释放"而调用方以为续上了，同一缺陷类，不做就是把修复做一半。

### (3) `_dissolve_task` 的默认值改为**调用时**解析

- **改法**：`timeout_s: float = CANCEL_WAIT_TIMEOUT_S` → `timeout_s: float | None = None` +
  函数体内解析。
- **理由**：`CANCEL_WAIT_TIMEOUT_S` 在 `__all__` 里是**公开常量**，写成默认参数会让"改这个常量"
  成为一个**没有任何效果**的动作（默认参数在定义时求值）——那正是本文件反复在防的"会骗人的接缝"。
- **代价**：多一个 `None` 分支、多一个局部变量。行为在"不传该形参"时**逐字不变**。

## B6. 没做的事 / 已知边界（如实写，不美化）

1. **F8 只登记不修**（工单允许）：关停被**取消**时清理仍会被整体跳过。`main.py` 的
   `except asyncio.CancelledError` 里已写明理由（取消的语义就是"尽快停"，在取消路径上继续
   await 一串清理会把"尽快"变成"不确定"），且**树内无生产者**触发该路径。
   我**没有**给出它的判别力自证——因为按上述判断不该改行为，没有"红"可看。
2. **F11 只登记**：AST 判据的两个弱点（可被仍错的代码满足、对等价正确写法误报）已逐条写进
   四处判据的 docstring，并明确"行为判据为主"。我**没有**把它们改写成行为判据
   ——那需要另写等价的行为用例，超出本批次范围；工单也只要"登记 + 措辞"。
3. **裸 `await runner.execute(...)` 的四处无界等待**：按 N7 的"只登记"处理，
   暴露面低（"永不返回"的处理器今天都带 0.01s/0.3s 超时）。**没有**逐个包 `wait_for`。
4. **`await 真 run_forever` 处包了 `wait_for`**：不挂死，但一次回归会烧 5s 且形态是
   `TimeoutError` 而不是语义化断言。登记在 `test_main_assembly.py` 的模块 docstring 里。
5. **`tests/repository` 单独跑时 `test_session.py` 有一条既有失败**（`caplog` 拿不到
   `EngineFactory` 的装配日志，1 failed / 270 passed）——**与本轮改动无关**：
   (a) 把本轮唯一改到的 `tests/repository/test_task_lease_store.py` 排除掉、甚至用
   `-k "not task_lease_store"` 仍然失败；(b) 用 `文件 + 该用例` 两两组合逐个试，
   定位到污染源是**既有的** `tests/repository/test_migration.py`；
   (c) 全量默认段（CMD2）里它是**通过**的。属别的任务的既有文件，本轮**只登记不碰**。
6. **探针 0 新增**：本批次所有"能判红的证据"都由**已交付的用例**给出（§B3），
   没有任何临时探针文件。`D:\progrom\.dsh-probe\` 目录当前为空（此前 5 个探针已删）。
   `services/aicore/probe-7bz35wir/` 存在但**不是我的**（连列目录都被沙箱拒绝，
   且不在 `git status` 里），故未做任何处置。
7. **`tests/integration/test_main_assembly.py` 不验轮询**（既有边界，未变）：
   `_RecordingRunner` 只等 `stop`。让它真轮询会去扫真库并把别的用例留下的行判成 FAILED。
8. **`_assert_shutdown_order` 用事件序列做代理判据**：`stop.set()` 本身在进程外不可观测，
   故"`run_forever.end` 出现在 `runner.stop` 之前"是它的代理。这一点写在
   `_RecordingRunner` 的 docstring 里（既有写法，未变）。

## B7. 提交计划（**2 个新提交**；不改写 `ab535ae`/`3c9a6c2`/`1fed477`）

| 提交 | 内容 | 主要文件 |
|---|---|---|
| 6 `fix(aicore): 心跳生命周期改为结构上不可泄漏，并让 B1 的判据真能判红` | F1/F2/F3（结构修复 + 4 条用例 + 2 条判别力自证）、M1（判据本体 + 内存变异自证）、F4、F5、F13 的两处条件等待、N2③④、N3（同文件部分）、N4（同文件部分） | `src/aicore/core/task_runner.py`、`tests/unit/test_task_runner.py`、`tests/unit/test_cpu_pool.py` |
| 7 `fix(aicore): 补严装配与死亡的判据，并让锁店替身与真 Redis 同判` | F6、F7、F9、F10、F12、N1、N5、N6、N7、N2①②⑤⑥、新增两条 structural 判据 | `src/aicore/core/lease.py`、`src/aicore/main.py`、`src/aicore/repository/task_lease_store.py`、`tests/integration/*`、`tests/structural/*`、`pyproject.toml` |

**需要拆 hunk 的地方**：`tests/unit/test_task_runner.py` 同时含提交 6（F1–F5/M1/F13）与
提交 7（N2③/N4 的 `poll_interval_s`）的改动 —— 我这边**未做拆分**，`git add -p` 由提交者执行。

**授权说明**：`pyproject.toml` 此前在 `task-4.7-fix-brief.md` §1 的"仍然不可改"清单里，
本轮由追加工单 **N5 明确裁定并授权**只改 `addopts` 一行（其余未动）。

## B8. 第 4 批改动的文件与行数（Python `len(text.splitlines())`，与 §4 同口径）

| 文件 | 行数 | 状态 |
|---|---|---|
| `services/aicore/pyproject.toml` | 128 | 改（**仅 `addopts` 一行** + 注释） |
| `services/aicore/src/aicore/core/lease.py` | 835 | 改（F9 校验面、N1 不重试、§七 边界登记） |
| `services/aicore/src/aicore/core/task_runner.py` | 1351 | 改（F1–F5 结构修复、`_dissolve_task` 默认值、F11 措辞） |
| `services/aicore/src/aicore/main.py` | 274 | 改（F8 已知边界登记） |
| `services/aicore/src/aicore/repository/task_lease_store.py` | 436 | 改（F10 过期说明改正） |
| `services/aicore/tests/integration/test_lease_redis.py` | 459 | 改（N2⑥、F9(c) 三条自证、豁免清单） |
| `services/aicore/tests/integration/test_main_assembly.py` | 669 | 改（F6/F7/F12/N6/N7；**整文件重写**） |
| `services/aicore/tests/integration/test_runner_redis.py` | 588 | 改（F10、N1 时延判据） |
| `services/aicore/tests/repository/test_task_lease_store.py` | 168 | 改（N4② 删恒真判据 + 留痕） |
| `services/aicore/tests/structural/test_pytest_config.py` | 70 | **新建**（N5 的机械判据） |
| `services/aicore/tests/structural/test_sleep_exemption_counts.py` | 120 | **新建**（N2 的机械判据） |
| `services/aicore/tests/unit/test_cpu_pool.py` | 370 | 改（N2⑤、N3 措辞） |
| `services/aicore/tests/unit/test_lease.py` | 511 | 改（F9 替身侧 4 组用例） |
| `services/aicore/tests/unit/test_task_runner.py` | 2905 | 改（F1–F5/M1/F13/N2③④/N4①③/N3、内存变异工具） |

> `services/aicore/tests/unit/test_task_runner.py` 从 1961 → **2905 行**（+944）是本批次最大的一处；
> 增量几乎全是**判别力自证**（内存变异工具 + 5 条自证用例 + 判据本体抽取）。
> 工单要求"每条判据都要能判红"，而本轮的适用面正是"判据是空的"这一类缺陷，
> 故自证部分的体量大于被测代码本身。

---

# 第 5 批（工单 `task-4.7-fix-brief-3.md`）

**基线**：HEAD `a3aa8e0`（未改写任何既有提交；本轮全部落在工作树上）
**纪律自检**：未 `git add` / `git commit`；变异**全部内存**（`_mutant_runner_class` /
`_mutant_main` / 合成 ini 字符串，文件从不被写）；**探针 0 个新文件**
（`D:\progrom\.dsh-probe\` 仍为空目录）；未改 `pyproject.toml` 的其它行。

## C0. 一行结论

**B1（major，本轮新引入的回归）FIXED**：放弃路径的总等待从 `2 × CANCEL_WAIT_TIMEOUT_S`
收到 **1 ×**，实测 **2.031s → 1.034s**（生产常量 1.0s）；判据同时收紧到能判出 2×，
并给出了"串行各等一档 ⇒ 必红"的自证。B2/B3/B4/B5/B6/B8 **全部 FIXED**，B7 **REGISTERED**。
**⚠ 交付时本机 MySQL 服务处于 Stopped**（见 §C5），故 CMD3 与验收脚本第 1 项这次**跑不全**——
与本轮改动无关，但必须如实报出来。

## C1. 逐项状态表

| 项 | 状态 | 证据 |
|---|---|---|
| **B1**（major）放弃路径的等待上界是 docstring 的两倍 | **FIXED** | 修法取 **(a) 整个放弃路径共用一个截止时刻**：进入放弃路径时算一次 `abandon_deadline`，放弃分支与 `finally` 兜底**都传它**；`_dissolve_task` 改成收**绝对 deadline** 并在预算用尽时**直接返回**（不再 cancel、不再记日志）。实测（生产常量 `CANCEL_WAIT_TIMEOUT_S=1.0`、处理器吞掉取消）：**2.031s → 1.034s**；判据 `_assert_abandon_wait_is_bounded` 的阈值从 `3×` 收紧到 **1.5×**（正确 ≈1×，串行 ≈2×，阈值正落在中间）；自证 `test_b1_abandon_budget_guard_discriminates`（内存变异：`finally` 那次丢掉 `deadline=`）⇒ **实测 0.44s vs 生产 0.22s**（同一场景、同一判据助手，**必红**） |
| **B2**（minor）F4 的 `0.0` / `-1.5` 零判别力 | **FIXED** | 判据本体 `_assert_unusable_timeout_was_refused` 增第三条：**逐参数**断言那条分支日志（`非有限值或 <= 0` / `无法解析成数值`）；自证 `test_b2_zero_timeout_guard_discriminates`（校验变异成 `if False:`）⇒ 旧的两条后果判据**照样绿**（`mark_failed=1` + `5002`，因为"采用 0.0"= 立即超时，后果与兜底完全一致）、**新的日志判据红**——正好复现"零判别力"这个诊断。`nan`/`inf` 那半保留（它们本就是真判据） |
| **B3**（minor）子串判据可被坏 ini 满足 | **FIXED** | `shlex.split` 解析后断言 **`-m` 恰好一次、值恰为 `not integration`**；自证 `test_default_deselect_criterion_discriminates` 用三条合成坏配置（`… -m "not integration" -m integration` / `…_typo` / `-m integration`）证明**必红**，并附两种合法写法的阳性对照（分开写与贴着写） |
| **B4**（minor）`-o addopts=""` 的危险没人写明 | **FIXED** | 写在**两处**：`tests/structural/test_pytest_config.py` 的模块 docstring（整节 `⚠ -o addopts="" 会静默解除这条承诺`，含实测 `1304 → 1354`）与 `pyproject.toml` 里 N5 那段注释的末尾 |
| **B5**（minor）`bool` 的理由是假的 | **FIXED** | `_require_lease_ms` 与 `test_lease.py` 里的理由改成实测的那条（`PX True` → **客户端编码期** `DataError: Invalid input of type: 'bool'`），并把守卫的真实理由写成两条：**两侧同判**（同一个异常类型）+ **不依赖三方库的编码时机**。守卫保留 |
| **B6**（minor）一条恒真断言 | **FIXED** | 删掉 `assert not handler.entered or gate is not None`（`gate` 自创建后从未重新赋值 ⇒ 整条恒真），原处留注释说明**为什么不需要**重复断言（覆盖已由 `wait_for(handler.started.wait(), timeout=5)` 承担） |
| **B7**（只登记）新异常不穿出 `run_forever` | **REGISTERED** | 写在下方 §C4 第 3 条 |
| **B8**（minor）两条自证只钉消息、不钉成因 | **FIXED** | ① `test_f7_shutdown_order_guard_discriminates` 增两段**成因**断言（序列非空且首项是 `run_forever.start`；`runner.stop` **先于** `run_forever.end`，缺席时按下标越界算）；② `test_f1_f3_guard_discriminates` 改成**逐参数**声明 `(异常类型, 消息片段)`，`pytest.raises(expected_exc, match=…)` 各钉自己那一档 |

## C2. B1 的修法与取舍（为什么选 (a) 而不是 (b)）

工单给了两条路：(a) 共用一个 deadline；(b) `finally` 只在"尚未放弃过"时才调。**选 (a)**：

| | (a) 共用 deadline（**采用**） | (b) 局部标记"只放弃一次" |
|---|---|---|
| 不变式在哪 | 写在**预算**里：谁调用都受同一个截止时刻约束 | 写在**调用点**：靠"别忘了置标记" |
| 新增调用点 | 传同一个 deadline 即自动纳入预算 | 新调用点若忘了看标记 ⇒ 又变 2× |
| 判据 | `_dissolve_task` 的 `remaining <= 0` 分支**结构上**保证总等待 ≤ 1 档 | 需要额外的"标记传对了没"判据 |

代价：`_dissolve_task` 的形参从 `timeout_s`（相对）变成 `deadline`（**绝对**），
并在预算用尽时**多一个分支**（直接返回）。这个分支本身也写进了 docstring：
**不再 cancel**（对已吞掉取消的 task 是零收益）、**不再记日志**（否则"一次放弃"在日志里像两次）。

**诚实边界（新增到 docstring 里）**：两次 `_dissolve_task` 之间的 `_cancel_heartbeat`
**不在**这个预算内——它等的是心跳自己响应取消的时间（一次 `asyncio.sleep` 或一次 `renew`）；
Redis 被"黑洞"时那一次 `renew` 会把这段拉长。故 MUST NOT 被读成"`execute` 的返回时间一定有硬上界"。

**一处顺手发现的脆弱点（本轮修掉）**：B1 的注释里若**逐字引用**那行 `if` 源码，
基于行文本的变异锚点就会变成两处——`_mutant_runner_class` 的"锚点必须唯一"断言**当场把它拦住了**
（M1 的自证第一次跑就红在这上面）。注释改成不引用源码原文，并在原处写明这条经验。

## C3. 关键自证的实测读数

| 自证 | 变异 | 实测 |
|---|---|---|
| B1 生产态（`CANCEL_WAIT_TIMEOUT_S=1.0`） | — | `elapsed = 1.034s`（复核者修复前实测 **2.031s**） |
| `test_dissolve_task_gives_up_after_a_bounded_wait`（`bound=0.2`） | — | **0.22s** 通过（阈值 0.3s） |
| `test_b1_abandon_budget_guard_discriminates` | `finally` 那次丢掉 `deadline=` | **0.44s**（≈2×）⇒ 同一判据助手**红在"串行等了两档"** |
| `test_b2_zero_timeout_guard_discriminates` | `if not math.isfinite(value) or value <= 0:` → `if False:` | 旧两条后果判据**绿**、日志判据**红**（"零判别力"复现） |
| `test_default_deselect_criterion_discriminates` | 合成三条坏 ini | 三条**全红**；两种合法写法通过 |
| `test_f1_f3_guard_discriminates`（2 态，B8 后） | 修复前结构 | 各钉自己的异常类型与消息（`ValueError`/`payload 拼错了`、`TypeError`/`a coroutine was expected`） |
| `test_f7_shutdown_order_guard_discriminates`（B8 后） | `await runner_task` → `await asyncio.sleep(0)` | 红 + **成因断言**：`runner.stop` 早于 `run_forever.end` |

> **方法论**（复核者纠正控制者，已照办）：自证必须打在**同一场景的接缝**上。
> 本轮两条新自证都只改产品代码在该场景下的一处行为（`deadline` / 那个 `if`），
> 场景（同一个吞掉取消的处理器、同一份 `renew_result=False`、同一个上界）**逐字不变**。

## C4. 没做到的事（如实写）

1. **本机 MySQL 服务在交付时是 `Stopped`**（`Get-Service MySQL` → Stopped，3306 拒绝连接；
   `Start-Service` 需要管理员权限，实测失败）。后果：CMD3 变成 **25 passed / 25 skipped**，
   `group3_acceptance.py` 第 1 项 FAIL（其余 9 项 PASS）。
   **与本轮改动无关**（本轮全部判据都在不依赖 MySQL 的段里；同一天的早些时候 CMD3 是 50 passed / 0 skipped），
   但**必须报出来**：请控制者在 MySQL 起来后重跑这两条。
2. **`_cancel_heartbeat` 的上界不在 B1 的预算内**（见 §C2 的诚实边界），本轮**没有**修。
3. **B7 只登记**：`InvalidLeaseArgumentError` 不会穿出 `run_forever`（真 Redis + `lease_ms=0` 实测：
   永久「领取任务失败（连续第 N 次…）」+ 有界退避），异常类型变更是安全的，
   但**一个永远不会自愈的编程错误被报成 Redis 抖动**——写在工单要求的位置，即此处。
4. **`test_f5_bound_guard_discriminates` 花 1.0s**：它靠"外层 `wait_for` 撞上无上限的等待"来表达红，
   故必须真等一个 5×上界。已登记，未再压。
5. **`_HangForeverHandler` 的收尾改成 `finally` + `release()` + 等 `finished`**（本轮补）：
   第一版把 `release()` 写在断言之后，**断言一失败就会挂死事件循环关停**
   （实测 120s 不返回）——判别力自证里"断言失败"正是预期路径，故这条是必需的，不是洁癖。

## C5. 本批次的验收命令原始输出

### CMD1（单元三件套）

```
$ python -m pytest -p no:cacheprovider -o addopts="" tests/unit/test_lease.py tests/unit/test_task_runner.py tests/unit/test_cpu_pool.py -q --durations=6
........................................................................ [ 78%]
....................                                                     [100%]
============================= slowest 6 durations =============================
1.01s call     tests/unit/test_task_runner.py::test_f5_bound_guard_discriminates
0.53s call     tests/unit/test_task_runner.py::test_transient_claim_failure_does_not_kill_the_loop
0.43s call     tests/unit/test_task_runner.py::test_b1_abandon_budget_guard_discriminates
0.34s call     tests/unit/test_task_runner.py::test_lease_loss_cancel_guard_discriminates
0.34s call     tests/unit/test_task_runner.py::test_m1_abandon_guard_discriminates
0.22s call     tests/unit/test_task_runner.py::test_dissolve_task_gives_up_after_a_bounded_wait
92 passed in 4.67s
```

> 90 → **92 passed**（+2：B1 与 B2 的自证）。**注意生产态那条从 0.43s 降到 0.22s** ——
> 0.43s 就是 B1 的 2×（`0.2 + 0.2`），现在是 1×（`0.2`）。

### CMD2 默认段

```
$ python -m pytest -p no:cacheprovider -o addopts="" -m "not integration" -q
1294 passed, 13 skipped, 50 deselected, 1 warning in 54.27s
```

> 1291 → **1294 passed**（+3：B1/B2 自证 + B3 自证）。

### CMD3 集成段（**本次不完整：MySQL 未运行**）

```
$ python -m pytest -p no:cacheprovider -o addopts="" -m "integration" -q
25 passed, 25 skipped, 1307 deselected in 59.24s
# 25 条 skip 的原因全部是：
#   需要真实 MySQL（aicore_test@127.0.0.1:3306）…OperationalError (2003,
#   "Can't connect to MySQL server on '127.0.0.1' (WinError 10061 …)")
```

> 上一次（第 4 批交付时，MySQL 正常）：`50 passed, 1304 deselected in 40.34s`。
> **本轮改动的判据一条都不在 skip 之列**：Redis 侧的 `test_lease_redis.py`（16 条）、
> `test_main_assembly.py`（7 条）与 `test_runner_redis.py` 中不依赖库的那部分**都跑了并且通过**。

### CMD4 ruff / CMD5 mypy / CMD6 import-linter

```
$ ruff check --no-cache src tests scripts
All checks passed!          EXIT=0

$ mypy --cache-dir .mypy_cache src
Success: no issues found in 61 source files

$ lint-imports
Contracts: 4 kept, 0 broken.
```

### CMD7 第 3 组验收脚本（第 1 项因 MySQL 停下而 FAIL，其余 9 项 PASS）

```
$ python scripts/group3_acceptance.py
[FAIL] 1. DDL 在真实 MySQL 8 执行
[PASS] 2..10
结果：PASS 9 / FAIL 1 / INFO 0
```

> 第 4 项（sleep 判据）仍 PASS，**本批次净增豁免 0 处**。

### Redis 残留

```
aicore:* = []   dbsize = 0
```

## C6. 第 5 批改动的文件与行数

| 文件 | 行数 | 本批内容 |
|---|---|---|
| `services/aicore/pyproject.toml` | 133 | 仅 N5 注释块末尾补 B4 那三行（`addopts` 行本身未变） |
| `services/aicore/src/aicore/core/lease.py` | 848 | B5：`_require_lease_ms` 的 `bool` 理由改成实测 |
| `services/aicore/src/aicore/core/task_runner.py` | 1397 | **B1**：`abandon_deadline` + `_dissolve_task(deadline=)` + 预算用尽分支 + 诚实边界；常量注释补 B1 |
| `services/aicore/tests/integration/test_main_assembly.py` | 691 | B8①：F7 自证补成因断言 |
| `services/aicore/tests/structural/test_pytest_config.py` | 164 | B3：`shlex` 按语义解析 + 自证；B4：`-o addopts=""` 的危险写进 docstring |
| `services/aicore/tests/unit/test_lease.py` | 515 | B5：`bool` 那一档的理由 |
| `services/aicore/tests/unit/test_task_runner.py` | 3191 | B1 判据收紧 + B1 自证；B2 判据本体 + 自证；B6 删恒真断言；B8② 逐参数钉类型；收尾改成 `finally` + 等 `finished` |

**提交（1 个，按工单）**：
`fix(aicore): 放弃路径的等待上界收敛到文档承诺值，并补严三处判据`（B1 + B2/B3/B4/B5/B6/B8；B7 只登记）。
