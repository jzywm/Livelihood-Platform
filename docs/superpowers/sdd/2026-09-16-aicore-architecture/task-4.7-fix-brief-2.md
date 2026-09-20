# Task 4.7 修复轮 **第 4 批**工单（独立复核第 1 批结果 → 控制者已复核确认）

**基线**：HEAD `1fed477`（3 个提交已就位、逐提交健康检查全绿）
**来源**：独立复核者（冻结 SHA、只读、内存探针）· **控制者已用自己的探针复核 F1/F2/F3**
**本轮性质**：修复轮。**F1/F2/F3 同一个根因、同一处修复**，F6 是假绿，其余为如实登记项。

---

## 0. 控制者独立复核的原始输出（不是转述复核者）

同一探针（`lease_ms=150` → 心跳间隔 50ms；真 `InMemoryLockStore` 外层计 `renew` 次数）：

```
handler raises ValueError (programming error)   → execute 抛 ValueError
    renew at return 0 / +0.45s later 7 / 租约仍归本实例 = True
handler raises AiCoreError (business failure)   → execute 正常返回
    renew at return 0 / +0.45s later 0          ← 对照：干净
```

隔离复探（每个场景独立拆除并 await 清理）：

```
(a) AiCoreError handler -> execute: returned normally          ← 控制者首版探针里的
                                                                  "CancelledError" 是它自己的
                                                                  跨场景残留，不是产品缺陷
(b) external cancel -> raised CancelledError; renew 3 -> 10 (+7); live heartbeat tasks=1
(c) sync handle     -> execute: TypeError: a coroutine was expected, got None;
                       renew 0 -> 7 (+7); live heartbeat tasks=1
```

**读法**：(a) 证明业务失败路径干净；(b)(c) 证明**外部取消**与**处理器形态错误**两条路径
都会留下一个**仍在续期的孤儿心跳**。

---

## 1. 一个根因，三条入口（**F1 = blocker**；F2 / F3 = major）

> **严重度更正（复核者主动补跑端到端后下调，控制者采纳）**：F2 原报 blocker，
> 补跑后证明**有一条不泄漏的形态**：直接取消 `run_forever`（未 set stop）时，
> 取消落在**轮询等待**上、不会传播到 `_execute_with_permit`，在飞任务照常收尾、写终态、
> 释放租约（实测另一实例 `acquire` 得到 `attempt=2`、活动 task 为空）⇒ **该路径干净**。
> 真正泄漏的是"取消落在 **`execute` 自己**身上"（典型：关停 drain 阶段被取消），
> **树内无生产者** ⇒ 记为 **major**。
> **F1 不受影响，仍是 blocker**：它**不需要任何取消/关停**——处理器（把活干起来之后）
> 抛一个普通异常就会永久泄漏心跳。
> **但三者的修复是同一处结构性改动**，故不因严重度不同而分两轮做。

**根因**：`execute` 里 `heartbeat = asyncio.create_task(_heartbeat())` 之后、
`try/finally`（内含 `await self._cancel_heartbeat(heartbeat)`）**之前**，还有若干可抛/可退出的语句。
只要从那里冒出 `execute`，`finally` 就不执行 ⇒ 心跳**脱离所有回收路径** ⇒ 它按
`lease_ms/3` 一直续期成功 ⇒ **`SET NX` 永不成功、没有实例能再领到这个任务**，
行永远停在 `PROCESSING`。

三条入口：
- **F1**：处理器抛**非 `AiCoreError`**（`ValueError` 这类编程错误）——`handler_task.result()` 的上抛
  只被 `AiCoreError`/`CancelledError` 兜住，于是异常在进入 `try` 之前冒出。
  这条路径正是 `TaskHandler.handle` 的 docstring **逐字承诺**的形态
  （"抛别的异常……终态不写（**留待租约过期后由别的实例重做**）"）——**承诺不成立**。
