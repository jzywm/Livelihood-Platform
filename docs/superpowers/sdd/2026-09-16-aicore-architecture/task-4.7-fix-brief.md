# Task 4.7 + 4.8 修复轮工单（控制者独立复核后下发）

**Worktree**：`D:\progrom\.worktrees\aicore-architecture`；服务根 `services/aicore/`
**上一轮**：`task-4.7-brief.md`（实现）+ `task-4.7-report.md`（自报）
**本轮性质**：**修复轮**。控制者已独立复现全部门禁并逐条取证，下面是**证据 → 必须的行为 → 验收形态**。

---

## 0. 控制者已独立复现的事实（无需你重跑，但你的修复不得让它们变红）

| 门禁 | 控制者实测原始输出 |
|---|---|
| CMD2 默认段 | `1240 passed, 13 skipped, 33 deselected, 1 warning in 55.48s` |
| CMD3 集成段 | `33 passed, 1253 deselected in 45.81s`；跑完 Redis `dbsize=0`、`aicore:*` 残留 `[]` |
| CMD4 ruff | `All checks passed!` |
| CMD5 mypy | `Success: no issues found in 61 source files` |
| CMD6 lint-imports | `Contracts: 4 kept, 0 broken.`（契约 4 KEPT，方案 1 落地正确） |
| 验收脚本 | `PASS 10 / FAIL 0`，豁免清单 10 处（4 既有 + 6 新增）与你的报告一致 |

**控制者确认你对的地方**（不要回退这些）：
- `limit = concurrency_limit` 让「第一个抢不到就试下一个」真的可达 —— 我的探针 A：`list_claimable(limit=1)` 只回 `['task-a']`，而 `claim_once()` 正确返回 `task-b`。
- `requeue → defer → release` 顺序与效果 —— 我的探针 C 事件序列 `store.begin_attempt → store.requeue → locks.defer → locks.release`，`is_deferred=True`、`leases now held=0`、别的实例在退避窗口内领不到、1.5s 后 `attempt=2`。
- 三个自报缺陷（信号量持有范围、`limit=1`、释放租约）都是真缺陷、修得也对。
- 契约 4 的处理方式（core 就地 Protocol + 组合根注入 `dict(REGISTRY)`）经我复核成立。

---

## 1. 阻塞项（必须修，且必须有判别力自证）

### B1【设计违反】租约丢失后**没有放弃执行**，处理器继续跑到结束并完成外部副作用

**要求原文**（`openspec/changes/implement-aicore-service/design.md:208`）：
> 租约到期未被续期即可被其他实例回收……**续期失败必须主动放弃任务而非继续执行**，避免出现
> 「两个实例同时处理同一任务」的重复外部调用（会产生真实费用与重复标记）。

**你自己的文档也这么写**（`core/task_runner.py:542` 的 `execute` docstring「置 `lease_lost`、**取消处理**、不写任何终态」；心跳日志「**主动放弃执行**，不写终态」）。

**控制者实测（探针，`lease_ms=100` → 心跳间隔 0.0333s，`renew` 首次即返回 `False`，处理器耗 1.0s 并计一次"付费调用"）**：

```
HEARTBEAT_DIVISOR = 3 -> heartbeat every 0.0333s
execute() returned after 1.032s
renew_calls         = 1
handler ran to end  = True
paid api calls made = 1
store_calls         = ['begin_attempt']
TRACE               = ['handler_start', 'handler_end']
[stderr] 任务 task_x 的租约已不再归本实例所有（续期被拒）：主动放弃执行，不写终态，由租约过期后回收（design.md:208）
```

**读法**：0.033s 就判定租约丢失并打了"主动放弃执行"的日志，但 `execute` 到 **1.032s** 才返回、
处理器**跑完了**、**付费调用发生了 1 次**。抑制住的只有终态写回（这是对的），
**执行本身没有被放弃** —— 正是 `design.md:208` 要避免的「重复外部调用」。

**必须的行为**：租约丢失时**中止处理器的执行**（取消它），`execute` 随即收尾返回，
不写任何终态（这条你已经做对）。`asyncio.CancelledError` 那个分支
（`task_runner.py:625-634`：`if not heartbeat.done(): raise`）就是为此准备的接收端，
**目前没有任何东西去触发它** —— 请把取消接上，让那条分支成为**主路径**而不是死代码。

**诚实性要求（重要，别再犯 D3 那种"文档说做了、代码没做"）**：
- 处理器若已经把工作交给了**线程**（`run_cpu_bound`），协程取消**收不回**那个线程。
  这一点 MUST 写进 docstring，**MUST NOT** 写成"已回滚外部副作用"。能承诺的只有：
  「不再等待它、不再写终态、不再叠加后续工作」。
