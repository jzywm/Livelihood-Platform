# Task 4.7 修复轮 **第 5 批**工单（收窄的定向复核结果：无 blocker，1 个 major + 6 个 minor）

**基线**：HEAD `a3aa8e0`（5 个提交已就位、逐提交健康检查全绿）
**来源**：独立复核者在冻结 SHA 上的**定向复核**（`1fed477..a3aa8e0`）
**性质**：修复轮。**B1 是本轮修复新引入的回归，必须修**；其余六条都是"判据太松 / 文档与代码不符"——正是本任务一直在修的那一类。

---

## 0. 复核确认干净的部分（**不要动**，也不要回退）

- **F7 的 join 判据真修好了**：把 `main.py` 的 `await runner_task` 换成 `await asyncio.sleep(0)`（插件 exec 进
  `aicore.main.__dict__`）→ `1 failed`，`At index 1 diff: 'runner.stop' != 'run_forever.end'`，变异连跑 3 次全红、
  生产未变异连跑 5 次全绿；
- **M1 真是"等处理器自己的完成事件（有界）再断言"**：`stopped` 在 `handle` 的 `finally` 置位、
  `wait_for(stopped.wait(), 2.0)`，且置位后处理器**同步**执行 `paid_calls += 1; completed = True`
  ⇒ 不取消必然读到 `completed=True`；换第二个接缝的变异（吞掉取消照样跑完）→ 2 failed；
  自然完成窗口从 0.3s **收紧 5 倍到 0.06s** 后变异仍 2 failed、未变异仍 2 passed ⇒ **事件驱动，不靠时序余量**；
- **F6**：只删 `add_done_callback(...)` 那一行注册（不碰 `_log_runner_death`）→ `1 failed`，
  报错正是「没有死亡**当场**那条日志」；
- **F1/F2/F3 没有误伤正向路径**：上界放大到 5s 后 success 0.001s / `AiCoreError` 0.001s / 任务级超时 0.060s，
  `saw_cancel=False` ⇒ happy path 不白等、正常完成与业务失败都不被取消；
- **F9 与真 Redis（db15）逐项同判、未引入新分歧**；`test_main_assembly.py` 7 passed 且无新恒真判据；
  sleep 那条机械判据是真的；N5 生效（裸收集 `1304/1354 collected (50 deselected)`）。

**⚠ 一条方法论提示**（复核者纠正控制者的错建议，请照办）：
"把处理器改成立即完成"在产品**未变异**时也会红（心跳来不及续期，正确实现也走成功路径）
——**换了场景，不能当判别力探针**。自证必须打在**同一场景**的接缝上。

---

## 1. B1【major·本轮新引入的回归】放弃路径的等待上界是 docstring 的两倍

**实测（生产常量 `CANCEL_WAIT_TIMEOUT_S = 1.0`，处理器吞掉取消永不结束）**：

```
lease lost + swallow-cancel   elapsed = 2.031s   outcome = returned
两条 ERROR：「处理器在 1.0s 内没有响应取消：不再等它…」
```

**根因**：`finally` 里新增的 `await _dissolve_task(handler_task)`（`task_runner.py:801-802`）与
`if lease_lost or timed_out:` 里那次（`:779-783`）**串行各等一整档上界** ⇒ 合计 2×。
`1fed477` 的 `finally` 只有 `_cancel_heartbeat`，故**这是本轮引入的**。
而 `_dissolve_task` 的 docstring（`:1267-1270`）逐字写「**最多再加上**这里的 `CANCEL_WAIT_TIMEOUT_S`」——**不成立**。

**为什么第二次调用是纯浪费**：一个已经吞掉第一次 `cancel()` 的 task，再 `cancel()` 一次它照样吞
⇒ **零收益、纯延迟**（任务级超时可能变成 T+2s，关停 drain 的上界同样翻倍）。

**要求（二选一，理由写进 docstring）**：
- (a) **整个放弃路径共用一个上界**：进入放弃路径时算一次 deadline，后续调用传递**剩余预算**
  （`_dissolve_task` 接受绝对 deadline 或剩余秒数）；或
- (b) **只放弃一次**：`finally` 里仅在"尚未放弃过"时才调 `_dissolve_task`（用局部标记）。
**验收判据**：无论哪条，**总等待 MUST ≤ 一个 `CANCEL_WAIT_TIMEOUT_S`**，且 docstring 写的上界与实际一致。

**并且——这条同样重要**：**F5 用例的 `assert elapsed < bound_s * 3` 恰好放过了它**
（`bound=0.2` ⇒ 0.6 > 0.4，2× 也能过）。**必须把界收紧到能判出 2×**。
**判别力自证（MUST）**：把上界改回"串行各等一档"（内存变异或局部复制控制流），该用例**必须变红**；
产品态必须绿。**"能判红"要能看到红。**

---

## 2. 其余六条（都小，都是"判据/文档不诚实"）