- **F2**（major）：**取消落在 `execute` 自己身上**时（`await asyncio.wait(...)` 在 `try` 之外
  收到取消），`CancelledError` **传播是对的**（没有退化成 lease_lost、没有吞掉），
  但 `_dissolve_task(handler_task)` 与 `_cancel_heartbeat(heartbeat)` 都不执行 ⇒
  心跳泄漏 + 处理器被**孤儿化**（仍在 sleep，之后照常打付费调用）。
  可达形态是"**关停被中止**"（先 `stop.set()` 让 `run_forever` 进 `_drain_inflight` 等这个任务，
  再取消 `run_forever`——此时 `gather` 会取消子任务），树内无生产者。
- **F3**：`handle` 不是 async（同步 `def`）或没有该属性 ⇒ `create_task(handler.handle(...))`
  这一行**同步执行**处理器代码/抛 `AttributeError`，同样落在 `finally` 之外。

**必须的结构要求（本轮的核心，MUST 逐字落实）**：
`create_task(_heartbeat())` 与 `try` 之间 **MUST NOT 有任何可抛语句**——
即 `try` 必须**紧接** `create_task`，处理器 task 的创建、`asyncio.wait`、
`result()` 取值、失败分流、终态写回**全部**在 `try` 之内；
`finally` 里既取消心跳、**也取消仍在运行的处理器 task**。
**这条是"结构上成立"而不是"每条路径各打一个补丁"**：`handle` 的 docstring 已经写了
"起了心跳就必须收掉它成为**结构上成立**的事"——现在不成立，请让它成立。

**判别力自证（MUST，且 MUST NOT 用"改 src + finally 还原"）**：
用一个 `_PreFixExecute`（把解析/创建挪回 `try` 之外的同形副本）或内存变异的执行体，
证明上述用例**会红**；三条入口（F1 非 AiCoreError、F2 外部取消、F3 同步 `handle`）
**各要一条用例**，且每条都要断言：① `execute` 的出口行为（上抛/传播）。
② 返回后再等 ≥3 个心跳间隔，`renew` 次数**不再增长**。
③ `asyncio.all_tasks()` 里**没有** `_heartbeat`。
④ 另一个实例能 `acquire` 到该任务（**这条是最贴近后果的判据**）。

---

## 2. 阻塞项：F6 —— "死亡有日志"的断言是空的（假绿）

**复核者的证据**：删掉 `main.py` 的 `add_done_callback(_log_runner_death)` 后，
`test_main_assembly.py` 仍 **4 passed**。因为断言是
`"异常退出" in caplog.text or "不会再领取任何任务" in caplog.text`，
而**关停期**那条日志（`main.py:199`「任务执行器在关停前已**异常退出**：继续执行关停清理」）
也含同一子串 ⇒ 断言被它满足。

**后果**：`3c9a6c2` 的**一半理由**（"死亡**当场**记 ERROR，否则进程存续期间一行日志都没有"）
**没有任何守备**——把 done-callback 删掉可以全绿通过。

**必须**：断言**只可能由死亡当场那条日志满足**，且**判别力可证**。要求：
1. 断言死亡当场消息的**独有**子串（`main.py:53` 的「进程仍然存活」那一段），
   **MUST NOT** 用与关停期日志共有的子串（"异常退出"）；
2. 同时在 `caplog.records` 上断言**顺序**：死亡当场那条**早于**关停收尾那条；
3. **判别力自证**（内存里做，不落盘）：把"只含关停期日志"的记录序列喂给同一个断言助手，
   断言助手**必须判红**；`ADDRESSED-BY-REFACTOR` 不算，要能看到红。

---

## 3. 主要项

- **F4**：`timeout_s()` 返回 `nan`/`inf` 时任务级超时被**静默关掉**（`float(declared())` 放行），
  恰好得到 `FALLBACK_HANDLER_TIMEOUT_S` 的论证逐字否决的"挂死处理器永久占满并发额度"。
  **必须**：非有限值（nan/inf）与 `<= 0` 一律**不采用**，改走 `FALLBACK_HANDLER_TIMEOUT_S` + ERROR 日志
  （与"缺 `timeout_s` / 非可调用 / 非数值"同一条处置），并加用例（`nan`/`inf`/`0`/负数）。
