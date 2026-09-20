# Task 4.7 / 4.8 独立评审报告（第 2 轮，收窄到权威范围）

**评审者**：独立 subagent（与实现者无共享上下文）· **基线**：见 §0 的 SHA256
**控制者裁定**：本轮评审在「修复轮正在改写工作树」的窗口内进行（控制者的调度失误），
故按文件重划取证范围；本节 A1–A9 属于**修复轮不碰或必须先修**的发现，R1–R5 属参考范围。

---

## 0. 取证基线（SHA256 前 16 位 + mtime）

`lease.py`=**0226E3FDF7AEA0D5**(16:22:53)｜`main.py`=**CBD3D586B8217AD5**(16:14:07)｜
`conftest.py`=**0F7592192C09A532**(16:37:38)｜`test_lease.py`=58F3DADE86E689F1｜
`test_lease_redis.py`=25D813D91EDA386E｜参考范围：`task_runner.py`=**CC7395D594F0E37E**(18:34:00)、
`task_lease_store.py`=8E30FA10F155C211(16:25:28)

权威子集实测：`pytest tests/unit/test_lease.py tests/integration/test_lease_redis.py -q`
→ **17 passed in 1.46s**（遵控制者指示未跑全量）。

---

## A1【major】`handler.timeout_s()` 抛异常 → 心跳 task 泄漏 → 租约被**永久续期**，任务再也无法回收

**证据**（探针，`task_runner.py` SHA cc7395d594f0e37e）：

```
execute 抛出 KeyError: 'handler 的 timeout_s 访问了一个不存在的配置项'
execute 返回/抛出时 renew 调用次数 = 0
再等 0.25s 之后 renew 调用次数 = 8（新增 8 次）
仍在运行的后台 task 数 = 1: ['TaskRunner.execute.<locals>._heartbeat']
lease release 调用次数 = 0
判定：心跳**泄漏**（execute 早已返回，它仍在续期 → 租约永不过期，任务再也不会被回收）
```

**根因**：`create_task(_heartbeat())` 已经执行，而 `_declared_timeout_s(handler)`
（内含 `float(declared())`）在 `try/finally` **之外**。处理器作者的一个 bug
（`timeout_s` 抛异常 / 返回 `None`、非数值）就让心跳脱离所有回收路径：
它按 `lease_ms/3` 一直 renew 成功 ⇒ **没有任何实例能再领到这个任务**（`SET NX` 永不成功），
行永远停在 `PROCESSING`。

**附带**：`task_runner.py:437` docstring 逐字写「抛别的异常……终态**不写**
（**留待租约过期后重做**）」——这条路径上租约**永不**过期，docstring 与实际相反；
`_settle` 的日志同样说「租约留待过期回收」，也是错的。

**Confidence：verified**（探针 + 代码位置）。不在控制者已列的 B1/B2/B3/M1–M5 内，故照报。

---

## A2【major】`run_forever` 无异常兜底：一次**瞬时**错误永久杀死执行器；且 `main.py` 关停块被整体跳过

**证据**（探针 B）：

```
run_forever 是否已结束 = True
异常 = RuntimeError: (1146, "Table 'aicore.ai_task_202610' doesn't exist")
死亡后再等 0.2s，list_claimable 调用次数 3 -> 3（未再轮询）
lifespan 关停阶段抛出：RuntimeError: (1146, ...)
关停块里**实际执行到**的清理步骤 = []（应为空 ⇒ 全部被跳过）
```

**真实性佐证**（真 MySQL，探针 p5）：`list_claimable` 对不存在的月表直接抛

```
ProgrammingError: (pymysql.err.ProgrammingError) (1146, "Table 'aicore_test.ai_task_203101' doesn't exist")
```

而 `ensure_month_tables` 在 `src/` 里**没有任何运行期调用者**
（全仓只有 `deploy/sql/migration/env.py`、`scripts/apply_ddl.py` 的 docstring 与测试）
⇒ **每月 1 号（新月表还没由运维/迁移建出来）执行器的第一次轮询就抛 1146，
进程活着但再也不领任务**。

`main.py:155-173` 无 try/except：`await runner_task` 把死亡原因原样抛出
⇒ `runner.stop()`、`locks.close()`、`engine_factory.dispose()`、`flush_logging()` 全部跳过。
`/health` 只回 `{"status":"ok"}`、不查依赖 ⇒ **执行器死了没有任何信号**：
`create_task` 没有 done-callback，异常只有关停时才被 retrieve（进程存续期间一行日志都不会有）。