- 日志文案要与实际行为一致（现在这条日志在说谎）。

**验收形态**：一条用例，处理器**本来要跑很久**（或等到被取消），租约丢失后断言：
① `execute` 在远小于处理器时长内返回；② 处理器**没有跑完**（用一个只有跑完才会置位的旗标）；
③ 外部副作用计数为 **0**；④ 三类终态写回零调用。
**判别力自证**：这条用例**必须在当前实现下变红**（当前实现会让 ②③④ 里 ②③ 失败）。
自证方式与 4.7 既有做法一致（内存里变异、不落盘）。

### B2【工单明确要求未实现】领取**没有**受信号量约束（领了再排队）

**要求原文**（`task-4.7-brief.md:309-310`，§2.5 硬约束 7）：
> `run_forever` 用 `asyncio.Semaphore(config.concurrency_limit)` 封顶；**信号量满时 MUST NOT 领取新任务**
> （先拿信号量再领取，而不是领了再排队）

**要求原文**（同文件第 442 行，验收第 18 条）：
> **背压**：`concurrency_limit=1` 时，第二个任务在第一个跑完前**不被领取**

**控制者实测（探针 B：`concurrency_limit=1`、8 个候选、处理器每次睡 0.20s、
用符合 `TaskStore` Protocol 的替身；"在租"由真 `InMemoryLockStore` 记账）**：

```
handlers entered      : ['task-0', 'task-1', 'task-2', 'task-3']
max_in_flight (exec)  : 1  (limit=1)
max leases held at once: 2  (limit=1)
leases still held     : 0
VERDICT: CLAIM-THEN-QUEUE: 2 leases held while only 1 may execute
```

**读法**：执行确实被封在 1（你修的信号量持有范围是对的），但**租约被领了 2 个**——
第二个任务在第一个跑完前**已经被领取**，与验收第 18 条**直接冲突**。
`run_forever` 是「先领取、再把协程挂到信号量上排队」，也就是工单明令禁止的**领了再排队**。

**为什么这是真问题而不是洁癖**：被领取但还在排队的任务**持有租约、却没有心跳**
（心跳在 `execute` 里才起，而 `execute` 要等许可）。等待超过 `lease_ms` 时租约静默过期
→ 别的实例回收 → **同一个任务被两个实例执行**，正是 B1 同一条设计禁令要防的重复付费调用。

**必须的行为**：**先拿许可再领取**；领不到任务就把许可立刻还回去。同时
**`stop` 必须仍能及时打断**（验收第 19 条不得回退）：等在许可上时不能对 `stop` 无响应。

**注意一个会掩盖缺陷的现有事实**（你要在报告里说明你的新契约如何不依赖它）：
`SqlTaskLeaseStore.list_claimable` 的谓词是 `WHERE status = 'PROCESSING'`，而
`begin_attempt` **不改 status**（仍是 `PROCESSING`）——所以**正在跑的行仍然出现在扫描窗口里**。
在 `limit = concurrency_limit` 且窗口恰好被"自己在跑的行"占满时，`acquire` 会被自己挡住，
于是表面上看不出领了再排队。**这个掩盖是偶然的、且依赖窗口大小**：
一旦窗口里出现一个更早的、租约已过期的行（崩溃回收路径）而本实例许可已满，
就会真的领了再排队。**执行器的背压契约 MUST 自洽，MUST NOT 依赖存储层谓词的副作用。**

**验收形态**：一条断言「**同时持有的租约数 ≤ concurrency_limit**」的用例
（控制者探针 B 的形态：候选窗口里必须有一个**不同于正在跑的**可领取任务，
否则用例没有判别力）。**判别力自证**：把许可判定挪回领取之后（内存变异），该用例必须变红。

### B3【我的工单第二条自相矛盾 —— 授权你改既有文件，按下面最小范围】

你 §5.2 的判断**完全正确**，我复核确认三条约束同时成立：
- `task-4.7-brief.md:17-18`「MUST NOT 改：……`repository/**` 的**既有文件**……」；
- 同文件第 518 行「发现控制者给的接口有硬伤 → 停下并写明，MUST NOT 自行改契约或既有文件」；
- `repository/task_repo.py:118-146` 的 `update_status` 列集合只有 `status`/`progress`/`finished_at`，
  且 `tests/repository/test_repos.py:733 test_status_update_statement_only_sets_three_columns` 逐列钉住。