- **F5**：`_dissolve_task` 在 `cancel()` 之后**无上限地 await**。不合作的处理器
  （吞掉取消、或延迟响应）会把"主动放弃"变成"等它做完"，且**放弃之后仍发生付费调用**
  （复核者实测：租约 0.033s 就丢失，`execute` 到 **1.561s** 才返回，付费调用 **1** 次）。
  **必须**：取消后的等待**有界**；超界时记 ERROR 并**不再等**（MUST NOT 无限等）；
  docstring 的诚实边界**补上这一条**（现只列了"已交给线程的工作/已发出的同步调用收不回"，
  漏了"处理器吞掉取消或延迟响应"）——**MUST NOT** 让读者以为 `execute` 的返回时间只由 `timeout_s` 决定。
- **F7**：`await runner_task` 这个 **join 本身没有行为判据**——把 `await runner_task` 换成
  `await asyncio.sleep(0)` 后 `4 passed`（连跑 5 次），因为 `stop.set()` 已唤醒 `run_forever`，
  父协程一次让出就够它先记下 `run_forever.end`。
  **必须**：让"**等执行器真的退出**"这件事可判定——`run_forever.end` 之前要有**需要多次让出**
  才能完成的动作（例如记录版 `run_forever` 在 `stop` 置位后再 `await` 一个由测试显式放行的
  门闩），并给出**判别力自证**：把 `await runner_task` 换成 `await asyncio.sleep(0)`（内存变异），
  顺序判据**必须变红**。
- **F9**：内存替身比真 Redis **宽松 4 处**（真 Redis 实测）：
  `acquire(lease_ms=0/-5)` → Redis `invalid expire time`，替身照发租约并计数；
  `acquire(lease_ms=1000.5)` → Redis `value is not an integer`，替身照发；
  `defer(delay_s=0.0001/0.0005/0.0009)`（`int(delay_s*1000)==0`）→ Redis 报错，替身真退避；
  `defer(delay_s=1.9999)` → Redis PTTL 1998ms vs 替身 1999.9ms（截断口径）。
  **可达性如实**：`Settings.lease_ms ge=1`、执行器退避 ≥1.0s ⇒ 今天都不可达。
  **必须**：(a) 让替身**拒绝**真 Redis 会拒绝的输入（`lease_ms <= 0`、非整数 `lease_ms`、
  `int(delay_s*1000) == 0`）——**两侧行为一致，而不是"契约上写着 Redis 会报错但替身照做"**；
  (b) 过期边界（真 Redis `now > when` vs 替身 `now >= expires_at`，实测最多 1ms 差）
  **择一写进 docstring 并登记为已接受差异**；(c) 把跨实现一致性用例从"只覆盖计数 TTL"
  扩到**上述输入拒绝面**（同一组输入喂两侧，断言同判）。生产调用点不可达**不构成不修的理由**：
  `LockStore` 是交付契约，而"单测绿、生产抛"正是这几轮反复出现的形态。

---

## 4. 次要项（都小，但都要求修或如实登记）

- **F10**：`src/aicore/repository/task_lease_store.py:79-97` 仍写着「★ 已知缺口：`mark_failed`
  的 `error_code` **没有落库**（如实登记，MUST 先读）」「收下但落不了库」「FAILED 行的该列此刻
  会是 NULL」——**这些说明已经过期且是假的**（同文件 `:43-49` 与合作码 `:315` 早已闭合）；
  `tests/integration/test_runner_redis.py:315-317` 的函数 docstring 同样还写着
  「⚠ error_code 此刻不会落库……故断言该列为 None」，而同函数 `:349` 断言的正是真实码值。
  **B3.6 只做了一半**，请补齐（**这是"文档说没做、代码做了"的镜像，同一类毛病**）。
