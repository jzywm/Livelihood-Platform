# 第 4 批工单 · 追加（来自独立复核第 2 批：假绿普查 + sleep 普查，全部钉在 `1fed477`）

**控制者已逐条复核**；下面每条都写明"要求"与"验收形态"。
**注意**：M1 的修复点就在你正在改的 `tests/unit/test_task_runner.py` 里，顺手做掉。

---

## M1【最高优先·判据零杀伤】B1 的招牌用例钉不住"取消"

**B 的全量实测（`1fed477`）**：把 `execute` 里 `if lease_lost or timed_out:` 改成**只判 `timed_out:`**
（即"租约丢失后不取消处理器"）⇒ `-m "not integration"` 全量 **1268 passed, 13 skipped, 41 deselected, 0 failed**。
**一条都没红。** 隔离复核：同一变异下只跑 `test_renew_failure_abandons_without_any_terminal_write`
→ **2 passed**。

**机制（读代码即可确认）**：该用例的
② `handler.completed is False`（L599）与 ③ `paid_calls == 0`（L602）
都在 `execute` 返回后**立刻**读取。**不取消**时处理器只是**脱离的 task 还在 `sleep(1.0)`**——
此刻 `completed` 当然是 `False`、`paid` 当然还是 `0`，**两种实现下同时为真**；
① `elapsed < 0.5` 也拦不住（心跳 10ms 就发现租约丢失，`execute` 照样早返回）。
而 L563-565 的 docstring 逐字宣称"修复前这两条**必红**"——**与实测矛盾**。

⇒ 也就是说：**把 B1 的修复整个撤掉，全量套件依然全绿。** B1 的回归门禁是空的。

**要求**：断言**必须越过处理器的"本来完成时刻"再复查**。首选形态（事件驱动 + 有界）：
让假处理器在**真的跑完**时置一个完成事件，用例在 `execute` 返回后
`await asyncio.wait_for(handler.finished.wait(), timeout=<有界>)`（用 `suppress(TimeoutError)` 包住），
**然后再**断言 `completed is False` / `paid_calls == 0` / 三类终态零调用。
**MUST NOT** 用固定轮数让出凑（见下 F13）。

**判别力自证（MUST）**：把 `if lease_lost or timed_out:` 变异成只判 `timed_out:`
（**内存变异，MUST NOT 改 src + 还原**），该用例**必须变红**。
`ADDRESSED-BY-REFACTOR` 不接受——要能看到红。

> 说明：**产品侧的行为是对的**（复核者独立验证过：`renew` 首次即 False 时
> `execute` 0.065s 返回、处理器收到 `CancelledError`、付费调用 0）。
> 这一条修的是**判据**，不是产品。但"产品对、判据空"意味着**下次改坏没人拦**。

**同时修掉那句与实测矛盾的 docstring。**

---

## N1【高】`test_unreachable_redis_fails_fast_without_touching_the_row` 名不副实且**独占集成段一半时长**

**实测**：该用例 **25.18s**（集成段 50.10s 的一半）。断言只有 `pytest.raises(Exception)` + 行未变，
**没有任何时延或"只试一次"的判据**——名字里的 "fails fast" 无人验证。
成因不在 aicore：redis-py 8.1.0 默认 `Retry(retries=10)`，裸 `Redis(port=1).ping()` 实测 26.0s。

**要求**（二选一并说明理由）：
(a) 让生产侧**显式不重试**（构造 `RedisLockStore` 时把重试策略定死）——这是**产品行为**决定，
    要 docstring 写清"为什么 Redis 客户端不自动重试"；或
(b) 保留现状，但**把用例名与判据对齐**：名字不再承诺 fail fast，并**登记**"Redis 抖动会被
    redis-py 重试 10 次（≈26s）"，同时给该用例加**有界时延判据**（例如断言 < 5s）——若做不到
    就如实写成"本用例只验证行未被改动，不验证时延"。
**控制者倾向 (a)**：`list_claimable`/`acquire` 上游已有 `run_forever` 的有界退避（A2），
Redis 客户端再叠 10 次内部重试等于把 26s 的尾巴藏在一次"看起来很快"的调用里——
**这正是 A2 当初要消灭的形态**。但**改产品行为必须在报告里单列**，并给出理由与代价。

---

## N2【中】6 处"声称的判据 ≠ 实际判据"（都要求修，都是同一个毛病）

1. `tests/integration/test_runner_redis.py:315-317`：docstring 说"该列为 `None`"，而 L349 断言真实码值；
2. `src/aicore/repository/task_lease_store.py:43-49` 与 `:79-97` **自相矛盾**（第 1 批的 F10，已在工单里）；
3. `tests/unit/test_task_runner.py:10-11` **逐字**写"本文件**没有** `await asyncio.sleep(...)`，
   也没有任何轮询等待"——实际 **13 处豁免**、其中 `L1296`/`L1417`/`L1953` 就是轮询等待；
4. `tests/unit/test_task_runner.py:30` 的索引表把硬约束 7 指向
   `test_concurrency_limit_blocks_the_second_claim`，**该用例全仓不存在**（已改名）；
5. `tests/unit/test_cpu_pool.py:14` 写"共 2 处豁免"，实际 **3** 处；
6. `tests/integration/test_lease_redis.py:18` 写"只有一处 sleep"，实际 **2** 处。

**要求**：逐条改成与代码一致。**MUST NOT 只把数字改对而保留错误的定性**——
第 3 条要么把那三处轮询等待改成条件等待，要么把"没有任何轮询等待"这句**删掉**。
**另加一条机械判据**：写一个（可放在既有 structural 测试里）**扫描判据**，
断言"文件 docstring 里声称的豁免数与实际 `# ai-allow-sleep` 数一致"，
使这类**数字漂移下次自动变红**——否则它一定会再漂。