**这是我的工单缺陷**（与 §5.1 同类），**不是你的偏离**；你停下来报告是对的。
`design.md:210` 明写「外部通道失败（`4003`）与依赖超时（`5002`）**分别计数**」，
而 4.11 要靠 `ai_task.error_code` 做这件事 ⇒ 这一列**必须落库**。

**本轮授权范围（仅此，超出即越权）**：
1. `repository/task_repo.py::status_update_statement` 增加 `error_code: str | None = None` 形参；
   **仅当非 `None` 时**把该列放进 `.values(...)`（保持既有调用方的 SQL 不变）。
2. `repository/task_repo.py::TaskRepo.update_status` 增加同名形参并透传。
3. `tests/repository/test_repos.py::test_status_update_statement_only_sets_three_columns`
   **MUST NOT 删除或削弱**：保留"不传 `error_code` 时**恰好**三列"的断言，
   **另加**一条"传了 `error_code` 时恰好四列且该值正确"的断言。
4. `repository/task_lease_store.py::mark_failed` 把 `error_code` 真正写下去，
   并**删掉**那条 WARNING（缺口已闭合）。
5. 集成用例里那条"正面记录该列为 `NULL`"的断言改为断言**真实码值**。
6. `repository/task_lease_store.py` 与报告里所有「`error_code` 落不了库」的说明同步更新。

**仍然不可改**：`provider/**`、`core/config.py`、`core/errors.py`、`core/envelope.py`、
`api/**`、`service/**`、`pyproject.toml`、`.importlinter`、以及 `tests/` 下**除第 3 条指名的那一条用例之外**的既有文件。

---

## 2. 主要项（必须修，判据清楚）

### M1【假绿】`test_renew_failure_abandons_without_any_terminal_write` 没有判别力，且是 CMD1 的主要耗时

**实测**：该用例两个参数各耗时 **5.01s**（`--durations`），CMD1 全部 11.75s 里 **10.02s** 是它。
`FakeHandler(hang=True)` 是"挂到被 `wait_for` 取消"，而 `timeout_s` 默认 **5.0**
—— 也就是说**用例是靠 5 秒超时结束的**，不是靠租约丢失（租约在 10ms 就丢了）。
租约丢失那一刻对处理器**什么都没做**；把它改成"真的取消"，断言**照样全绿**。

**必须**：让它对 B1 的修复**有判别力**（B1 的验收形态可以就是它，也可以另立一条），
并让它的耗时回到**毫秒级**（修好 B1 后自然如此）。**判别力自证**：当前实现下必须红。

### M2【死接口】`TaskRunner(clock=...)` 完全没用上

**实测**：`self._clock` 只在 `task_runner.py:456` 被赋值，全文件**再无任何读取**。
`claim_once` 的 `now=self.now()` 取的是**墙钟**（`datetime.now(UTC)`），心跳等待用的是
**真 `asyncio.sleep`**。于是这个形参是一个**会骗人的接缝**：注入了假时钟的调用方以为控制了时间，
实际什么都没控制。

**裁定：删掉这个形参**（连带 `clock` 的 import 若不再需要），并在 `__init__` docstring 里写明
**为什么这里的时间不可注入**：写库的时间戳必须与人读的时间对齐（只能墙钟）、
心跳等待必须是真的（否则续期节奏会被测试改写）。
**这是我工单的缺陷**（`task-4.7-brief.md:269` 列了这个形参、第 314 行还要求"可注入"），
**不是你的偏离**；也**不要**改成"用 `self._clock.sleep()` 驱动心跳"——那会让注入的
假时钟（其 `sleep` 无让出点）把心跳变成忙循环。同步删掉测试侧的 `clock=` 实参。

### M3【误导性命名 + 永不失败的断言】`test_claim_probe_placeholder`

`tests/unit/test_cpu_pool.py:331`：名字里的 `claim_probe`/`placeholder` 是一次性探针的残留命名，
会让复核者误以为它是残留物；末尾 `assert TaskClaim and InMemoryLockStore` **永远为真**
（只是为了压住未使用导入）。请改名成描述其真实判据的名字，并去掉那条永不失败的断言
（改用 `__all__` 或删掉无用导入）。

### M4【报告失准】行数表与用例计数全表对不上

**实测（控制者逐个文件数）**：

| 文件 | 报告 | 实测 |
|---|---|---|
| `core/lease.py` | 394 | **608** |
| `core/task_runner.py` | 604 | **972** |
| `repository/task_lease_store.py` | 255 | **394** |
| `tests/unit/test_lease.py` | 165 | **258** |
| `tests/unit/test_task_runner.py` | 826 | **1134** |
| `tests/unit/test_cpu_pool.py` | 245 | **352** |
| `tests/integration/test_lease_redis.py` | 165 | **251** |
| `tests/integration/test_runner_redis.py` | 305 | **437** |
| `tests/unit/test_lease.py` 用例数 | 11（§1 与 §9 两处） | **10** |
| 单元新增合计 | 49 | **48**（CMD1 的 `48 passed` 自证） |