- **F12**：装配用例的卫生问题，逐条处理：
  (a) **`flush_logging()` 不可观测**（删掉/提前都 4 passed）——至少登记，能断言则断言；
  (b) **对调 `RunnerConfig(lease_ms=…, max_retries=…)` 的取值仍 4 passed**——
      `TaskRunner.config` 是公开只读属性，**应当**断言装配进去的值来自 `Settings`（这正是 §2.7 的判据）；
  (c) `SqlTaskLeaseStore` 的注入**无判据**——加一条（哪怕是 `isinstance` + 它拿的是同一个 `engine_factory`）；
  (d) 该文件**不需要 MySQL/Redis**（死端口下仍 4 passed），却被标 `integration`
      且**默认段会被真收集执行**（`pyproject.toml` 只有 `addopts="-q"`、无 `-m "not integration"`、
      无 collection hook）——与你文件 docstring 的说法不符。**裁定**：既然它不连外部依赖，
      **就不要靠"默认段不跑集成"来保它**；要么在 `pyproject.toml` 的 `addopts` 里补
      `-m "not integration"`（**改 pyproject 需先问我**），要么把该文件的 marker 去掉/改标
      （**同样先问我**）。**本轮只做一件事：把事实写清楚并登记**，不要擅自改 `pyproject.toml`。
  (e) 抹掉 `DSH_IT_MYSQL_PASSWORD` → `1 passed, 3 skipped`：**该凭据与用例实际需要无关**，
      属**假 skip**（凭据缺失时它仍然会跑）。请改成**与真实需求对齐**的 skip 条件。
  (f) 删掉 `runner_stop.set()` 用例**挂死**（>8 分钟无输出）而非变红——**MUST** 给该
      用例加**有界 deadline**（超时即以断言失败收场）。"挂死"在 CI 上比"变红"贵得多。
- **F13**：`ai-allow-sleep` 从 10 涨到 22。复核者逐条判定**绝大多数是真实节奏**（心跳必须真等、
  真 PX、CPU 时长），唯一可疑形态是**固定让步轮数**（`for _ in range(50)` / `range(5)`）——
  同文件自己记过"实测固定 50 轮偶发不够"。**要求**：凡"让步轮数"**是判据本身**的地方，
  改成**条件等待 + 有界 deadline**（轮询到条件成立或超时），并在报告里列出改了几处。
  实测连跑 12 次稳定，故按 minor 处理。
- **F8**（关停块在"执行器被**取消**"时被整体跳过）：树内无生产者 ⇒ **只登记**。
  若你判断能安全修（例如 `except asyncio.CancelledError` 里也记一条并继续清理、最后再抛），
  请连判别力自证一起给；否则在 docstring 里写明这是**已知边界**。
- **F11**（AST 结构判据可被仍然错的代码满足，且对等价正确写法误报）：**只登记**，
  并确保**行为判据为主、AST 判据为辅**的措辞在文件里写清楚。

---

## 5. 纪律

- 报告写入 `.superpowers/sdd/2026-09-16-aicore-architecture/task-4.7-fix-report.md`（追加第 4 批一节）；
- **MUST NOT** `git add` / `git commit`（控制者来提交）；
- **MUST NOT** 用「改 src + finally 还原」做变异测试（变异一律在内存里；F6 的判别力自证
  用"合成记录序列喂同一个断言助手"的形态）；
- 探针**上限 2 个**、只放仓库外的 `D:\progrom\.dsh-probe\`、用完即删；
- **MUST NOT** 改 `pyproject.toml` / `.importlinter` / `services/aicore/tests/` 下**未被本工单点名**的既有文件；
- 每条都要在报告里给**逐项状态表**：`FIXED` / `REGISTERED` / `STILL-PRESENT` + 证据；
  **做不出能判红的自证就停下写明是哪一条**（这一轮我已经替你把 F1/F2/F3 的原始输出拿到了，照着重建即可）。

## 6. 交付后的提交形态

本轮改动落在**新提交**上（不要改写已有 3 个提交）。建议：
- 一个 `fix(aicore): 心跳生命周期改为结构上不可泄漏（含外部取消与非 AiCoreError 出口）`（F1/F2/F3 + 用例）；
- 一个 `fix(aicore): 补严装配与死亡的判据，并让锁店替身与真 Redis 同判`（F4/F5/F6/F7/F9/F10/F12/F13）。

我会对每个提交再跑一次全量门禁 + 逐提交健康检查。