- **B2【minor】F4 的 `0.0` / `-1.5` 两个参数零判别力**。把校验改成 `if False:`（其余不动）→
  `[nan]`/`[inf]` FAILED，而 `0.0`/`-1.5`/`abc` 照样 green——因为"**采用它**（立即超时）"与
  "**兜底**（0.05s 后超时）"的**可观测后果相同**（都是 `mark_failed=1 + 5002`）。
  **要求**：给这两个参数加一条能分开两者的判据（**耗时** `elapsed >= fallback*0.5`，或断言那条
  "非有限值或 `<= 0`"的 ERROR 日志），并给出"变异校验后必须变红"的自证。`nan`/`inf` 那一半已是真判据，保留。
- **B3【minor】`test_pytest_config.py` 的子串判据可被坏配置满足**。实测变异 ini：
  `addopts = -q -m "not integration" -m integration` ⇒ 子串在、判据绿，而裸收集 **50/1354**。
  **根因**：`-m` 是 argparse `store`，**后者覆盖前者**；`-m "not integration_typo"` 同理。
  **要求**：用 `shlex.split` 解析 `addopts` 后断言 **`-m` 恰好出现一次且值恰为 `not integration`**
  （不是子串包含）。**判别力自证**：上述变异 ini **必须让该用例变红**。
- **B4【minor】`-o addopts=""` 的危险没人写明**。已确认**仓库内没有任何命令/文档在用它**（既有门禁没受影响），
  但"清空 `addopts` 会静默恢复 50 条真连 Redis/MySQL 的用例"这句话**要写在人能看见的地方**
  （`test_pytest_config.py` 的模块 docstring 或 `pyproject.toml` 那段注释）。
- **B5【minor】`_require_lease_ms` 里 `bool` 的理由是假的**（`lease.py:323-342`、`test_lease.py:425-426` 都写了）。
  真 Redis + redis-py 8.1.0 实测：`PX True` → **客户端编码期** `DataError: Invalid input of type: 'bool'`，
  **不是**"被悄悄接受成 1 毫秒的租约"。守卫本身无害（两侧仍同判）**保留**，
  **但理由必须改成实测的那一条**——本轮一直在修"文档与代码不符"，不能自己再写一句。
- **B6【minor】一条恒真断言**：`tests/unit/test_task_runner.py:1875`
  `assert not handler.entered or gate is not None  # 处理器确实开工过`——`gate` 自 `:1854` 创建后从未重新赋值
  ⇒ **整条恒真**。删掉它，或改成真正表达"处理器确实开工过"的判据（该覆盖实际已由 `:1869` 的
  `wait_for(handler.started.wait(), timeout=5)` 承担——若如此，删掉即可并在原处留一行注释说明为什么不需要重复断言）。
- **B8【minor】两条自证只钉消息、不钉成因**：
  `test_f7_shutdown_order_guard_discriminates`（`test_main_assembly.py:542`）只断言
  `pytest.raises(AssertionError, match="关停顺序不对")`——**空 `_EVENTS` 也会满足**；
  `test_f1_f3_guard_discriminates`（`test_task_runner.py:2185`）用
  `pytest.raises((ValueError, TypeError))` 两型合一，**无法把每个参数钉在自己的异常类型上**。
  **要求**：改成逐参数钉**具体**异常类型 / 逐项钉**具体**断言消息。
- **B7【只登记，不改】**：新异常**不会**穿出 `run_forever`（真 Redis + `lease_ms=0` 实测：永久
  「领取任务失败（连续第 N 次…）`InvalidLeaseArgumentError`」+ 有界退避、永不领取任何任务）。
  异常类型变更是**安全的**（旧形态的真 Redis `ResponseError` 走同一个 `except Exception`），
  但"一个**永远不会自愈**的编程错误被报成 Redis 抖动"值得登记为**已知行为**（写在报告 §"没做到的事"里即可）。

---

## 3. 纪律（不变）

- **MUST NOT** `git add` / `git commit`（控制者来提交）；**MUST NOT** 改 `pyproject.toml` 的其它行、`.importlinter`、
  以及本工单未点名的既有文件；
- **MUST NOT** 用「改 src + finally 还原」做变异——一律**内存变异**（pytest 插件 `-p` 在运行期替换模块属性，
  或局部复制控制流）；本轮的阳性自证我已在工单里给出实测形态，照着重建即可；
- 探针**上限 2 个**、只放仓库外的 `D:\progrom\.dsh-probe\`、用完即删（含 `__pycache__`）；
- 报告追加"第 5 批"一节到 `task-4.7-fix-report.md`：逐项 `FIXED` / `REGISTERED` + 证据；
  **做不出能判红的自证就停下写明是哪一条**。

## 4. 交付形态

**一个新提交**（不改写已有 5 个）：
`fix(aicore): 放弃路径的等待上界收敛到文档承诺值，并补严三处判据`
（B1 + B2/B3/B4/B5/B6/B8；B7 只登记）。交付后我会再跑一次全套门禁 + 逐提交健康检查。