**内部不一致**：心跳里专门处理了「Redis 抖动」（`except Exception` → 放弃），
但**领取路径**（`claim_once`/`list_claimable`/`acquire`）一处兜底都没有——同一种抖动，两条路径两种命运。

**Confidence：verified**（探针 B + p5 真库 + 逐行读 `main.py`/`health.py`）。
控制者另行复核：`main.py:155-173` 确无 try/except；`/health` 的不查依赖是
`api/health.py:5` 明写的 Task 11.1 范围，故**不构成 T2 缺陷**，但放大了「死了没信号」。

---

## A3【major】内存替身**没有**建模「计数键 PEXPIRE 到期」——离线段永远看不见「计数丢失→无限重试」

**证据**（探针 P2，`lease_ms=100ms`、`attempt_count_ttl_ms=250ms`、每步间隔 0.4s > TTL）：

```
Redis   acquire 序列（每步等 0.4s）: [1, 1, 1]     ← 计数键到期，INCR 从 1 重来（真实 Redis 语义）
InMem   acquire 序列（同一 TTL，注入时钟推进 0.4s/步）: [1, 2, 3]   ← 计数**永不**到期
live_attempt_counter 是否被生产代码调用： 出现次数 = 1     ← 只有它自己的定义
```

**根因**：`InMemoryLockStore._increment_attempts`（`lease.py:436`）直接读
`self._state.attempts.get(...)`，**绕过**了 `InMemoryState.live_attempt_counter`（`lease.py:329`）
——后者是唯一按 `expires_at` 判过期的方法，而它**是死代码**。

**为什么重要**：`DEFAULT_ATTEMPT_COUNT_TTL_MS` 的整段 docstring（`lease.py:99-108`）就在论证
「计数不能在重试途中丢，否则超额判据归零→无限重试」；而**离线段（10 条单测）在这一点上与生产不一致**：
任何依赖计数键到期的实现/回归，单测都会给绿灯，集成段用真 Redis 也盖不住替身这一侧。

**同族分歧**：`RedisLockStore(attempt_count_ttl_ms=0)` 会让 `PEXPIRE key 0` **删键**
（实测 `PEXPIRE 0 -> True | exists after = 0`），每次领取都从 1 重来 ⇒ 判据被静默关掉，
而替身在同参数下仍一直累加。

**Confidence：verified**（探针 + 死代码 grep）。

---

## A4【minor】`defer(delay_s <= 0)` 的文档口径被 Redis 违背；`delay_s=nan` 在替身里是**永久退避**

```
InMemory defer(delay_s=0.0)  -> OK, is_deferred = False
InMemory defer(delay_s=-3.0) -> OK, is_deferred = False
Redis    defer(delay_s=0.0)   -> ResponseError: invalid expire time in 'set' command
Redis    defer(delay_s=-3.0)  -> ResponseError: invalid expire time in 'set' command
Redis    defer(delay_s=0.0004)-> ResponseError: invalid expire time in 'set' command
defer(delay_s=nan) 之后推进 10000s，is_deferred = True | acquire = False   ← 永久退避（内存侧）
acquire(lease_ms=0) -> True | 立刻再 acquire -> True    ← 内存侧返回必然立即过期的 claim
```

三处口径互相打架：`LockStore.defer` docstring（`lease.py:207`「`delay_s <= 0` 按『不等待』处理
（写一个立即到期的键）」）、`RedisLockStore.defer` docstring（`lease.py:586`「钳到 0
（键写入后立即到期，等价于不等待）」）、以及真 Redis 行为（`SET k v PX 0` 是**错误**）。
`_DEFER_LUA` 里也没有下限保护。

**可达性（如实说）**：生产调用点只传 `BACKOFF_BASE_S * 2 ** (attempt-1) >= 1.0`，故今天**不可达**；
但 `defer` 是交付的公开契约。**Confidence：verified**。

---

## A5【minor】`mark_failed` 的 read-then-write 是**丢失更新**（真 MySQL 实测 80 → 10）

```
  [A] 读到 progress = 10
  [B] 已提交 progress = 80
最终行: status=FAILED progress=10
结论: 并发进度被**丢失更新**覆盖（80 -> 10）
```