---

## N3【中】两条"睡一觉再祈祷"（固定轮数 / 固定余量）→ 改条件等待 + 有界 deadline

- `tests/unit/test_task_runner.py:1103-1104`：用**固定 50 轮** `sleep(0)` 代替"等到循环做完"。
  **同文件 L1092-1095 自己记过"实测固定 50 轮偶发不够"**，却把这处留下了。
  它决定 `test_b2_guard_discriminates` 的 `mutant_peak >= 2` ⇒ **该自证本身可能是假红/假绿**。
- `tests/unit/test_task_runner.py:337`：靠"50ms 处理器 vs 10ms 心跳"的 **5× 时间余量**保证心跳跑过一轮。
- `tests/unit/test_cpu_pool.py:87-122`：docstring 称"顺序**不受机器快慢影响**"，
  实际是 10ms vs 100ms 的**时间竞速**（10× 余量）。

**要求**：凡"时序余量/让步轮数**就是判据本身**"的地方，改成**条件等待 + 有界 deadline**
（轮询到条件成立或超时），并把 docstring 改成与实现一致的措辞（第 3 条那句"不受机器快慢影响"**必须改**）。
余量很大的地方（≥10×）可保留但**必须如实写成"靠余量"而不是"不受影响"**。

---

## N4【低】顺手的

- `tests/unit/test_task_runner.py:1807-1817` 只断言 `getattr(cls, "_is_protocol", False)`（纯类型层）——
  补一条**行为**判据（例如把一个结构上满足的对象真的传进去并用起来），或如实说明它只是类型层守卫；
- `tests/repository/test_task_lease_store.py:143-149` 对**刚 import 的常量**断言
  `isinstance(str) and strip()`——这是恒真的自我断言，删掉或换成"与 DDL/er.md 逐字比对"的真判据；
- `test_missing_handler_does_not_break_the_running_loop` **1.02s**：同文件其它用例都传了
  `poll_interval_s=0.0`，它没传 ⇒ 白等一个生产轮询间隔。补上。

---

## N5【裁定·授权】`pyproject.toml` 的 `addopts` 补 `-m "not integration"`

复核者给了明确技术判断，**控制者采纳并授权你改这一行**（**仅此一行**，其余不动）：

- `pyproject.toml:97` 的 marker 描述、以及多份 docstring / `openspec` tasks.md 都承诺
  "**默认不执行**"，但 `addopts` 里既没有 `-m` 也没有 collection hook ⇒ **承诺是空的**，
  `pytest`（不带参数）会**真的收集并执行**集成用例；
- 补上后**全仓的承诺才成立**；而 CLI 的 `-m integration` 会**覆盖 ini**，
  故你现有的门禁命令（`-m "not integration"` / `-m integration`）**不受影响**；
- **不要**改 marker：该文件确实会构造真 `RedisLockStore`（今天不连只是**惰性构造**的偶然），
  摘掉 marker 等于把一个会碰 Redis 的用例放进"默认段 MUST NOT 连 Redis"的段里。

**改完必须自证**：不带 `-m` 跑一次 `pytest --collect-only -q | Select-String integration`，
证明集成用例不再被收集；并照旧跑你那两条带 `-m` 的门禁命令证明**没有变化**。

## N6【裁定·授权】**凭据探测造成的假 skip** 必须修

`tests/integration/test_main_assembly.py:63-68`：`DSH_IT_MYSQL_PASSWORD` 缺失时
**skip 掉 3 条行为用例**，而那 3 条**一条外部依赖都不需要**（死端口下 4 passed 已证）
⇒ 这是**静默砍覆盖**的形态，比 marker 问题更值得修。
**要求**：让 skip 条件与该用例的**真实需求**对齐（不需要 MySQL 就不许因 MySQL 凭据缺失而 skip）；
若某条确实需要，就把它需要的那个依赖作为条件。

---

## N7【登记】无界挂死清单（不要求全修，按下面区分）

- **已证实的无界挂死（唯一一处，**必须修**）**：`tests/integration/test_main_assembly.py` 的 3 条行为用例
  文件里**没有任何超时**——删掉 `runner_stop.set()` 后后台跑 >8 分钟零输出、只能 job_kill。
  凡"`stop` 没被 set / 执行器桩永不返回"的回归都会让 **CI 挂住而不是变红**。
  ⇒ **给这些用例加有界 deadline**（超时以断言失败收场）。**"挂死"在 CI 上比"变红"贵一个数量级。**
- **潜在无界（只登记）**：裸 `await runner.execute(...)` 四处
  （`test_task_runner.py:394/:412/:1357/:1579`、`test_runner_redis.py:253`、Harness 的 `claim_and_execute`）——
  只在产品侧"处理器返回前就卡住"时才真挂（今天"永不返回"的处理器都带 0.01s 超时），暴露面低。
  登记即可，**不必**逐个包 `wait_for`。
- **有界但会把回归显示成 5s TimeoutError**：`await` 真 `run_forever` 处都包了 `wait_for`——
  不挂死，但一次回归烧 5s 且形态不是语义化断言。登记即可。

---

## 交付与纪律（不变）

- 上面全部并入**第 4 批**的**两个新提交**（M1/N2/N3/N4 多在 `test_task_runner.py`，与 F1/F2/F3 同一批）；
- **MUST NOT** `git add`/`commit`；**MUST NOT** 用"改 src + finally 还原"做变异（一律内存变异）；
- 探针上限 2 个、只放 `D:\progrom\.dsh-probe\`、用完即删；
- 报告追加"第 4 批"一节，逐项状态表：`FIXED` / `REGISTERED` / `STILL-PRESENT` + 证据；
  **做不出能判红的自证就停下写明是哪一条**。