比值逐文件不同（1.37~1.61），**不是任何统一口径**（总行/非空/非注释/非文档字符串我都算过），
最可能是**实现中途取数后未刷新**。报告里的数字是复核者的判据来源，**必须与交付物一致**。
请全部重算并改正；并在报告里写明"数字取自交付后重算"。

### M5【docstring 承诺了不存在的断言】验收第 18 条用例

`test_concurrency_limit_blocks_the_second_claim` 的 docstring 写「断言 `acquire` 的调用序列里
**只有** `task-a`」，但**用例体里没有任何对 `locks.acquire_calls` 的断言**
（`_FixedClaimLockStore` 记了 `acquire_calls`，从头到尾没被读）。它现在只断言
`handler.entered` 与 `max_in_flight`。
**并且它的绿色来自 `limit=concurrency_limit=1`**：候选窗口被切成 1 个元素，
而那个元素恰好是正在跑的 `task-a`（`FakeStore.list_claimable` 只排除写过终态/重排队的任务），
所以 `acquire` 永远拿不到 `task-b`——**不是因为信号量，是因为窗口**。

**必须**：把 docstring 说的那条断言真的写上，并让用例能对 B2 的修复有判别力
（窗口里必须出现一个**不同于正在跑的**可领取任务）。

---

## 3. 只登记、本轮不修（写进报告 §6，不要动代码）

- `SqlTaskLeaseStore.list_claimable` 会把**正在跑的行**一并扫出来（`begin_attempt` 不改 `status`），
  于是 `limit=concurrency_limit` 的窗口会被"自己领不到的行"占掉。多实例下表现为
  「窗口全被别人持有的行占满 → 本实例空转」。属**吞吐**问题（M1 任务量 <1 QPS），
  归 4.9–4.11 或压测任务（13.4）评估，本轮只登记。
- `list_claimable(limit=concurrency_limit)` 的多扫行开销仍无量测（你 §6.4 已登记，保留）。
- `mark_failed` 终止分支不释放租约（你 §4.3 的理由成立，保留）。

---

## 4. 纪律（与上一轮相同，逐条仍然有效）

- **MUST NOT** `pip install`；**MUST NOT** 用「改 src + finally 还原」做变异测试（变异一律在内存里做）；
- 临时探针**上限 2 个**，且**MUST 放在仓库外的** `D:\progrom\.dsh-probe\`（那个目录不属于任何 git 仓库），
  用完即删；**MUST NOT** 在 `tests/` 或 `src/` 下留任何 `_probe*`/`_dsh*` 文件；
- 真等待的 `sleep` 一律带同行 `# ai-allow-sleep: <理由>`，并在报告里列清单；
- 发现本工单又自相矛盾 → **停下并在报告里写明**，MUST NOT 自行扩大范围；
- 报告写入 `.superpowers/sdd/2026-09-16-aicore-architecture/task-4.7-fix-report.md`。

---

## 5. 交付形态：**两个提交**，各自独立健康

请**分两个提交**（都要跑完整门禁；每个提交单独 checkout 出来都必须全绿）：

1. `fix(aicore): 租约丢失即中止执行，且领取受信号量约束` —— B1、B2、M1、M2、M3、M5
2. `feat(aicore): 失败终态落 error_code，供 4.11 分别计数` —— B3（含 `task_repo.py` 与 3.7 用例的授权改动）

**MUST NOT** `git add`/`git commit`（控制者来提交）；**MUST NOT** 加 `[AI]` 前缀。

---

## 6. 交付时必须附的原始输出（EXIT=0 且与固定计数一致）

```
1) pytest -p no:cacheprovider -o addopts="" tests/unit/test_lease.py tests/unit/test_task_runner.py tests/unit/test_cpu_pool.py -q --durations=8
2) pytest -p no:cacheprovider -o addopts="" -m "not integration" -q          # 期望 1240 passed 附近
3) pytest -p no:cacheprovider -o addopts="" -m "integration" -q              # 期望 33+ passed，0 skip
4) ruff check --no-cache src tests scripts
5) mypy --strict src
6) lint-imports --config .importlinter
7) python scripts/group3_acceptance.py
```
外加：CMD1 的 `--durations` 里那两条 5.01s **必须消失**（改到毫秒级），
以及 Redis 跑完集成段后 `dbsize=0`。