docstring 声称「`progress` 保持原值」，实际是把**旧快照**写回去。修法需要 `update_status`
能表达「不动这一列」，否则在这个接口下这个竞态**无法消除**——与 `error_code` 缺口同源
（列集合写死在 `status_update_statement`）。

**附带（同类）**：`_current_progress` 的 docstring 说「行的存在性由紧接着那次 UPDATE 的
`rowcount` 决定」，但 `_write_back` 与 `mark_failed` 都把返回值**丢掉**——
`rowcount=0`（行不存在/打错分片）时执行器仍认为写成功并释放租约，
行留在 `PROCESSING` 等下一轮重放（**可能重复调用付费通道**）。

**Confidence：verified**（真库探针）／`rowcount` 那条 **strongly-suggested**（代码直读）。

---

## A6【minor】会话级 socket 守卫**看不见 asyncio 的非环回建连**（Windows/Proactor）

```
event loop policy: _WindowsProactorEventLoopPolicy
[A] 异步非环回建连（ProactorEventLoop 路径）: asyncio.open_connection('192.0.2.1', 9) -> TimeoutError
    违规记录数 = 0
[B] 同步非环回建连（对照组）: socket.connect('192.0.2.1', 9) -> TimeoutError
    违规记录数 = 1
结论： 异步路径**不可见**（守卫存在盲区）
```

守卫只 patch `socket.socket.connect`，而 Proactor 的 `create_connection`/`open_connection`
走 C 层 ConnectEx，**根本不经过**被 patch 的方法。docstring 登记了两条能力边界
（环回放行、C 扩展），**没有登记这一条**，而它比登记的那两条更容易被误信。
**Confidence：verified**。

---

## A7【minor】`task_lease_store.py` 两处把「三源不漂移」的保证挂在一个**不存在**的用例文件上

```
Test-Path tests\repository\test_task_lease_store.py -> False
全仓搜 "test_task_lease_store" 只有 2 处命中：task_lease_store.py:38 与 :126（都是自我引用）
```

原文：「不是第二份状态机……三处一致性由 `tests/repository/test_task_lease_store.py`
**现读** `service/task/state.py` 与 `er.md` §6.1 逐字比对——**不导入**不等于**不校验**」。
即：就地声明状态字面量的**唯一**防线没有实现。**Confidence：verified**。

---

## A8【minor】报告引用了一个**不存在**的用例名；`app.state.task_runner` 零读者零用例

报告 §3.3 提到 `test_no_task_runner_in_test_env`；全仓 grep 该名字 **0 命中**
（只有 `main.py:141` 写 `app.state.task_runner`，**没有任何地方读它**）。
控制者已另立待办：`main.py` 装配用例（集成段，`env="dev"`）覆盖这条装配线。

---

## A9【minor】`RedisLockStore.monotonic_now()`（连同它的 `clock=` 形参）是死接口

全仓 `monotonic_now` 只有 2 处命中——`lease.py:531` 的定义与 `lease.py:502` 的 docstring 提及；
无任何调用者。与控制者 M2（`TaskRunner(clock=)`）同族但是**另一个类**。**Confidence：verified**。

---

## 参考范围（修复轮正在改这些文件 ⇒ 勿与控制者的 B/M 项重复计数）

- **R1【minor】** `test_handler_timeout_goes_through_the_failure_path_with_5002`：唯一断言业务码的一行
  在 `if codes:` 里，而它实际走的路径（attempt=1 → requeue）**不会**产生 `error_code=` 事件
  ⇒ 该断言是**死代码**；一个把超时算成 `4003`（甚至任意码）的实现照样绿。
  docstring 却写「只断言『走了失败分流』会漏掉『超时被当成通道失败 4003』这种实现」——它自己正是那样。
  判别力只在同文件 `..._when_retries_are_exhausted`（`max_retries=0` → `mark_failed`）那条上，缺口窄，minor。
- **R2【minor】** `test_default_executor_still_runs_off_the_event_loop_thread` 声称测 `executor=None`，
  实际传的是 `runner.executor`（自建池）——**`run_cpu_bound(..., executor=None)` 从未被任何用例执行**；
  名字与 `_run_with_none_executor` 与行为不符。同文件 `test_claim_probe_placeholder` 末行恒真断言。
- **R3【minor·B2 的测试侧】** `test_concurrency_limit_blocks_the_second_claim` 只断言 `handler.entered`
  与 `max_in_flight`，**完全没有碰 `locks.acquire_calls`**（工单第 18 条逐字要求断言 `acquire` 调用次数）
  ——这正是"领了再排队"能一路绿灯的原因。
- **R4【minor】** `test_list_claimable_only_scans_the_current_month` 只做否定断言，
  同一调用里没有"本月任务**在**结果里"的阳性对照 ⇒ 恒返回 `[]` 的实现也能过。
- **R5** `task_lease_store.list_claimable` 用 `select(table)` 取全部列（含 `model_meta` JSON 血缘快照），
  每次轮询都拉回来——M1 量级可忽略，登记备查。

---

## 明确查过且 **CLEAN**（覆盖面）

- **Lua 领取原子性**（超出 brief 的 2 连接测试）：5 条独立连接 × 20 次同时 `acquire`
  → **恰好 1 个赢家**、计数键 `b'1'`（证明 INCR 只在 `SET NX` 成功后才跑）、
  `PTTL=4991 ∈ (0,5000]`；释放后再来 20 条并发 → 恰好 1 赢家、`attempt=[2]`、计数键 `b'2'`。
  脚本结构正确、**无 TOCTOU**。
- `renew`/`release` 的 owner 校验走 Lua，脚本内原子；`renew` 只改 TTL 不改值；
  被拒的续期不动 TTL（集成用例正面钉住）。
- **键命名/前缀**：三类键互不相同、同前缀；**不可能跨任务撞键**；
  全仓只有 `aicore:lease:` 与 `aicore:test:` 两个前缀。唯一保留：未做 hash tag，
  Redis Cluster 下 acquire 脚本会 CROSSSLOT——本服务单实例，当前不成立，仅登记。
- `is_deferred` 两侧都**只读**，连调两次一致、不改变可领取性。
- 真 `PX` 语义：TTL 生效、到期可被另一连接回收、`renew` 真延长；
  `release` 计数**不**清零（attempt 递增）。
- **conftest 的 Redis 夹具**：每用例 `aicore:test:<uuid>:` 前缀、只 `SCAN`+`DEL` 自己的前缀、
  **无 FLUSHDB/KEYS**、连不上时带原因的显式 skip；清理写在 `redis_store` 自己的终结器里；
  另行验证「`aclose()` 之后再做 SCAN+DEL 仍可用」「`close()` 幂等」
  「先关 store、夹具再清理」这条真实顺序不会漏键；全部探针跑完 `dbsize=0`、`aicore:* = []`。
- **main.py 启动/关停顺序**：装配点、`env != "test"` 闸门、关停顺序、
  `handlers={}` + `policies=dict(REGISTRY)` 均与 brief §2.7/§2.8 一致；
  `app.state` 除 `task_runner` 外无多余残留。
- `lease.py` 依赖面只有 stdlib + `redis.asyncio` + `aicore.core`；
  `InMemoryState` 的 `>=` 过期判据只有一处、无 `>`/`>=` 混用。
- 权威 10 条单测做了逐条判别力推演（改坏成"不 purge/不查退避/token 不比对/计数清零/续期不延长"
  都会红），**未发现假绿**；它们与集成段的**唯一**盲区就是 A3/A4 两个未建模语义。

## 未能覆盖

- 无法对权威测试文件做完整变异测试（`aicore` 是 editable 安装，复制 `src/` 无法可靠遮蔽真包，
  且评审者不允许改仓库），故假绿结论限于直接可判定的 R1–R4 与实测分歧的 A3/A4。
- 未验 Redis Cluster / `maxmemory` 淘汰计数键 / 主从切换下的 Lua 语义（部署为单实例）。
- 遵控制者指示未跑全量套件；未复核控制者已列的 B1/B2/B3/M1–M5（不重复）。

## 纪律

未改动 worktree 与主仓任何文件；探针只建在 `D:\progrom\.dsh-probe\`（7 个），**已全部删除**。
真 MySQL 只插入并删除了 1 行私有探针数据，未 DROP 任何表。Redis 用了 4 个 `aicore:probe47:*`
系前缀，结束实测 `dbsize=0`、`aicore:* = []`。
