"""`core/task_runner.py` 的执行器内核用例（工单 §3.2 的 13 条 + 结构断言）。

## 时钟与等待的处置（本文件最容易写错的地方）

工单 §2.5 硬约束 3 要求「心跳按 `lease_ms // 3` 间隔 `renew`」，而
`tests/conftest.py` 又逐字禁止「测试内任意 sleep」。两者不冲突，但**必须分清哪一段在等**：

- **心跳的间隔是生产代码的 `asyncio.sleep`**，不是用例在等：用例把 `lease_ms` 取成 30ms
  （→ 心跳 10ms），于是「心跳确实跑过一轮」是**可观测**的，而整个用例的墙钟成本只有几十毫秒；
- **用例自己的等待分三类**（`# ai-allow-sleep:` 逐处豁免，理由写在行末）：

  | 类别 | 处数 | 说明 |
  |---|---|---|
  | `sleep(0)`：只让出一次调度（收尾用） | 3 | 不等待，把控制权交给执行器/心跳协程 |
  | 条件等待里的轮询（**都有界 deadline**） | 5 | 等"某件事发生了"（落账、跑够轮数、进入退避） |
  | 真实时间窗口（**判据本身就是时间**） | 4 | 心跳是否仍在续期、模拟处理器耗时、变异体心跳 |

  第 3 类里"观察泄漏"那一处**必须**真等而不能只 `sleep(0)`：泄漏的心跳是**生产代码**
  在按 10ms 的间隔自我调度，事件循环让出多少次都不能保证它跑过一轮——
  只有跨过它的间隔才是"它还在续期"的证据。
  **本文档此前逐字写着"本文件没有 `await asyncio.sleep(...)`、也没有任何轮询等待"——
  那是错的**（当时已有 13 处豁免，其中 3 处就是轮询等待）。数字由
  `tests/structural/test_sleep_exemption_counts.py` 机械核对，MUST NOT 手写后再也不改。

睡眠豁免：12 处（机械判据逐文件比对，见 `tests/structural/test_sleep_exemption_counts.py`）。

## 「第几次尝试」怎么被用例控制

`TaskRunner` 从 `claim_once` 拿到的 `TaskClaim.attempt` 决定退避 / 转人工。
故本文件的锁替身**记录**每次 `acquire` 生成的 claim，`execute` 时按 `task_id` 取回
（`harness.claim_of(task_id)`）显式传入——这既是生产时序的复现，也让
「第 4 次失败要转人工」这类用例能精确地站在指定的尝试序号上。

## 每条硬约束的用例在哪里

| 硬约束（工单 §2.5） | 用例 |
|---|---|
| 1 领取顺序（第一个成功即返回） | `test_claim_once_returns_the_first_task_whose_lease_is_free` |
| 2 `begin_attempt` 在心跳之前 | `test_begin_attempt_is_written_before_the_heartbeat_starts` |
| 3 续期假 / 抛异常 → 放弃且不写终态 | `test_renew_failure_abandons_without_any_terminal_write` |
| 4 任务级超时用 handler 声明的值 | `test_handler_timeout_goes_through_the_failure_path_with_5002` |
| 5 失败分流两条 | `test_backoff_delays_grow_exponentially` 等三条（见下） |
| 6 先写库后释放租约 | `test_mark_succeeded_precedes_lease_release` |
| 7 背压（先拿许可再领取） | `test_leases_held_never_exceed_the_concurrency_limit` |
| 8 `stop` 可打断 | `test_run_forever_stops_promptly_when_the_event_is_already_set` |
| §2.8 处理器缺失必须显式失败 | `test_missing_handler_is_not_silently_skipped` |

> 更正（本轮）：本表第 7 行此前指向 `test_concurrency_limit_blocks_the_second_claim`
> ——**该用例全仓不存在**（用例在 B2 修复时改名为上面这条）。索引表指错名字比没有表更糟：
> 它让人以为"这一条有覆盖"，而实际去搜是空的。

硬约束 5 的三条：`test_backoff_delays_grow_exponentially`（退避逐项相等）、
`test_over_limit_turns_to_manual_review`（超限转人工）、
`test_non_retryable_policy_skips_backoff_entirely`（`retryable=False` 不退避）。

## 修复轮新增的判据（每条都带判别力自证）

| 判据 | 自证（同一份判据必须能判红） |
|---|---|
| B1 租约丢失 ⇒ 取消处理器且不写终态 | `test_m1_abandon_guard_discriminates`（内存变异） |
| F1/F2/F3 心跳 MUST NOT 泄漏 | `test_f1_f3_guard_discriminates` / `test_f2_guard_discriminates` |
| F4 不可用的 `timeout_s` 声明 → 兜底 | 参数化本身即"修复前必红"（`nan`/`inf` 会挂） |
| F5 取消后的等待有界 | `test_f5_bound_guard_discriminates` |
| A2 领取失败不杀循环 | `test_a2_guard_discriminates` |
| B2 许可先于领取 | `test_b2_guard_discriminates` |

判据本体集中在少数几个助手里（`_assert_lease_lost_abandons` /
`_assert_no_heartbeat_leak` / `_assert_abandoned`），自证喂的就是它们——
"自证"与"真判据"因此不会各自漂移。
"""

from __future__ import annotations

import ast
import asyncio
import logging
import sys
import threading
import time
import types
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from aicore.core.errors import (
    CHANNEL_FAILURE_CODE,
    INTERNAL_ERROR_CODE,
    AiCoreError,
    ChannelFailureError,
)
from aicore.core.lease import InMemoryLockStore, InMemoryState, TaskClaim
from aicore.core.task_runner import (
    HEARTBEAT_DIVISOR,
    ClaimedTask,
    RunnerConfig,
    TaskHandler,
    TaskPolicy,
    TaskRunner,
    TaskStore,
)
from aicore.service.task.registry import REGISTRY

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUNNER_PATH = PROJECT_ROOT / "src" / "aicore" / "core" / "task_runner.py"

#: 结构性判据共享的禁用包清单（两处判据 + 一处判别力自证都用它，MUST NOT 各写一份）。
FORBIDDEN_CORE_IMPORTS = (
    "aicore.service",
    "aicore.repository",
    "aicore.provider",
    "aicore.port",
    "aicore.api",
)

TASK_TYPE = "OCR"
ACCOUNT = "acc_0000000000000000000000000001"
CREATED_AT = datetime(2026, 9, 16, 10, 30, tzinfo=UTC)
LEASE_MS = 30_000
#: 心跳用例的短租约：30ms → 心跳间隔 10ms（`HEARTBEAT_DIVISOR = 3`）。
SHORT_LEASE_MS = 30


class FakeClock:
    """**只给锁替身用的**可注入假时钟（形状同 `provider/guard.py` 的 `StepClock`）。

    ## 为什么它不再是 `TaskRunner` 的形参（本轮删掉，M2）

    `TaskRunner(clock=...)` 曾是死接口：`self._clock` 赋了值却从不被读。
    现在 `TaskRunner` **没有** `clock` 形参，理由写在它的 `__init__` docstring 里
    （写库时间只能墙钟、心跳等待必须是真的）。

    本类仍被 `RecordingLockStore` 用来判租约是否过期——那是**内存锁店**的时间轴，
    不是执行器的时间轴，两者互不影响：`run_failed_attempt` 靠 `advance()`
    让"上一个租约过期"（对应真实 Redis 的 `PX` 到期）。
    """

    def __init__(self, now: float = 1000.0) -> None:
        self.now = now
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds

    def advance(self, seconds: float) -> None:
        """手动推进虚拟时间（**不经过睡眠**，用例模拟「租约过期」用）。"""
        self.now += seconds


def _claimed(task_id: str, task_type: str = TASK_TYPE) -> ClaimedTask:
    return ClaimedTask(
        task_id=task_id,
        task_type=task_type,
        account_id=ACCOUNT,
        created_at=CREATED_AT,
    )


class FakeStore:
    """`TaskStore` 替身：记录**每一次**调用与顺序（顺序本身是要断言的契约）。

    `events`（共享时间线，跨组件顺序断言用）与 `calls`（本替身自己的调用列表，次数断言用）
    是两个视角：只有后者能把「零调用」写成一行断言。
    """

    def __init__(
        self,
        tasks: Sequence[ClaimedTask] = (),
        events: list[str] | None = None,
        *,
        exclude_begun: bool = False,
    ) -> None:
        self._tasks = list(tasks)
        self.events: list[str] = [] if events is None else events
        self.calls: list[tuple[str, str]] = []
        #: 每个方法被调用时的线程 ident（断言「经 `run_in_threadpool` 调用」用）。
        self.thread_ids: list[int] = []
        #: 下一次（及之后若干次）`list_claimable` 要抛的异常（**A2 用**：模拟瞬时故障）。
        self.claim_failures: list[Exception] = []
        #: 已被写回终态 / 已重排队的任务（**真** `SqlTaskLeaseStore.list_claimable` 里
        #: `WHERE status = 'PROCESSING'` 的自然结果）：
        #: - 成功/失败 → 状态离开 `PROCESSING`，再也扫不到；
        #: - 重排队 → 仍在 `PROCESSING`，但紧接着会被 `locks.defer()` 挡住，
        #:   故在替身里也直接排除（否则 `run_forever` 会在退避窗口内反复领到同一个任务）。
        #: 没有这本账时，替身每轮都交出同一个任务，`run_forever` 会把它跑上无数次——
        #: 那既不是生产行为，也让并发类断言失去判别力。
        self._not_claimable: set[str] = set()
        #: **`list_claimable` 是否排除"本轮已 `begin_attempt` 的行"**。
        #:
        #: 这不是"加了个测试专用的假特性"，而是 `TaskStore` 的**另一种合法实现**：
        #: 「我自己正在处理的行，对我自己而言不是可领取的」——真实仓储完全有理由这么写
        #: （例如 `begin_attempt` 把行标成 `status='RUNNING'` 的实现）。
        #:
        #: **它的存在是本轮的一个教训**（控制者的探针否证了我的一个结论）：第一版只有
        #: `exclude_begun=False` 这一种窗口语义，于是"许可满时窗口里只剩自己领不到的那一行"，
        #: 「同时持有的租约数」对"先拿许可"与"先领取"两种实现**都给 1**——
        #: 我据此写下"结构上不可能超过 1"。那句话是**替身的性质**，不是契约的性质：
        #: 换成 `exclude_begun=True` 之后，修复前的形态**真的会持有 2 个租约**
        #: （见 `test_b2_guard_discriminates` 的实测）。
        self.exclude_begun = exclude_begun
        self._begun: set[str] = set()

    def _record(self, method: str, task_id: str) -> None:
        self.calls.append((method, task_id))
        self.thread_ids.append(threading.get_ident())
        self.events.append(f"store.{method}:{task_id}")

    def names(self) -> list[str]:
        return [name for name, _ in self.calls]

    def count(self, method: str) -> int:
        return self.names().count(method)

    def list_claimable(self, *, limit: int, now: datetime) -> Sequence[ClaimedTask]:
        self._record("list_claimable", f"limit={limit}")
        if self.claim_failures:
            raise self.claim_failures.pop(0)
        return [
            task
            for task in self._tasks
            if task.task_id not in self._not_claimable
            and not (self.exclude_begun and task.task_id in self._begun)
        ][:limit]

    def begin_attempt(self, task_id: str, *, account_id: str, created_at: datetime) -> None:
        self._record("begin_attempt", task_id)
        self._begun.add(task_id)

    def mark_succeeded(
        self,
        task_id: str,
        *,
        account_id: str,
        created_at: datetime,
        progress: int,
        finished_at: datetime,
    ) -> None:
        self._record("mark_succeeded", task_id)
        self._not_claimable.add(task_id)
        self.events.append(f"progress={progress}")
        self.events.append(f"finished_at_aware={finished_at.tzinfo is not None}")

    def mark_failed(
        self,
        task_id: str,
        *,
        account_id: str,
        created_at: datetime,
        error_code: str,
        finished_at: datetime,
    ) -> None:
        self._record("mark_failed", task_id)
        self._not_claimable.add(task_id)
        self.events.append(f"error_code={error_code}")
        self.events.append(f"finished_at_aware={finished_at.tzinfo is not None}")

    def requeue(self, task_id: str, *, account_id: str, created_at: datetime) -> None:
        self._record("requeue", task_id)
        self._not_claimable.add(task_id)


class RecordingLockStore:
    """锁替身：把三个动作记进**共享时间线**，记录每次 `acquire` 生成的 claim，可改变续期行为。"""

    def __init__(
        self,
        *,
        events: list[str] | None = None,
        renew_result: bool = True,
        renew_error: Exception | None = None,
        claimable: Sequence[str] | None = None,
    ) -> None:
        self.events: list[str] = [] if events is None else events
        # 内部锁店用**自己的**假时钟（不是 runner 的——runner 已无时钟形参）。
        # 这样 `harness.clock.advance(...)` 只影响"租约是否过期"这一件事，
        # 对应真实 Redis 的 `PX` 到期。
        self._clock = FakeClock()
        self._inner = InMemoryLockStore(state=InMemoryState(self._clock))
        #: `None` = 全部可领取（走内部真锁店）；给了序列 = **只有这些 task_id 可领取**。
        #:
        #: 为什么需要后者：真锁店（内存）的 `release` 会把键**删掉**，于是
        #: `claim_once` 的「第一个抢不到就试下一个」用例里，被 `release` 掉的那个任务
        #: 又变成可领取了——用例想表达的是「**别人正持有** task-a」，
        #: 而"持有"在真锁店上的唯一表达是"租约未过期"（不是"被 release 过"）。
        #: 故这类用例显式声明"哪些任务此刻可被本实例领取"，把环境条件写明。
        self._claimable = None if claimable is None else set(claimable)
        self._renew_result = renew_result
        self._renew_error = renew_error
        self.acquire_calls: list[str] = []
        self.renew_calls: list[TaskClaim] = []
        self.release_calls: list[TaskClaim] = []
        self._claims: dict[str, TaskClaim] = {}
        #: **第一次续期成功**时置位。
        #:
        #: 给"需要心跳真的跑过一轮"的用例当**条件**用（N3）：此前那条用例靠
        #: "处理器 50ms vs 心跳 10ms"的 5× 余量去赌心跳跑了一轮——余量不是判据，
        #: 机器一慢就变成"心跳根本没跑"的空断言（而且它还是绿的）。
        self.first_renew = asyncio.Event()

    @property
    def clock(self) -> FakeClock:
        """内部锁店的时间轴（用例靠 `advance()` 让租约过期）。"""
        return self._clock

    def claim_of(self, task_id: str) -> TaskClaim:
        """`acquire` 为该任务生成的那个 claim（用例把它显式交给 `execute`）。"""
        return self._claims[task_id]

    async def acquire_from_another_instance(
        self, task_id: str, *, lease_ms: int
    ) -> TaskClaim | None:
        """**另一个实例**能否领到这个任务（F1/F2/F3 判据 ④）。

        它与 `acquire` 的两点差别都是刻意的：

        - **不记进调用序列**（`acquire_calls` / `events`）：这是"别的实例"的动作，
          记进来会污染判据 ② 的 `renew` 计数口径；
        - **先把内部时钟推过租约**：真实世界里"另一个实例来领"总是发生在
          "上一个持有者的租约已到期"之后——`SET NX` 只对**过期**的键成功。
          不推时钟的话，本判据退化成一个平凡的假（谁在自己持有期间都领不到）。

        底层键空间（`InMemoryState`）与主实例**共用一份**（同一个 Redis），
        但客户端是**另一个对象**——这正是"另一个实例"在内存锁店上的唯一表达。
        """
        self._clock.advance(lease_ms / 1000.0 * 2.0)
        other = InMemoryLockStore(state=self._inner.state)
        return await other.acquire(task_id, lease_ms=lease_ms)

    async def acquire(self, task_id: str, *, lease_ms: int) -> TaskClaim | None:
        self.acquire_calls.append(task_id)
        self.events.append(f"locks.acquire:{task_id}")
        if self._claimable is not None and task_id not in self._claimable:
            return None
        claim = await self._inner.acquire(task_id, lease_ms=lease_ms)
        if claim is not None:
            self._claims[task_id] = claim
        return claim

    async def renew(self, claim: TaskClaim, *, lease_ms: int) -> bool:
        self.renew_calls.append(claim)
        self.events.append(f"locks.renew:{claim.task_id}")
        if self._renew_error is not None:
            raise self._renew_error
        if self._renew_result:
            self.first_renew.set()
        return self._renew_result

    async def release(self, claim: TaskClaim) -> bool:
        self.release_calls.append(claim)
        self.events.append(f"locks.release:{claim.task_id}")
        return await self._inner.release(claim)

    async def is_deferred(self, task_id: str) -> bool:
        return False

    async def defer(self, task_id: str, *, delay_s: float) -> None:
        self.events.append(f"locks.defer:{task_id}:{delay_s}")

    async def close(self) -> None:
        return None


class FakeHandler:
    """`TaskHandler` 替身：可配置超时、立即失败、或挂到被取消。"""

    def __init__(
        self,
        *,
        events: list[str] | None = None,
        timeout_s: float = 5.0,
        failure: AiCoreError | None = None,
        hang: bool = False,
        delay_s: float = 0.0,
    ) -> None:
        self.events: list[str] = [] if events is None else events
        self._timeout_s = timeout_s
        self._failure = failure
        self._hang = hang
        self._delay_s = delay_s
        self.handled: list[str] = []

    def timeout_s(self) -> float:
        return self._timeout_s

    async def handle(self, task: ClaimedTask) -> None:
        self.handled.append(task.task_id)
        self.events.append(f"handler.handle:{task.task_id}")
        if self._hang:
            # 挂到被 `wait_for` 取消：**不是**用例在等，是它在等超时。
            await asyncio.Event().wait()
        if self._delay_s:
            # 模拟处理器耗时，让心跳在它运行期间真跑一轮（≤0.05s）。
            await asyncio.sleep(self._delay_s)  # ai-allow-sleep: 模拟处理器耗时 50ms，让心跳触发
        if self._failure is not None:
            raise self._failure


class Harness:
    """一次用例的装配：runner + 两个替身 + 一条共享事件时间线。"""

    def __init__(
        self,
        *,
        tasks: Sequence[ClaimedTask] = (),
        handlers: Mapping[str, TaskHandler] | None = None,
        policies: Mapping[str, TaskPolicy] | None = None,
        config: RunnerConfig | None = None,
        renew_result: bool = True,
        renew_error: Exception | None = None,
        handler: Any = None,
        claimable: Sequence[str] | None = None,
    ) -> None:
        self.events: list[str] = []
        self.store = FakeStore(tasks, events=self.events)
        self.locks = RecordingLockStore(
            events=self.events,
            renew_result=renew_result,
            renew_error=renew_error,
            claimable=claimable,
        )
        #: 锁替身的时间轴（**不是** runner 的——runner 没有时钟形参，见 `FakeClock` 的 docstring）。
        self.clock = self.locks.clock
        self.handler = handler if handler is not None else FakeHandler(events=self.events)
        self.handler.events = self.events
        self.runner = TaskRunner(
            store=self.store,
            locks=self.locks,
            handlers={} if handlers is None else handlers,
            policies=REGISTRY if policies is None else policies,
            config=config or RunnerConfig(lease_ms=LEASE_MS, max_retries=3, concurrency_limit=4),
        )

    def short_heartbeat_config(self, *, max_retries: int = 3) -> RunnerConfig:
        """心跳一定会跑一轮的配置（30ms 租约 → 10ms 间隔）。"""
        return RunnerConfig(
            lease_ms=SHORT_LEASE_MS, max_retries=max_retries, concurrency_limit=4
        )

    async def claim_and_execute(self, task_id: str) -> None:
        """经真 `claim_once` 领取后执行，并把该任务的真 claim 交给 `execute`。

        为什么显式传 `claim=`：`TaskRunner` 内部会把 `claim_once` 拿到的 claim 按 `task_id`
        存起来供 `execute` 取回；用例直接调 `execute` 时那份记录不存在，若走"合成 claim"
        路径，`renew` 会拿到空 token 而被真锁店判 `False`——那会把「成功路径」测成「放弃路径」。
        显式传入使本方法测的正是生产那条时序。
        """
        claimed = await self.runner.claim_once()
        assert claimed is not None, "替身 store 必须给出该任务，否则用例的装配错了"
        assert claimed.task_id == task_id
        await self.runner.execute(claimed, claim=self.locks.claim_of(task_id))

    async def run_failed_attempt(self, attempt: int, *, task_id: str = "task-a") -> None:
        """在**指定的尝试序号**上跑一次失败（`attempt` 由锁替身的 `acquire` 决定）。

        先领取 `attempt` 次（每次把租约过期，让下一次领取成功并累加计数），
        最后一次的 claim 才是交给 `execute` 的那个。
        """
        for _ in range(attempt - 1):
            claim = await self.locks.acquire(task_id, lease_ms=LEASE_MS)
            assert claim is not None
            expected = _ + 1
            assert claim.attempt == expected, (
                f"锁店的尝试计数没有连续累加：{claim.attempt} != {expected}"
            )
            self.clock.advance(LEASE_MS / 1000 + 0.5)  # 让租约过期，下一次领取是新的尝试
        claimed = await self.runner.claim_once()
        assert claimed is not None
        await self.runner.execute(claimed, claim=self.locks.claim_of(task_id))


def _failure() -> AiCoreError:
    """一个带明确业务码的失败（用 `4003`：与超时 `5002` 区分，本文件两条路径都要用）。"""
    return ChannelFailureError("上游通道返回 503")


# ---------------------------------------------------------------------------
# 9. 原子领取：并发领取不重复
# ---------------------------------------------------------------------------
async def test_concurrent_claims_never_double_assign_a_task() -> None:
    """9. N 个协程同时 `claim_once()`，**恰好一个**拿到手，其余返回 `None`。"""
    harness = Harness(tasks=[_claimed("task-a")])

    results = await asyncio.gather(*[harness.runner.claim_once() for _ in range(10)])

    got = [item for item in results if item is not None]
    assert len(got) == 1, f"并发领取拿到了 {len(got)} 个任务：同一任务会被重复执行"
    assert got[0].task_id == "task-a"
    assert harness.locks.acquire_calls.count("task-a") == 10, (
        "10 个协程都试了同一个任务，但只有 1 次应当成功（锁店返回了 1 个非 None）"
    )


async def test_claim_once_returns_the_first_task_whose_lease_is_free() -> None:
    """硬约束 1：第一个抢不到就**试下一个**，MUST NOT 重试同一个。

    `claimable=("task-b", "task-c")` 显式声明「此刻只有这两个能被本实例领到」
    ——那正是「别人正持有 task-a」在生产上的样子（租约未过期）。

    **另有一条隐性判据**：`list_claimable` 必须回一批（`limit=concurrency_limit`）而不是
    只回一行。若回一行，「试下一个」结构上不可达（第一个候选被占 → 本轮一个都领不到）——
    第一版就是这么写的，本用例正是抓到它的那一条。故这里同时断言
    `acquire` 试了 task-a 与 task-b 两个。
    """
    harness = Harness(
        tasks=[_claimed("task-a"), _claimed("task-b"), _claimed("task-c")],
        claimable=("task-b", "task-c"),
    )

    claimed = await harness.runner.claim_once()

    assert claimed is not None
    assert claimed.task_id == "task-b", "被占用的任务没有被跳过，而是重试了同一个"
    assert harness.locks.acquire_calls == ["task-a", "task-b"], (
        f"领取顺序错：{harness.locks.acquire_calls}（应逐个试、第一个成功即停）"
    )


async def test_claim_once_returns_none_when_every_lease_is_taken() -> None:
    """补充：全部被占时返回 `None`（不抛异常，也不返回被占的任务）。"""
    harness = Harness(tasks=[_claimed("task-a")], claimable=())

    assert await harness.runner.claim_once() is None
    assert harness.locks.acquire_calls == ["task-a"], "应当试过它、失败、然后如实返回 None"


# ---------------------------------------------------------------------------
# 10. begin_attempt 先于心跳
# ---------------------------------------------------------------------------
class _WaitForFirstRenewHandler:
    """处理器**挂到"心跳至少续过一次"为止**（N3：把时间余量换成条件）。

    此前这条用例是 `FakeHandler(delay_s=0.05)`：靠"处理器 50ms vs 心跳 10ms"的
    **5 倍余量**去赌心跳跑过一轮。余量不是判据——机器慢/全量套件并发时它可能不成立，
    而那时用例**照样是绿的**（断言 `renew_calls` 非空会红，但"5×"这句话本身没人验）。

    这里改成**事件驱动**：处理器等 `RecordingLockStore.first_renew`（第一次续期成功时置位），
    带**有界**上界防止"心跳根本没跑"把用例挂死；超时则显式记下 `timed_out`，
    由用例断言——于是"心跳真的跑过一轮"从**赌**变成了**被检查的前提**。
    """

    def __init__(self, first_renew: asyncio.Event, *, budget_s: float = 2.0) -> None:
        self._first_renew = first_renew
        self._budget_s = budget_s
        self.entered = False
        self.timed_out = False

    def timeout_s(self) -> float:
        # 远大于等待上界：本用例要证的是"心跳跑过一轮"，不是"任务级超时"。
        return 30.0

    async def handle(self, task: ClaimedTask) -> None:
        self.entered = True
        try:
            await asyncio.wait_for(self._first_renew.wait(), timeout=self._budget_s)
        except TimeoutError:
            self.timed_out = True


async def test_begin_attempt_is_written_before_the_heartbeat_starts() -> None:
    """10. 领取成功后**先** `begin_attempt` 再起心跳（调用顺序断言）。

    判据的前提是"心跳**确实**跑过至少一轮"——否则「先 begin 再心跳」会因为
    「心跳根本没跑」而变成**空断言**。前提由处理器**等**第一次续期成功来保证
    （事件驱动 + 有界上界，见 `_WaitForFirstRenewHandler`），不再靠时间余量去赌。
    """
    harness = Harness(tasks=[_claimed("task-a")])
    handler = _WaitForFirstRenewHandler(harness.locks.first_renew)
    harness.runner = TaskRunner(
        store=harness.store,
        locks=harness.locks,
        handlers={TASK_TYPE: handler},
        policies=REGISTRY,
        config=harness.short_heartbeat_config(),
    )

    await harness.runner.run_once()

    assert handler.entered, "处理器没被启动：本用例的前提不成立"
    assert not handler.timed_out, (
        "2s 内心跳一次都没续期：本用例的判据前提不成立（先查心跳，别把空断言当绿）"
    )
    assert harness.store.count("begin_attempt") == 1
    assert harness.locks.renew_calls, "心跳一轮都没跑：30ms 租约 → 10ms 间隔"
    first_begin = harness.events.index("store.begin_attempt:task-a")
    first_renew = next(
        i for i, item in enumerate(harness.events) if item.startswith("locks.renew:")
    )
    assert first_begin < first_renew, (
        f"心跳先于事实源写回：{harness.events}（事实源会显示『有租约但没人处理』）"
    )


# ---------------------------------------------------------------------------
# 11 / 12. 续期失败 → **取消处理** + 放弃（B1 的验收形态）
# ---------------------------------------------------------------------------
class _BadTurnHandler:
    """「本来要跑很久、且只在跑完后才产生外部副作用」的处理器。

    它刻意写成**三行有顺序的代码**，因为这正是修复前失效的地方：

    ```python
    await asyncio.sleep(self.delay_s)   # 模拟下游调用（可被取消，取消点在这里）
    self.paid_calls += 1                # 外部副作用（付费调用）
    self.completed = True               # 只有真的跑完才置位
    ```

    修复前：租约 10ms 就丢了，但没人取消它 → 它跑到 `sleep` 结束 → **`paid_calls` 变成 1**、
    `completed` 变成 `True`（正是 `design.md:208` 要防的重复外部调用）。
    修复后：心跳先结束 → `execute` 取消这个 task → `CancelledError` 在 `sleep` 处抛出，
    后两行**永远不执行**。

    `timeout_s` 取 **5.0**（远大于用例的墙钟预算）：这样"用例是靠租约丢失结束的"而不是
    靠任务级超时结束的——修复前那版用例用的是 `FakeHandler(hang=True)` + `timeout_s=5.0`，
    结果**两个参数各耗时 5.01s**，绿色其实来自超时（假绿，M1）。
    """

    def __init__(self, *, delay_s: float, timeout_s: float = 5.0) -> None:
        self._delay_s = delay_s
        self._timeout_s = timeout_s
        self.entered = False
        self.completed = False
        #: 「付费调用」次数：外部副作用，**只有跑完才会 +1**。
        self.paid_calls = 0
        #: **处理器真的不再运行**（跑完 / 被取消）时置位。
        #:
        #: 为什么必须有这个事件（M1）：`execute` 返回的那一刻，"
        #: `completed is False` / `paid_calls == 0`" 在**修复前后同时为真**——
        #: 不取消时处理器只是一个**脱离的 task 还在 sleep**，此刻它当然还没跑完。
        #: 判据要能判红，就必须**越过它本来会跑完的那一刻**再复查；
        #: 而"那一刻"只能由处理器自己报出来（`finally`），不能靠固定轮数让出去猜。
        self.stopped = asyncio.Event()

    def timeout_s(self) -> float:
        return self._timeout_s

    async def handle(self, task: ClaimedTask) -> None:
        self.entered = True
        try:
            await asyncio.sleep(self._delay_s)  # ai-allow-sleep: 模拟处理器耗时，由取消/跑完结束
        finally:
            # 两条路径都会到这里：跑完（正常结束）与被取消（`CancelledError`）。
            self.stopped.set()
        self.paid_calls += 1
        self.completed = True


async def _assert_lease_lost_abandons(
    harness: Harness, handler: Any, *, elapsed: float, budget_s: float = 2.0
) -> None:
    """**「租约丢失 ⇒ 真的放弃执行」的判据本体**（B1 的 ① + ②③ + 四类写回零调用）。

    抽成一个函数是为了让**判别力自证把同一份判据喂给变异体**（M1）——
    若断言散在用例体里，自证只能复制一份判据，于是"自证"与"真判据"会各自漂移，
    而漂移过的自证恰恰证明不了真判据能判红。

    ## 为什么要先等 `stopped`（M1 的修复点）

    `execute` 返回的那一刻，② `completed is False` 与 ③ `paid_calls == 0`
    **在修复前后同时为真**：不取消处理器时它只是一个脱离的 task 还在 `sleep`，
    此刻它当然还没跑完。实测（控制者复核）：把取消路径整个撤掉，
    `-m "not integration"` 全量 **1268 passed / 0 failed**，一条都没红。

    故这里先等处理器的 `stopped` 事件（`handle` 的 `finally` 置位：跑完与被取消**都会**置位），
    **越过它本来会跑完的那一刻**再读 ②③。于是：

    - **修复后**：取消在 `_dissolve_task` 里完成，`stopped` 在 `execute` 返回前就已置位 → 判据为真；
    - **修复前（取消被撤掉）**：`stopped` 要等处理器自己睡醒才置位 →
      此刻 `completed is True` / `paid_calls == 1` → **判据变红**。

    `budget_s` 只是防"处理器永不停止"把用例挂死（N7 的纪律：挂死比变红贵一个数量级）。
    """
    assert handler.entered, "处理器一次都没被启动：①③ 会退化成平凡真（假绿）"
    assert elapsed < 0.5, (
        f"execute 花了 {elapsed:.3f}s 才返回：它等的是处理器或任务级超时，"
        f"而不是租约丢失（10ms 后心跳就该发现）——这正是 B1：没有放弃执行"
    )
    stopped = await _wait_handler_stopped(handler, budget_s=budget_s)
    assert stopped, (
        f"处理器 {budget_s}s 内既没跑完也没被取消：本判据的 ②③ 无法判定（先修这个）"
    )
    assert handler.completed is False, (
        "处理器**跑完了**：租约丢失后没有取消它，`design.md:208` 的「放弃执行」没落地"
    )
    assert handler.paid_calls == 0, (
        f"外部副作用发生了 {handler.paid_calls} 次：重复外部调用（会产生真实费用）"
    )
    assert harness.store.count("mark_succeeded") == 0, "续期失败后写了成功终态"
    assert harness.store.count("mark_failed") == 0, "续期失败后写了失败终态"
    assert harness.store.count("requeue") == 0, "续期失败后把任务重新排队了"
    assert harness.store.count("begin_attempt") == 1, (
        "begin_attempt 仍应写一次（放弃发生在它之后：事实源上留一行 PROCESSING 是对的，"
        "它会被租约过期后的回收者接走）"
    )


async def _wait_handler_stopped(handler: Any, *, budget_s: float) -> bool:
    """等处理器**真的不再运行**（跑完或被取消），返回是否在预算内停下来。

    有界（`budget_s`）是刻意的：无界的 `await` 会把"处理器永不停止"这种回归
    显示成**挂死**，而挂死在 CI 上比变红贵一个数量级（N7 的纪律）。
    """
    try:
        await asyncio.wait_for(handler.stopped.wait(), timeout=budget_s)
    except TimeoutError:
        return False
    return True


def _assert_abandoned(harness: Harness, handler: Any) -> None:
    """**B1 的判据本体**：处理器没跑完、没有副作用、三类终态零调用。

    `_assert_lease_lost_abandons` 在等处理器停下来之后调用它；单独立一个函数是给
    **第二条判别力自证**（`_DetachedOnCancelHandler`，纯替身变异、不碰产品源码）用的。
    """
    assert handler.completed is False, (
        "处理器**跑完了**：租约丢失后没有取消它，`design.md:208` 的「放弃执行」没落地"
    )
    assert handler.paid_calls == 0, (
        f"外部副作用发生了 {handler.paid_calls} 次：重复外部调用（会产生真实费用）"
    )
    assert harness.store.count("mark_succeeded") == 0, "续期失败后写了成功终态"
    assert harness.store.count("mark_failed") == 0, "续期失败后写了失败终态"
    assert harness.store.count("requeue") == 0, "续期失败后把任务重新排队了"
    assert harness.store.count("begin_attempt") == 1, (
        "begin_attempt 仍应写一次（放弃发生在它之后：事实源上留一行 PROCESSING 是对的，"
        "它会被租约过期后的回收者接走）"
    )


@pytest.mark.parametrize(
    ("renew_result", "renew_error"),
    [(False, None), (True, RuntimeError("redis 抖动"))],
    ids=["renew 返回 False", "renew 抛异常"],
)
async def test_renew_failure_abandons_without_any_terminal_write(
    renew_result: bool, renew_error: Exception | None
) -> None:
    """11 / 12 / **B1**. 续期失败 → **取消处理并放弃**：不跑完、无副作用、三类终态零调用。

    工单 §3.2 第 11 条逐字要求三条零调用（`mark_succeeded` / `mark_failed` / `requeue`），
    **修复轮的 B1 又加了三条**（要「真的放弃执行」而不只是抑制写回）：

    ① `execute` 在**远小于处理器时长**内返回（不是等它跑完、也不是等 `timeout_s`）；
    ② 处理器**没有跑完**（`completed is False`）；
    ③ 外部副作用计数为 **0**（`paid_calls == 0`）。

    ## ②③ 的读法：必须**越过处理器本来的完成时刻**（M1 的修复）

    第一版在这里**紧接着 `execute` 返回就读** ②③ —— 那是**零杀伤**的写法：
    不取消处理器时它只是一个脱离的 task 还在 `sleep`，此刻 `completed` 当然是 `False`、
    `paid_calls` 当然是 `0`，**两种实现下同时为真**。实测（控制者复核）：
    把 `if lease_lost or timed_out:` 变异成只判 `timed_out:`（= 撤销 B1 的修复），
    `-m "not integration"` 全量 **1268 passed / 0 failed**，一条都没红。
    ① 也拦不住：心跳 10ms 就发现租约丢失，`execute` 两种实现下都早返回。

    故现在先 `await` 处理器的 `stopped` 事件（它在 `handle` 的 `finally` 里置位——
    跑完与被取消都会置位），**再**断言 ②③。于是：

    - **修复后**：取消在 `_dissolve_task` 里完成，`stopped` 在 `execute` 返回前已置位 → 判据为真；
    - **修复前（B1 被撤掉）**：`stopped` 要等处理器自己睡醒（`delay_s`）才置位 →
      此刻 `completed is True` / `paid_calls == 1` → **判据变红**。

    判别力自证见 `test_m1_abandon_guard_discriminates`（内存变异，锚点 = 那一行 `if`）。

    各数值一起保证"结束来自租约丢失"：租约 `lease_ms=30` → 心跳间隔 10ms；
    处理器 0.3s；`timeout_s=5.0`（远大于用例预算）。整个用例应当是**几十毫秒级**。
    """
    handler = _BadTurnHandler(delay_s=0.3)
    harness = Harness(
        tasks=[_claimed("task-a")],
        handlers={TASK_TYPE: handler},
        handler=handler,
        renew_result=renew_result,
        renew_error=renew_error,
    )
    harness.runner = TaskRunner(
        store=harness.store,
        locks=harness.locks,
        handlers={TASK_TYPE: handler},
        policies=REGISTRY,
        config=harness.short_heartbeat_config(),
    )
    claimed = await harness.runner.claim_once()
    assert claimed is not None
    started = time.monotonic()

    await asyncio.wait_for(
        harness.runner.execute(claimed, claim=harness.locks.claim_of("task-a")), timeout=3.0
    )

    elapsed = time.monotonic() - started
    await _assert_lease_lost_abandons(harness, handler, elapsed=elapsed)


# ---------------------------------------------------------------------------
# 13. 任务级超时
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("max_retries", "expect_mark_failed"),
    [(0, True), (3, False)],
    ids=["已超限 → mark_failed 落 5002", "未超限 → 重排队（终态还没写）"],
)
async def test_handler_timeout_goes_through_the_failure_path_with_5002(
    max_retries: int, expect_mark_failed: bool
) -> None:
    """13. 处理器挂起超过 `timeout_s` → 走失败分流，业务码 **`5002`**。

    `timeout_s=0.01`（**处理器自己声明的值**，`design.md:185`），处理器永不返回。

    ## 两个分支都要断言（R1 的修复点）

    第一版只跑 `max_retries=0` 那条，却在 `attempt=1 / max_retries=3` 的路径上
    把"业务码"的断言写在 `if codes:` 里——而那条路径**根本不产生** `error_code=` 事件
    （它是重排队、不写终态），于是**那行断言是死代码**：一个把超时算成 `4003`
    甚至任意码的实现照样绿。docstring 却正好在吹这一点（假绿）。

    现在两条分支各自断言它**该**有的东西：

    - 已超限（`max_retries=0`）→ `mark_failed` 且 `error_code=5002`；
    - 未超限（`max_retries=3`）→ `requeue` + 退避 1.0s，**且 `mark_failed` 零调用**
      （终态还没写，故这里**没有**码可断——码的判据归上一条分支）。
    """
    handler = FakeHandler(hang=True, timeout_s=0.01)
    harness = Harness(
        tasks=[_claimed("task-a")],
        handlers={TASK_TYPE: handler},
        handler=handler,
        config=RunnerConfig(
            lease_ms=LEASE_MS, max_retries=max_retries, concurrency_limit=4
        ),
    )

    await harness.claim_and_execute("task-a")

    if expect_mark_failed:
        assert harness.store.count("mark_failed") == 1, "已超限必须写 FAILED 终态"
        assert "error_code=5002" in harness.events, (
            f"超时必须落 5002（不是 4003）：{harness.events}"
        )
        assert harness.store.count("requeue") == 0, "已超限不该再重排队"
    else:
        assert harness.store.count("requeue") == 1, "未超限应当重排队"
        assert harness.store.count("mark_failed") == 0, "未超限不该写 FAILED（终态还没到）"
        assert "locks.defer:task-a:1.0" in harness.events, (
            f"首次失败的退避应为 1.0s：{harness.events}"
        )
        assert not [item for item in harness.events if item.startswith("error_code=")], (
            "本分支不写终态，故不该出现 error_code（出现了说明分流走错了）"
        )


# ---------------------------------------------------------------------------
# 14 / 15 / 16. 失败分流（退避 / 超限 / 不可重试）
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("attempt", "expected_delay"),
    [(1, 1.0), (2, 2.0), (3, 4.0)],
    ids=["第 1 次 → 1.0s", "第 2 次 → 2.0s", "第 3 次 → 4.0s"],
)
async def test_backoff_delays_grow_exponentially(attempt: int, expected_delay: float) -> None:
    """14. 退避 `delay_s` **逐项相等**（不是"大致递增"）：`1.0 / 2.0 / 4.0`。

    依据 `docs/design/高并发架构演进设计.md:260`「指数退避（1s→2s→4s…）」与
    `BACKOFF_BASE_S = 1.0`。逐项断言的理由：`2 ** (attempt - 1)` 写成 `2 ** attempt`
    时序列会变成 2/4/8——「大致递增」的断言抓不到这个错。
    """
    handler = FakeHandler(failure=_failure())
    harness = Harness(tasks=[_claimed("task-a")], handlers={TASK_TYPE: handler}, handler=handler)

    await harness.run_failed_attempt(attempt)

    assert harness.store.count("requeue") == 1, f"第 {attempt} 次失败应当重排队"
    assert harness.store.count("mark_failed") == 0, f"第 {attempt} 次未超限，不该写 FAILED"
    assert f"locks.defer:task-a:{expected_delay}" in harness.events, (
        f"第 {attempt} 次的退避时长不是 {expected_delay}s：{harness.events}"
    )


async def test_over_limit_turns_to_manual_review() -> None:
    """15. 超限转人工：`max_retries=3`，第 **4** 次失败 → `mark_failed` 且 `requeue` 零调用。

    `error_code` 必须是**异常自带的 `code`**（`4003`，本层 MUST NOT 猜），
    `finished_at` 必须非空且 aware。
    """
    handler = FakeHandler(failure=_failure())
    harness = Harness(tasks=[_claimed("task-a")], handlers={TASK_TYPE: handler}, handler=handler)

    await harness.run_failed_attempt(4)

    assert harness.store.count("mark_failed") == 1, "超限必须写 FAILED（转人工，不静默丢单）"
    assert harness.store.count("requeue") == 0, "超限后仍在重排队：任务会被无限重试"
    assert f"error_code={CHANNEL_FAILURE_CODE}" in harness.events, (
        f"error_code 不是异常自带的码：{harness.events}"
    )
    assert "finished_at_aware=True" in harness.events, "finished_at 必须非空且带时区"


async def test_third_failure_still_retries() -> None:
    """15（边界）. `max_retries=3` 时第 **3** 次失败仍要重试（判据含等号）。

    这一条与上一条是一对：`attempt <= max_retries` 写成 `<` 时，第 3 次就会转人工，
    而第 4 条用例（用 `<` 也过）抓不到——两条合起来才把边界钉死。
    """
    handler = FakeHandler(failure=_failure())
    harness = Harness(tasks=[_claimed("task-a")], handlers={TASK_TYPE: handler}, handler=handler)

    await harness.run_failed_attempt(3)

    assert harness.store.count("requeue") == 1
    assert harness.store.count("mark_failed") == 0
    assert "locks.defer:task-a:4.0" in harness.events


async def test_non_retryable_policy_skips_backoff_entirely() -> None:
    """16. `retryable=False` 不进退避：**首次失败即** `mark_failed`。

    `design.md:185` 要求处理器声明「是否可重试」——声明了就必须被用上，
    否则那个字段只是装饰。这里用**最小策略替身**（只实现 `retryable` / `task_type` 两个
    成员，即 `core` 侧 Protocol 的全部要求）显式构造 `retryable=False`。
    """

    class _NotRetryable:
        task_type = TASK_TYPE
        retryable = False

    handler = FakeHandler(failure=_failure())
    harness = Harness(
        tasks=[_claimed("task-a")],
        handlers={TASK_TYPE: handler},
        handler=handler,
        policies={TASK_TYPE: _NotRetryable()},
    )

    await harness.run_failed_attempt(1)

    assert harness.store.count("mark_failed") == 1, "不可重试的类型首次失败就该转人工"
    assert harness.store.count("requeue") == 0
    assert not [item for item in harness.events if item.startswith("locks.defer:")], (
        "不可重试的类型不该进退避"
    )
    assert f"error_code={CHANNEL_FAILURE_CODE}" in harness.events


async def test_unknown_policy_is_treated_as_not_retryable() -> None:
    """补充：策略映射里没有该类型（或映射为空）时按**不可重试**分流（保守方向）。

    缺策略时宁可少重试、把任务交给人，也不要在一个本不该重试的类型上反复重试
    （每次重试都可能重放一次付费通道）。
    """
    handler = FakeHandler(failure=_failure())
    harness = Harness(
        tasks=[_claimed("task-a")],
        handlers={TASK_TYPE: handler},
        handler=handler,
        policies={},
    )

    await harness.run_failed_attempt(1)

    assert harness.store.count("mark_failed") == 1
    assert harness.store.count("requeue") == 0


# ---------------------------------------------------------------------------
# 17. 成功路径
# ---------------------------------------------------------------------------
async def test_mark_succeeded_precedes_lease_release() -> None:
    """17. 成功路径：`mark_succeeded(progress=100)` **先于** `locks.release`（顺序断言）。

    顺序反过来会在「租约已释放」与「终态已落库」之间留一个窗口，
    别的实例可以领到同一个任务并**重复调用付费通道**（`design.md:208`）。
    故这里断言的是**下标大小**，不是"两者都发生了"。
    """
    handler = FakeHandler()
    harness = Harness(tasks=[_claimed("task-a")], handlers={TASK_TYPE: handler}, handler=handler)

    await harness.claim_and_execute("task-a")

    assert harness.store.count("mark_succeeded") == 1
    assert "progress=100" in harness.events, f"成功必须写 progress=100：{harness.events}"
    assert "finished_at_aware=True" in harness.events
    succeeded_at = harness.events.index("store.mark_succeeded:task-a")
    released_at = harness.events.index("locks.release:task-a")
    assert succeeded_at < released_at, (
        f"先释放租约后写终态：{harness.events}（之间存在重复调用付费通道的窗口）"
    )
    assert harness.store.count("mark_failed") == 0
    assert harness.store.count("requeue") == 0


async def test_success_never_persists_a_container_task_state() -> None:
    """补充：成功路径不写失败列（`error_code` 不出现在时间线上）。"""
    handler = FakeHandler()
    harness = Harness(tasks=[_claimed("task-a")], handlers={TASK_TYPE: handler}, handler=handler)

    await harness.claim_and_execute("task-a")

    assert not [item for item in harness.events if item.startswith("error_code=")]


# ---------------------------------------------------------------------------
# 18 / B2. 背压：**同时持有的租约数 ≤ concurrency_limit**
# ---------------------------------------------------------------------------
class _LeaseAccountingLockStore:
    """按 `LockStore` 协议记账的**内存锁替身**：数「同时持有几个租约」与「并发几个 `acquire`」。

    ## 为什么需要它（M5 的教训）

    旧用例用 `_FixedClaimLockStore` + `FakeStore` 的默认窗口，绿色来自
    `limit = concurrency_limit = 1`：候选窗口被切成 1 个元素，而那个元素恰好是**正在跑的**
    `task-a`（`FakeStore.list_claimable` 只排除写过终态/重排队的任务），
    于是 `acquire` 永远拿不到 `task-b` —— **不是因为信号量，是因为窗口**。
    那样的用例对「领了再排队」**没有判别力**。

    ## 本替身怎么不依赖存储层谓词

    `TaskStore.list_claimable` 的谓词是 `status = 'PROCESSING'`，而 `begin_attempt` 不改
    `status`，所以**正在跑的行仍然在扫描窗口里**——这个副作用可能偶然掩盖"领了再排队"。
    本替身的窗口**刻意同时给出 `task-a`（正在跑）与 `task-b`（另有一个空闲候选）**，
    并让两行都始终 `PROCESSING`：于是「许可已满却仍去领取」的实现在这里**没有地方躲**
    （它必然领到 `task-b` 而多持一个租约）。执行器的背压契约因此不依赖存储层谓词。

    ## 可注入故障（判别力自证用）

    `fail_on_second_acquire` 置位时，**第二次 `acquire` 前的清理点**抛异常 ——
    该清理点在修复前的实现里不存在（那时租约不会在取消后释放）。于是：
    修复前 → 走到这个清理点 → **抛断言错误**（证明撤销确实会泄漏租约）；
    修复后 → 取消时已 `release` → 租约数回到 0 → 不抛，循环正常继续。
    """

    def __init__(self, *, fail_on_second_acquire: bool = False) -> None:
        self.fail_on_second_acquire = fail_on_second_acquire
        self.acquire_calls: list[str] = []
        self.releases: list[str] = []
        self.max_leases_held = 0
        self._leases: dict[str, str] = {}
        self._rounds = 0

    async def acquire(self, task_id: str, *, lease_ms: int) -> TaskClaim | None:
        # 每「轮」开始前先对账：跑着的任务**必须**仍持有租约，
        # 否则说明取消路径把租约漏掉了（判别力自证靠这一步）。
        held_now = len(self._leases)
        if (
            self.fail_on_second_acquire
            and held_now
            and "task-a" not in self._leases
            and self._rounds >= 1
        ):
            raise AssertionError("任务 task-a 的租约不见了：取消路径没有释放租约（租约泄漏）")
        self._rounds += 1
        self.acquire_calls.append(task_id)
        if task_id in self._leases:
            return None
        token = f"lease-token:{task_id}:{len(self.acquire_calls)}"
        self._leases[task_id] = token
        self.max_leases_held = max(self.max_leases_held, len(self._leases))
        return TaskClaim(task_id=task_id, token=token, attempt=1)

    async def renew(self, claim: TaskClaim, *, lease_ms: int) -> bool:
        return self._leases.get(claim.task_id) == claim.token

    async def release(self, claim: TaskClaim) -> bool:
        if self._leases.get(claim.task_id) != claim.token:
            return False
        del self._leases[claim.task_id]
        self.releases.append(claim.task_id)
        return True

    async def is_deferred(self, task_id: str) -> bool:
        return False

    async def defer(self, task_id: str, *, delay_s: float) -> None:
        return None

    async def close(self) -> None:
        return None

    @property
    def leases_held(self) -> int:
        return len(self._leases)


class _GateNowHandler:
    """处理器：进入时置 `started`，然后 `await` 一个外部事件（可被取消）。

    用事件而不是 `await asyncio.sleep(...)` 做同步点：sleep 是"等一段时间看结果"，
    事件是"等到这件事确实发生了"——后者不会因为机器慢而假红。
    **本文件一律用事件驱动**（第一版有处用例靠"让出 400 轮事件循环"，在全量套件下偶发不稳）。
    """

    def __init__(self, gate: asyncio.Event) -> None:
        self._gate = gate
        self.started = asyncio.Event()
        #: **第二个任务开工**时置位（阳性对照用：证明"放行后确实领到了下一个"）。
        self.second_started = asyncio.Event()
        self.entered: list[str] = []
        self.in_flight = 0
        self.max_in_flight = 0

    def timeout_s(self) -> float:
        return 30.0

    async def handle(self, task: ClaimedTask) -> None:
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        self.entered.append(task.task_id)
        self.started.set()
        if len(self.entered) >= 2:
            self.second_started.set()
        await self._gate.wait()
        self.in_flight -= 1


async def test_leases_held_never_exceed_the_concurrency_limit() -> None:
    """18 / **B2**. `concurrency_limit=1` 时**同时持有的租约数 MUST ≤ 1**（背压）。

    场景的两个要点（缺一个判据就没有判别力）：

    1. **替身的窗口排除"本轮已 `begin_attempt` 的行"**（`exclude_begun=True`）——
       那是对 `TaskStore` 的一个**合法实现**（"我自己正在处理的行，对我自己而言
       不是可领取的"）。不这么做的话，许可满时窗口里只剩"自己领不到的那一行"，
        "先拿许可"与"先领取"两种实现就都只持 1 个租约（见该参数的注释，以及被否证的旧结论）；
    2. **窗口里始终有别的可领取任务**（`task-b`），于是"领了再排队"一定会多持一个。

    三条断言一起构成判据：

    - `locks.max_leases_held <= 1`：**判据本体**（第二个任务在第一个跑完前没被领取）；
    - `handler.entered == ["task-a"]`：没有第二个处理器开工；
    - `"task-b" not in locks.acquire_calls`：许可满时**连试都没试**（更严一档）。

    **为什么"多持一个租约"是真问题**：被领取但还在排队的任务**持有租约却没有心跳**
    （心跳在 `execute` 里才起，而 `execute` 要等许可）。等待超过 `lease_ms` 时租约静默过期
    → 别的实例回收 → 同一个任务被两个实例执行（`design.md:208` 要防的重复付费调用）。
    """
    gate = asyncio.Event()
    handler = _GateNowHandler(gate)
    locks = _LeaseAccountingLockStore()
    store = FakeStore([_claimed("task-a"), _claimed("task-b")], events=[], exclude_begun=True)
    runner = TaskRunner(
        store=store,
        locks=locks,
        handlers={TASK_TYPE: handler},
        policies=REGISTRY,
        config=RunnerConfig(
            lease_ms=LEASE_MS, max_retries=3, concurrency_limit=1, poll_interval_s=0.0
        ),
    )
    stop = asyncio.Event()
    loop_task = asyncio.create_task(runner.run_forever(stop=stop))

    # **事件驱动**等到第一个处理器确实进入了（此刻许可被它持有）。
    await asyncio.wait_for(handler.started.wait(), timeout=5)

    assert locks.max_leases_held <= 1, (
        f"同时持有 {locks.max_leases_held} 个租约（上限 1）：第二个任务在第一个跑完前"
        f"**已经被领取**了（领了再排队）——它持有租约却没有心跳，"
        f"等待超过 lease_ms 就会静默过期并被别的实例回收"
    )
    assert "task-b" not in locks.acquire_calls, (
        f"许可已满时仍然去领取了候选任务：{locks.acquire_calls}"
        f"（信号量满时 MUST NOT 领取新任务）"
    )
    assert handler.entered == ["task-a"], (
        f"第一个任务还在跑，却有别的处理器开工了：{handler.entered}"
    )

    # ---- 阳性对照（**事件驱动**）：放行后第二个任务确实被领取并开工 ----
    gate.set()
    await asyncio.wait_for(handler.second_started.wait(), timeout=5)
    stop.set()
    await asyncio.wait_for(loop_task, timeout=5)

    assert handler.entered == ["task-a", "task-b"], (
        f"放行后第二个任务没有被领取并执行：{handler.entered}"
        f"（阳性对照失败 ⇒ 上面那条「没领第二个」可能是「循环根本没在工作」的平凡真）"
    )
    assert locks.max_leases_held == 1, (
        f"全程同时持有的租约数为 {locks.max_leases_held}（上限 1）：背压没有封顶"
    )
    assert handler.max_in_flight == 1, (
        f"同时有 {handler.max_in_flight} 个处理器在跑：信号量没有封顶"
    )


class _CountingStop:
    """`stop` 的结构替身：既是"该停了吗"，也**数执行器问了几次**（= 循环跑了几轮）。

    ## 为什么需要它（N3）

    `test_b2_guard_discriminates` 要在"循环已经跑过足够轮次"这个前提下量峰值租约数，
    而"足够"此前是靠 `for _ in range(50): await asyncio.sleep(0)` **凑**出来的
    ——同文件自己就记过"实测固定 50 轮偶发不够"（那会让自证假红）。

    轮数**不是时间**，而是**循环自己的动作**，因此它可以被观测而不是被猜测：
    两条实现（生产的与 `_PreFixB2Runner`）的每一轮都以 `while not stop.is_set()` 开头、
    以 `if stop.is_set(): break` 收尾 —— 故"问过几次 `stop`"与"跑了几轮"成正比
    （实测两种形态都是每轮 **2 次** `is_set()`）。判据因此是**条件等待 + 有界 deadline**，
    与机器快慢无关；就算将来某条实现多问一次，最坏也只是等到 deadline（不会假绿，
    因为峰值是在循环**结束之后**才读的）。

    接口只有 `is_set()` / `wait()` / `set()`——正是 `run_forever` 用到的那三个。
    """

    def __init__(self) -> None:
        self._event = asyncio.Event()
        self.is_set_calls = 0

    def is_set(self) -> bool:
        self.is_set_calls += 1
        return self._event.is_set()

    def set(self) -> None:
        self._event.set()

    async def wait(self) -> bool:
        return await self._event.wait()


#: 量峰值前要求循环至少跑过的轮数（每轮 2 次 `is_set()`，见 `_CountingStop`）。
_B2_REQUIRED_LOOP_ITERATIONS = 3


class _PreFixB2Runner(TaskRunner):
    """**B2 的变异体**：修复前的 `run_forever`（**先领取、再把协程挂到信号量上排队**）。

    v2 的形态（就是工单 §2.5 硬约束 7 明令禁止的那一种）：

    ```python
    claimed = await self.claim_once()            # ← 先领，不看许可
    self._track(asyncio.create_task(            # ← 再让协程自己去排队拿许可
        self._execute_after_permit(semaphore, claimed)))
    ```

    与修复后的差别有**两处**，都与 B2 直接相关：

    1. **领取发生在许可之前**；
    2. **循环里没有"许可已满就不领"的门**（那道门是随 B2 修复一起加的）。

    它必须**两处都还原**才与修复前等价——只还原第 1 处的话，门仍会挡住第二次领取
    （我第一版自证就栽在这里：`max_leases_held` 停在 1，看着像"判别力不存在"，
    实际是变异体没还原干净）。这也是控制者探针 `(b) pre-fix shape` 的形态。
    """

    async def run_forever(self, *, stop: asyncio.Event) -> None:
        semaphore = asyncio.Semaphore(self._config.concurrency_limit)
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=self._config.poll_interval_s)
                break
            except TimeoutError:
                pass
            if stop.is_set():
                break
            # ---- 修复前：先领取（此刻不看许可是否空闲），再把协程挂上去排队 ----
            claimed = await self.claim_once()
            if claimed is None:
                continue
            self._track(asyncio.create_task(self._execute_after_permit(semaphore, claimed)))
        await self._drain_inflight()

    async def _execute_after_permit(
        self, semaphore: asyncio.Semaphore, claimed: ClaimedTask
    ) -> None:
        """修复前的执行协程：**先排队等许可，再执行**（租约在排队期间空转、没有心跳）。"""
        async with semaphore:
            await self.execute(claimed)


async def test_b2_guard_discriminates() -> None:
    """**B2 的判别力自证**：把 `run_forever` 还原成"领了再排队"，上一条的判据**必须变红**。

    同一个场景（`exclude_begun=True` 的窗口 + 事件闸住的处理器 + `concurrency_limit=1`），
    只换 `run_forever` 的形态，实测两种实现的**峰值租约数**：

    - 修复后：**1**；
    - 修复前形态：**≥ 2**（第二个任务在第一个还在跑时就被领取了）。

    ## 这条自证是控制者的探针逼出来的（我此前的结论是错的）

    我上轮写过"「同时持有的租约数」在原契约下对两种实现给同一个答案"，并据此把运行期判据
    降级成 AST 顺序判据。**那句话被否证了**：它只在我当时那一个替身（`exclude_begun=False`，
    已开工的行留在窗口里）上成立，而那是**替身的性质、不是契约的性质**。
    换成合法的 `exclude_begun=True` 之后，判据立刻有判别力（就是本用例）。
    教训与 `FakeStore.exclude_begun` 的注释里那条是同一个：
    **不要把某个测试替身的行为写成对接口的断言。**
    """
    window = [_claimed("task-a"), _claimed("task-b"), _claimed("task-c")]

    async def _peak_leases(runner_cls: type[TaskRunner]) -> tuple[int, list[str]]:
        """跑同一场景，返回 `(峰值租约数, acquire 调用序列)`。"""
        gate = asyncio.Event()
        handler = _GateNowHandler(gate)
        locks = _LeaseAccountingLockStore()
        store = FakeStore(window, events=[], exclude_begun=True)
        runner = runner_cls(
            store=store,
            locks=locks,
            handlers={TASK_TYPE: handler},
            policies=REGISTRY,
            config=RunnerConfig(
                lease_ms=LEASE_MS, max_retries=3, concurrency_limit=1, poll_interval_s=0.0
            ),
        )
        stop = _CountingStop()
        loop_task = asyncio.create_task(runner.run_forever(stop=stop))  # type: ignore[arg-type]
        # **事件驱动**等到第一个处理器进入（它一定已经领过租约了）。
        await asyncio.wait_for(handler.started.wait(), timeout=5)
        # 再等到「第一行确实已 `begin_attempt`」落地——**那之后**窗口里才会出现第二个候选
        # （`exclude_begun=True` 把已开工的行排除掉）。
        #
        # 这一步**不能**用固定轮数：`begin_attempt` 经 `run_in_threadpool` 落到线程池，
        # 全量套件下调度更慢——实测固定 50 轮偶发不够，于是 `begin_attempt` 还没记账、
        # 第二个候选还没出现，变异体的峰值停在 1，自证**假红**。
        deadline = time.monotonic() + 5.0
        while store.count("begin_attempt") < 1 and time.monotonic() < deadline:
            await asyncio.sleep(0)  # ai-allow-sleep: 0 秒，等 begin_attempt 落到替身账上
        assert store.count("begin_attempt") >= 1, (
            "第一行始终没有 begin_attempt：本场景的前提不成立（第二个候选不会出现）"
        )
        # 再等循环**自己跑够轮数**（N3：这是条件等待，不是"让出 50 次去凑"）。
        # 修复前的形态需要**第 2 轮**才会领走第二个任务，故要求至少 3 轮留出余量；
        # 轮数由 `_CountingStop` 数"问了 `stop` 几次"得出，与机器快慢无关。
        required_checks = 2 * _B2_REQUIRED_LOOP_ITERATIONS
        deadline = time.monotonic() + 5.0
        while stop.is_set_calls < required_checks and time.monotonic() < deadline:
            await asyncio.sleep(0)  # ai-allow-sleep: 0 秒，让出控制权给执行器协程（条件等待）
        assert stop.is_set_calls >= required_checks, (
            f"循环只跑了约 {stop.is_set_calls // 2} 轮（要求 ≥{_B2_REQUIRED_LOOP_ITERATIONS} 轮）："
            f"本判据的前提不成立，峰值租约数不能作为证据"
        )
        gate.set()
        stop.set()
        await asyncio.wait_for(loop_task, timeout=5)
        # **循环完全停下来之后**才读峰值：这样它覆盖整段场景（含收尾），
        # 而不是"循环跑到一半时的快照"。
        peak = locks.max_leases_held
        calls = list(locks.acquire_calls)
        return peak, calls

    fixed_peak, fixed_calls = await _peak_leases(TaskRunner)
    mutant_peak, mutant_calls = await _peak_leases(_PreFixB2Runner)

    assert fixed_peak == 1, (
        f"修复后的实现峰值持有 {fixed_peak} 个租约（期望 1，acquire 序列 {fixed_calls}）："
        f"上一条用例的判据本身失守"
    )
    assert mutant_peak >= 2, (
        f"修复前形态的峰值只有 {mutant_peak} 个租约（期望 ≥2，acquire 序列 {mutant_calls}）："
        f"本判据对「领了再排队」没有判别力（上一条用例因此可能只是碰巧为绿）"
    )


def test_run_forever_acquires_the_permit_before_claiming() -> None:
    """**B2 的顺序判据**（源码级，AST）：`run_forever` 里许可的获取必须**在**领取之前。

    ## **行为判据为主、AST 判据为辅**（F11 要求的措辞就写在这里）

    行为判据（**主要**）：

    - `test_leases_held_never_exceed_the_concurrency_limit`（峰值租约数 ≤ `concurrency_limit`）；
    - `test_b2_guard_discriminates`（把 `run_forever` 还原成"领了再排队"，上一条**变红**）。

    本用例（**辅助**、便宜、直白地指出缺的是哪一条语句顺序）。为什么 MUST NOT 只留它：

    - **它可以被仍然错的代码满足**：源码里 `semaphore.acquire()` 在 `claim_once()` 之前，
      但许可容量与门判据（`len(self._inflight) >= concurrency_limit`）写成不一致时，
      运行期照样会领了再排队——那种改动只有行为判据抓得到；
    - **它对等价的正确写法可能误报**：把许可获取抽成一个辅助方法
      （`await self._take_permit(semaphore)`）之后，本判据找不到 `.acquire` 会**直接报错**，
      尽管行为完全正确。

    两条判据的守备范围不同，不是重复；但**判红时的第一顺位是行为判据**。

    判据：`semaphore.acquire()` 那行的**行号 <** `self.claim_once()` 那行的行号。
    任一方找不到 → **直接报错**（判据 MUST NOT 退化成空操作）。
    """
    run_forever = next(
        node
        for node in ast.walk(_runner_tree())
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "run_forever"
    )
    acquire_lines = [
        node.lineno
        for node in ast.walk(run_forever)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "acquire"
    ]
    claim_lines = [
        node.lineno
        for node in ast.walk(run_forever)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "claim_once"
    ]
    assert acquire_lines, "`run_forever` 里找不到许可获取：判据失去对象"
    assert claim_lines, "`run_forever` 里找不到 `self.claim_once()`：判据失去对象"
    assert min(acquire_lines) < min(claim_lines), (
        f"顺序反了：先领取（第 {min(claim_lines)} 行）后拿许可（第 {min(acquire_lines)} 行）"
        f"——工单 §2.5 硬约束 7 明令禁止「领了再排队」"
        f"（被领取的租约在排队期间没有心跳，等待超过 lease_ms 就会静默过期）"
    )


class _GatedHandler:
    """被一个事件闸住的处理器：`started` 在首次进入时 set，`both_done` 在两个任务都跑完后 set。

    用事件而不是 `await asyncio.sleep(...)` 做同步点：sleep 是"等一段时间看结果"，
    事件是"等到这件事确实发生了"——后者不会因为机器慢而假红。
    """

    def __init__(self, gate: asyncio.Event) -> None:
        self.events: list[str] = []
        self._gate = gate
        self.started = asyncio.Event()
        self.both_done = asyncio.Event()
        self.in_flight = 0
        self.max_in_flight = 0
        self.done: list[str] = []
        #: 开工顺序（与 `done` 分开记：断言「谁开工了」比断言「谁完成了」更接近并发判据）。
        self.entered: list[str] = []

    def timeout_s(self) -> float:
        return 10.0

    async def handle(self, task: ClaimedTask) -> None:
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        self.entered.append(task.task_id)
        self.started.set()
        await self._gate.wait()
        self.in_flight -= 1
        self.done.append(task.task_id)
        self.events.append(f"handler.done:{task.task_id}")
        if len(self.done) >= 2:
            self.both_done.set()


# ---------------------------------------------------------------------------
# 19. stop 可打断
# ---------------------------------------------------------------------------
async def test_run_forever_stops_promptly_when_the_event_is_already_set() -> None:
    """19. `run_forever` 在 `stop.set()` 后**立即**返回（不等一个轮询间隔）。

    判据是**墙钟耗时**而不是「有没有 sleep 调用」：`poll_interval_s` 取 30s，
    一个用 `asyncio.sleep(poll_interval_s)` 硬等的实现会在这里挂 30 秒而被
    `wait_for(timeout=2)` 掐掉（用例失败），而正确实现（`wait_for(stop.wait(), …)`）
    在 `stop` 已 set 时立刻返回。本用例**没有真等**：它等的是一次"立即返回"。
    """
    harness = Harness(tasks=[])
    stop = asyncio.Event()
    stop.set()
    runner = TaskRunner(
        store=harness.store,
        locks=harness.locks,
        handlers={},
        policies=REGISTRY,
        config=RunnerConfig(
            lease_ms=LEASE_MS, max_retries=3, concurrency_limit=4, poll_interval_s=30.0
        ),
    )
    started = time.monotonic()

    await asyncio.wait_for(runner.run_forever(stop=stop), timeout=2.0)

    elapsed = time.monotonic() - started
    assert elapsed < 0.5, (
        f"stop 已 set 却花了 {elapsed:.3f}s 才返回：等待没有走 stop.wait()（硬等了一个轮询间隔）"
    )
    assert harness.store.count("list_claimable") == 0, "stop 已 set 时不该再扫库"


# ---------------------------------------------------------------------------
# 20. run_once 无任务
# ---------------------------------------------------------------------------
async def test_run_once_returns_false_without_touching_redis() -> None:
    """20. `run_once` 无任务时返回 `False`，且**不调用 `acquire`**（减少 Redis 往返）。"""
    harness = Harness(tasks=[])

    result = await harness.runner.run_once()

    assert result is False
    assert harness.locks.acquire_calls == [], "没有可领取任务时仍打了一次 Redis：空轮询白烧一跳"
    assert harness.store.count("list_claimable") == 1


# ---------------------------------------------------------------------------
# 21. 处理器缺失
# ---------------------------------------------------------------------------
async def test_missing_handler_is_not_silently_skipped(caplog: pytest.LogCaptureFixture) -> None:
    """21. `handlers={}` 时领到任务 → 记 ERROR + 按失败分流（`error_code == 5000`）。

    三段断言，缺一不可（工单 §3.2 第 21 条逐字）：

    1. **记了 ERROR**（`design.md:194`「避免告警丢失」）；
    2. **确实写了终态**（不是只打日志）——这里 `max_retries=0`，故写的是 `FAILED`；
    3. **没有异常逃逸**（执行器不因一个无法处理的任务崩掉整个循环）。
    """
    harness = Harness(
        tasks=[_claimed("task-a")],
        handlers={},  # M1 的现状（工单 §2.8）
        config=RunnerConfig(lease_ms=LEASE_MS, max_retries=0, concurrency_limit=4),
    )

    with caplog.at_level(logging.ERROR, logger="aicore.core.task_runner"):
        # 不 try/except：MUST NOT 有异常逃逸——逃逸了本行就会红。
        await harness.claim_and_execute("task-a")

    assert "没有可用处理器" in caplog.text, f"没有记 ERROR 日志：{caplog.text!r}"
    assert harness.store.count("mark_failed") == 1, "只打了日志却没有写终态（任务会永远停在原状态）"
    assert f"error_code={INTERNAL_ERROR_CODE}" in harness.events, (
        f"装配缺失必须落 5000（不是 4003/5002）：{harness.events}"
    )
    assert harness.store.count("mark_succeeded") == 0


async def test_missing_handler_does_not_break_the_running_loop() -> None:
    """21（续）. 一个无法处理的任务**不会**让 `run_forever` 崩掉。

    判据是「终态写回完成之后 `run_forever` 仍在跑」（`not done()`），而不是"跑了很多轮"：
    后者会引入时序假设。等到 `mark_failed` 出现（那是 `execute` 的**最后**一步写回），
    再断言循环还活着，等价于「这个坏任务没有把循环带走」。

    `poll_interval_s=0.0`（N4）：默认生产值是 1.0s，而本用例每轮都要等一个间隔才能重查 `stop`
    ——不传它就会白等 1.02s（实测），而这段时间既不是判据也不是被测行为。
    """
    handler = FakeHandler()
    harness = Harness(
        tasks=[_claimed("task-a")],
        handlers={},
        config=RunnerConfig(
            lease_ms=LEASE_MS, max_retries=0, concurrency_limit=4, poll_interval_s=0.0
        ),
    )
    stop = asyncio.Event()
    loop_task = asyncio.create_task(harness.runner.run_forever(stop=stop))

    deadline = time.monotonic() + 5.0
    while harness.store.count("mark_failed") < 1 and time.monotonic() < deadline:
        await asyncio.sleep(0.01)  # ai-allow-sleep: 让出控制权给执行器协程（循环等待）

    assert harness.store.count("mark_failed") == 1, "坏任务没有写终态（或超时前没写完）"
    assert not loop_task.done(), "run_forever 因一个无法处理的任务被中断了"
    assert not loop_task.cancelled(), "run_forever 被取消了：坏任务不该带走整个循环"

    stop.set()
    await asyncio.wait_for(loop_task, timeout=5)
    assert handler.handled == [], "没有处理器却调用了 handler"
    assert harness.runner.registered_handlers == ()


# ---------------------------------------------------------------------------
# F1/F2/F3：心跳生命周期 MUST **结构上**不可泄漏
#
# 同一个根因（`create_task(_heartbeat())` 与 `try` 之间有可抛语句），三条入口：
#   F1（blocker）处理器抛**非 `AiCoreError`**（编程错误——`TaskHandler.handle` 的
#                docstring 明说这是预期形态）
#   F2（major）  取消落在 **`execute` 自己**身上（关停 drain 阶段被取消）
#   F3            `handle` 是同步 `def` / 没有该属性
#
# 控制者的隔离探针（`lease_ms=150` → 心跳 50ms）在**修复前**的三条入口上都是
# `renew +7`、活动心跳 task=1；对照组（处理器抛 `AiCoreError`）是 `renew +0`。
# ---------------------------------------------------------------------------

#: 观察"心跳还会不会继续续期"的窗口：≥3 个心跳间隔（`SHORT_LEASE_MS=30` → 10ms）。
_HEARTBEAT_OBSERVE_S = 0.05


class _ValueErrorHandler:
    """**F1**：把活干起来之后抛 `ValueError`（**非 `AiCoreError`** 的编程错误）。

    这条路径正是 `TaskHandler.handle` 的 docstring 逐字承诺的形态：
    "抛别的异常……终态不写（**留待租约过期后由别的实例重做**）"。
    修复前那个承诺**不成立**——心跳会带着租约一直续期，任务再也回不来。
    """

    def __init__(self, *, gate: asyncio.Event | None = None) -> None:
        self._gate = gate
        self.started = asyncio.Event()
        self.entered = False

    def timeout_s(self) -> float:
        return 30.0

    async def handle(self, task: ClaimedTask) -> None:
        self.entered = True
        self.started.set()
        if self._gate is not None:
            await self._gate.wait()
        raise ValueError("payload 拼错了（处理器作者的 bug，不是业务失败）")


class _SyncHandleHandler:
    """**F3**：`handle` 是**同步**函数（`asyncio.create_task` 会抛 `TypeError`）。"""

    def __init__(self) -> None:
        self.entered = False

    def timeout_s(self) -> float:
        return 30.0

    def handle(self, task: ClaimedTask) -> None:  # 故意不是 async def
        self.entered = True


class _HangForeverHandler:
    """一直挂着、**吞掉取消**的处理器（F5 用：取消之后仍不结束）。

    `except CancelledError: continue` 之后继续等一个新的 Event —— 于是
    `_dissolve_task` 的取消请求"看起来发出去了"，但 task 永不结束。
    这正是 F5 要的"不合作的处理器"，也是"取消不掉它"这条诚实边界的载体。

    ## 它 MUST 可被**外部放行**（否则会把事件循环的关停挂死）

    第一版没有 `release()`，结果**用例跑不完**：`asyncio.run()` 收尾时会
    `_cancel_all_tasks` 并 `gather` 它们，而这个 task 会一次又一次吞掉取消
    ⇒ 收尾永久挂住（实测：单条用例 90s 不返回，只能 kill）。
    故加一个**只有用例能置位**的 Event：循环的退出条件是"被放行"，不是"被取消"。
    """

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.cancelled_once = False
        self._release = asyncio.Event()

    def release(self) -> None:
        """让处理器可以结束（**用例收尾必须调用**，见类 docstring）。"""
        self._release.set()

    def timeout_s(self) -> float:
        return 30.0

    async def handle(self, task: ClaimedTask) -> None:
        self.started.set()
        while True:
            try:
                await self._release.wait()
                return
            except asyncio.CancelledError:
                self.cancelled_once = True
                # **吞掉取消**：继续等放行（新的 `wait()` 会新建一个 future）。
                continue


async def test_dissolve_task_gives_up_after_a_bounded_wait(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """**F5**：处理器**吞掉取消**时，`_dissolve_task` 必须在**有界**时间内放手。

    复核者的实测（修复前）：租约 0.033s 就丢失，而 `execute` 到 **1.561s** 才返回，
    **放弃之后仍发生 1 次付费调用**——即"主动放弃"被写成了"等它做完"。

    ## 场景（必须让 `execute` 走到"放弃"那一步）

    `renew_result=False` ⇒ 心跳首次续期即被拒 ⇒ 租约丢失 ⇒ 走 `_dissolve_task` 取消处理器。
    处理器吞掉取消**永不结束**，故「它什么时候返回」只由那个上界决定——
    这正是本判据的自变量（若处理器会自己结束，有界/无界就看不出差别）。

    ## 判据（三条，都是行为）

    ① `execute` 的返回时间 ≤ 上界的常数倍（**不是** 30s 的 `timeout_s`）；
    ② 超界时记一条 ERROR（放手**不静默**）；
    ③ 处理器确实被取消过——否则本用例会退化成"什么都没发生"的平凡真。

    上界用 `monkeypatch` 调小到 0.2s，故本用例的墙钟成本是几百毫秒而不是 1 秒。

    ## 判别力自证

    见 `test_f5_bound_guard_discriminates`：把 `_dissolve_task` 里的 `wait_for` 摘掉
    （**内存变异**），同一个判据**必须变红**（它会一直等那个永不结束的处理器）。
    """
    bound_s = 0.2
    monkeypatch.setattr("aicore.core.task_runner.CANCEL_WAIT_TIMEOUT_S", bound_s, raising=True)

    handler = _HangForeverHandler()
    harness = Harness(
        tasks=[_claimed("task-a")],
        handlers={TASK_TYPE: handler},
        handler=handler,
        renew_result=False,  # 续期首次即被拒 = 租约丢失 ⇒ 必然走 _dissolve_task
        config=RunnerConfig(
            lease_ms=SHORT_LEASE_MS, max_retries=3, concurrency_limit=4, poll_interval_s=0.0
        ),
    )
    claimed = await harness.runner.claim_once()
    assert claimed is not None

    started = time.monotonic()
    with caplog.at_level(logging.ERROR, logger="aicore.core.task_runner"):
        # 外层 `wait_for` 是**判据的一部分**：变异体在这里会撞上它并变成 TimeoutError，
        # 而不是把整个套件挂死（"挂死"比"变红"贵一个数量级）。
        await asyncio.wait_for(
            harness.runner.execute(claimed, claim=harness.locks.claim_of("task-a")),
            timeout=bound_s * 5,
        )
    elapsed = time.monotonic() - started

    assert handler.cancelled_once, "处理器没有被取消过：本用例的前提不成立"
    assert elapsed < bound_s * 3, (
        f"execute 花了 {elapsed:.3f}s 才返回（上界 {bound_s}s）："
        f"`_dissolve_task` 在无上限地等一个吞掉取消的处理器——F5 的失效形态"
    )
    assert "没有响应取消" in caplog.text, (
        f"超界放手没有记 ERROR：{caplog.text!r}——静默放手会让运维无从发现"
    )
    # 收尾：那个处理器因"吞掉取消"仍在后台（诚实边界：取消不掉它），
    # **放行**它（而不是再取消一次——再取消也会被吞掉，且会让事件循环关停挂住）。
    handler.release()
    await asyncio.sleep(0)  # ai-allow-sleep: 0 秒，让被放行的处理器与 execute 收尾


async def test_f5_bound_guard_discriminates(monkeypatch: pytest.MonkeyPatch) -> None:
    """**F5 的判别力自证**：摘掉 `_dissolve_task` 的 `wait_for`，上一条判据**必须变红**。

    内存变异（**文件从不被写**）：把

    ```python
    await asyncio.wait_for(asyncio.shield(task), timeout=timeout_s)
    ```

    换成裸 `await asyncio.shield(task)`——即修复前那个"无上限地 await"。
    处理器吞掉取消且永不结束，故**唯一**能让 `execute` 返回的就是那个上界；
    没有它，本用例会撞上自己的外层 `wait_for` 并抛 `TimeoutError`（红）。
    """
    mutant_cls = _mutant_runner_class(
        (
            "        await asyncio.wait_for(asyncio.shield(task), timeout=resolved_timeout_s)\n",
            "        await asyncio.shield(task)\n",
        ),
    )
    bound_s = 0.2
    monkeypatch.setattr("aicore.core.task_runner.CANCEL_WAIT_TIMEOUT_S", bound_s, raising=True)

    handler = _HangForeverHandler()
    harness = Harness(
        tasks=[_claimed("task-a")],
        handlers={TASK_TYPE: handler},
        handler=handler,
        renew_result=False,
        config=RunnerConfig(
            lease_ms=SHORT_LEASE_MS, max_retries=3, concurrency_limit=4, poll_interval_s=0.0
        ),
    )
    runner = mutant_cls(
        store=harness.store,
        locks=harness.locks,
        handlers={TASK_TYPE: handler},
        policies=REGISTRY,
        config=harness.runner.config,
    )
    claimed = await runner.claim_once()
    assert claimed is not None

    executing = asyncio.create_task(
        runner.execute(claimed, claim=harness.locks.claim_of("task-a"))
    )
    # **判据本体（生产侧那一条）在这里必然撞墙**：`execute` 不会在上界内返回。
    # 用 `pytest.raises(TimeoutError)` 把它表达成"红"，而不是让套件挂死。
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(asyncio.shield(executing), timeout=bound_s * 5)

    # 收尾：放行处理器 ⇒ 变异体那个无上限的 `await` 才可能走完。
    # 这一步同时是"变异体确实卡在等待上"的正面证据（放行之前它一直没返回）。
    assert not executing.done(), (
        "变异体的 execute 已经返回了：它并未无上限地等——本自证不成立"
    )
    handler.release()
    await asyncio.wait_for(executing, timeout=5.0)


async def _assert_no_heartbeat_leak(harness: Harness, task_id: str) -> None:
    """F1/F2/F3 共用的「心跳没有泄漏」判据（②③）与后果判据（④）。

    ①② 由调用方断言（各自的出口行为）；本函数负责：

    - **②（判别力所在）** `renew` 次数**不再增长**——泄漏的心跳唯一可见的后果就是
      "它还在续期"，而续期成功意味着**租约永不过期、任务被永久占住**；
    - **③** `asyncio.all_tasks()` 里没有 `_heartbeat`；
    - **④（最贴近后果）** 推进时钟越过租约之后，**另一个实例能领到它**。

    **判据顺序是有意的**：② 是判别力所在（修复前它必红），④ 是后果陈述——
    ④ 单独不具判别力，因为一个仍在续期的心跳在"推进时钟后立刻领取"这个窗口里
    也可能来不及续期（时间竞态）。故 ② 在前，④ 只在 ② 通过之后才有意义。
    """
    renews_before = len(harness.locks.renew_calls)
    # ≥3 个心跳间隔：泄漏的心跳会在这段时间里继续跑（它的间隔只有 10ms）。
    await asyncio.sleep(_HEARTBEAT_OBSERVE_S)  # ai-allow-sleep: 50ms=5 个间隔，看是否仍在续期

    assert len(harness.locks.renew_calls) == renews_before, (
        f"心跳仍在续期（{renews_before} → {len(harness.locks.renew_calls)} 次）："
        f"租约被永久续期 ⇒ `SET NX` 永不成功 ⇒ **没有实例能再领到这个任务**"
    )
    leaked = [
        task.get_coro().__qualname__
        for task in asyncio.all_tasks()
        if task is not asyncio.current_task() and not task.done()
    ]
    assert not any("_heartbeat" in name for name in leaked), (
        f"心跳 task 泄漏：{leaked}——它会一直续期，租约永不过期、"
        f"任务再也无法被任何实例回收"
    )
    claim = await harness.locks.acquire_from_another_instance(task_id, lease_ms=LEASE_MS)
    assert claim is not None, (
        "另一个实例领不到这个任务：租约被孤儿心跳永久续期，"
        "任务永远停在 PROCESSING（这是泄漏最贴近后果的判据）"
    )


async def test_programming_error_in_handler_does_not_leak_the_heartbeat() -> None:
    """**F1（blocker）**：处理器抛 `ValueError` 时，心跳 MUST 被收掉。

    ① 出口行为：`ValueError` **原样上抛**（编程错误不吞、不改写成业务失败）；
    ②③④ 见 `_assert_no_heartbeat_leak`。
    """
    handler = _ValueErrorHandler()
    harness = Harness(
        tasks=[_claimed("task-a")],
        handlers={TASK_TYPE: handler},
        handler=handler,
        config=RunnerConfig(
            lease_ms=SHORT_LEASE_MS, max_retries=3, concurrency_limit=4, poll_interval_s=0.0
        ),
    )
    claimed = await harness.runner.claim_once()
    assert claimed is not None

    with pytest.raises(ValueError, match="payload 拼错了"):
        await harness.runner.execute(claimed, claim=harness.locks.claim_of("task-a"))

    assert handler.entered, "处理器没有被启动：本用例的前提不成立"
    await _assert_no_heartbeat_leak(harness, "task-a")
    # 编程错误不写终态（留待租约回收）——与 ②③④ 一起构成"放弃但不静默"的完整口径。
    assert harness.store.count("mark_succeeded") == 0
    assert harness.store.count("mark_failed") == 0


async def test_external_cancel_of_execute_does_not_leak_the_heartbeat() -> None:
    """**F2（major）**：取消落在 **`execute` 自己**身上时，心跳与处理器 task 都要被收掉。

    ① 出口行为：`CancelledError` **原样传播**（绝不吞掉、也不退化成 lease_lost）；
    ②③④ 见 `_assert_no_heartbeat_leak`。

    v1（修复前）在这一路上会把处理器**孤儿化**：`CancelledError` 传播是对的，
    但 `_dissolve_task(handler_task)` 与 `_cancel_heartbeat(heartbeat)` 都不执行
    ⇒ 心跳继续续期 + 处理器仍在 sleep（之后照常发出付费调用）。
    """
    gate = asyncio.Event()
    handler = _ValueErrorHandler(gate=gate)  # 用 gate 把它挂在"已经开始干活"的状态
    harness = Harness(
        tasks=[_claimed("task-a")],
        handlers={TASK_TYPE: handler},
        handler=handler,
        config=RunnerConfig(
            lease_ms=SHORT_LEASE_MS, max_retries=3, concurrency_limit=4, poll_interval_s=0.0
        ),
    )
    claimed = await harness.runner.claim_once()
    assert claimed is not None
    executing = asyncio.create_task(
        harness.runner.execute(claimed, claim=harness.locks.claim_of("task-a"))
    )
    await asyncio.wait_for(handler.started.wait(), timeout=5)  # 事件驱动：等它真的开工

    executing.cancel()
    with pytest.raises(asyncio.CancelledError):
        await executing

    assert not handler.entered or gate is not None  # 处理器确实开工过
    await _assert_no_heartbeat_leak(harness, "task-a")


async def test_sync_handle_does_not_leak_the_heartbeat() -> None:
    """**F3**：`handle` 是同步函数（`create_task` 抛 `TypeError`）时，心跳 MUST 被收掉。

    ① 出口行为：`TypeError` 上抛（装配形态错误照旧炸出来，不吞）；
    ②③④ 见 `_assert_no_heartbeat_leak`。
    """
    handler = _SyncHandleHandler()
    harness = Harness(
        tasks=[_claimed("task-a")],
        handlers={TASK_TYPE: handler},
        handler=handler,
        config=RunnerConfig(
            lease_ms=SHORT_LEASE_MS, max_retries=3, concurrency_limit=4, poll_interval_s=0.0
        ),
    )
    claimed = await harness.runner.claim_once()
    assert claimed is not None

    with pytest.raises(TypeError, match="a coroutine was expected"):
        await harness.runner.execute(claimed, claim=harness.locks.claim_of("task-a"))

    await _assert_no_heartbeat_leak(harness, "task-a")


async def test_missing_handle_attribute_does_not_leak_the_heartbeat() -> None:
    """**F3（第二形态）**：处理器没有 `handle` 属性时（`AttributeError`）同样不泄漏。

    与上一条同一处修复、不同入口：`create_task(handler.handle(...))` 在取属性时就抛。
    单独立一条是因为修复前的泄漏点**不在** `create_task` 本身，而在"它落在 `try` 之外"——
    两条入口一起才能证明"try 紧贴 create_task"这条结构要求。
    """

    class _NoHandle:
        def timeout_s(self) -> float:
            return 30.0

    harness = Harness(
        tasks=[_claimed("task-a")],
        handlers={TASK_TYPE: _NoHandle()},
        config=RunnerConfig(
            lease_ms=SHORT_LEASE_MS, max_retries=3, concurrency_limit=4, poll_interval_s=0.0
        ),
    )
    claimed = await harness.runner.claim_once()
    assert claimed is not None

    with pytest.raises(AttributeError, match="handle"):
        await harness.runner.execute(claimed, claim=harness.locks.claim_of("task-a"))

    await _assert_no_heartbeat_leak(harness, "task-a")


@pytest.mark.parametrize(
    "bad_value",
    [float("nan"), float("inf"), 0.0, -1.5, "abc"],
    ids=["nan", "inf", "0.0", "-1.5", "非数值"],
)
async def test_unusable_timeout_declaration_falls_back_and_still_times_out(
    bad_value: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**F4**：`timeout_s()` 返回 `nan`/`inf`/`<=0`/非数值 → **不采用**，改走兜底超时。

    判据是**后果**而不是"读到了哪个数"：让兜底值变小（`monkeypatch` 模块常量），
    然后断言一个**挂死的**处理器确实被超时掐掉（`5002`）。
    修复前 `nan`/`inf` 会被 `float()` 原样放行 ⇒ `asyncio.wait(timeout=nan)` 永不超时
    ⇒ 这个用例会挂到外层 `wait_for` 上（红）。

    `<= 0` 的后果不同（"立即超时"）但处置相同：与"没有声明"同一档，MUST NOT 采用。
    """
    fallback = 0.05
    monkeypatch.setattr(
        "aicore.core.task_runner.FALLBACK_HANDLER_TIMEOUT_S", fallback, raising=True
    )

    class _BadTimeout:
        def timeout_s(self) -> object:
            return bad_value

        async def handle(self, task: ClaimedTask) -> None:
            await asyncio.Event().wait()  # 挂死（只有超时能结束它）

    harness = Harness(
        tasks=[_claimed("task-a")],
        handlers={TASK_TYPE: _BadTimeout()},
        config=RunnerConfig(
            lease_ms=LEASE_MS, max_retries=0, concurrency_limit=4, poll_interval_s=0.0
        ),
    )
    claimed = await harness.runner.claim_once()
    assert claimed is not None

    await asyncio.wait_for(
        harness.runner.execute(claimed, claim=harness.locks.claim_of("task-a")), timeout=5.0
    )

    assert harness.store.count("mark_failed") == 1, (
        f"timeout_s() 返回 {bad_value!r} 时任务没有被超时掐掉："
        f"该值被静默采用了（nan/inf 会关掉任务级超时；<=0 会把正常任务全判超时）"
    )
    assert "error_code=5002" in harness.events, "兜底超时必须按 5002 走失败分流"



# ---------------------------------------------------------------------------
# A2：领取路径的瞬时错误 MUST NOT 杀死轮询循环
# ---------------------------------------------------------------------------
async def test_transient_claim_failure_does_not_kill_the_loop(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """**A2**：`list_claimable` 抛一次瞬时错误后，`run_forever` **继续工作**并领到任务。

    修复前：`claim_once()` 没有兜底，一次 `ProgrammingError`（例如当月表还没建出来）
    就让协程死掉——**进程活着、执行器已死、且没有任何日志**（`create_task` 的异常只在
    关停时才 retrieve）。

    四段断言：

    1. 循环**没有**结束（`not loop_task.done()`）；
    2. 记了 ERROR（含"连续第 N 次"计数，让持续失败在日志里可见）；
    3. 失败之后**仍然领到了任务**（恢复能力，而不是"活着但不干活"）；
    4. `stop` 仍能打断（收尾没有卡在退避里）。
    """
    harness = Harness(tasks=[_claimed("task-a")], handlers={TASK_TYPE: FakeHandler()})
    harness.store.claim_failures = [RuntimeError("(1146, \"Table doesn't exist\")")]
    runner = TaskRunner(
        store=harness.store,
        locks=harness.locks,
        handlers={TASK_TYPE: harness.handler},
        policies=REGISTRY,
        config=RunnerConfig(
            lease_ms=LEASE_MS, max_retries=3, concurrency_limit=4, poll_interval_s=0.0
        ),
    )
    stop = asyncio.Event()
    with caplog.at_level(logging.ERROR, logger="aicore.core.task_runner"):
        loop_task = asyncio.create_task(runner.run_forever(stop=stop))
        deadline = time.monotonic() + 5.0
        while harness.store.count("mark_succeeded") < 1 and time.monotonic() < deadline:
            await asyncio.sleep(0.01)  # ai-allow-sleep: 让出控制权给执行器协程（循环等待）

        assert not loop_task.done(), (
            f"一次瞬时错误就把轮询循环杀死了（done={loop_task.done()}）："
            f"修复前这正是「进程活着、执行器已死、零日志」的形态"
        )
        stop.set()
        await asyncio.wait_for(loop_task, timeout=5)

    assert "领取任务失败" in caplog.text, f"瞬时错误没有记 ERROR：{caplog.text!r}"
    assert "连续第 1 次" in caplog.text, "日志里没有连续失败计数（持续失败会看不出来）"
    assert harness.store.count("mark_succeeded") == 1, (
        "失败之后没能恢复：循环活着但不再领任务"
    )


async def test_claim_failure_backoff_can_be_interrupted_by_stop(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """**A2**：领取失败的退避**可被 `stop` 打断**（验收第 19 条不得回退）。

    退避用 `stop.wait()` 当计时器而不是 `asyncio.sleep`：持续失败时 `stop.set()`
    必须**立刻**让循环退出，而不是等完当前那一档退避。

    场景：让 `list_claimable` **永远失败**（持续故障），退避会一路涨到上限；
    在第一次失败之后立刻 `set`，断言循环迅速返回。

    ## 判据的前提是**条件等待**，不是"让出 5 次"（F13）

    第一版用 `for _ in range(5): await asyncio.sleep(0)` 去凑"循环已经进入退避计时"。
    让步轮数不是判据：机器慢一点时循环可能还没走到退避，`stop.set()` 就落在了
    "还没开始退避"的时刻——那时用例依然绿，但它证明的东西已经不是它声称的东西。
    现在等的是**那件事本身**：退避的 ERROR 日志（它就在 `await stop.wait()` 那一行之前），
    条件 + 有界 deadline，超时即断言失败。
    """
    harness = Harness(tasks=[], handlers={TASK_TYPE: FakeHandler()})
    harness.store.claim_failures = [RuntimeError("永久故障")] * 1000
    runner = TaskRunner(
        store=harness.store,
        locks=harness.locks,
        handlers={TASK_TYPE: harness.handler},
        policies=REGISTRY,
        config=RunnerConfig(
            lease_ms=LEASE_MS, max_retries=3, concurrency_limit=4, poll_interval_s=0.0
        ),
    )
    stop = asyncio.Event()

    def _backoff_logged() -> bool:
        return any("领取任务失败" in record.getMessage() for record in caplog.records)

    with caplog.at_level(logging.ERROR, logger="aicore.core.task_runner"):
        loop_task = asyncio.create_task(runner.run_forever(stop=stop))
        deadline = time.monotonic() + 5.0
        while not _backoff_logged() and time.monotonic() < deadline:
            await asyncio.sleep(0)  # ai-allow-sleep: 0 秒，把控制权让给执行器协程（条件等待）
        assert _backoff_logged(), (
            f"5s 内没有出现退避日志：本用例的前提不成立（循环没走到退避）\n{caplog.text}"
        )
        started = time.monotonic()
        stop.set()
        await asyncio.wait_for(loop_task, timeout=2.0)

    elapsed = time.monotonic() - started
    assert elapsed < 0.5, (
        f"stop 之后花了 {elapsed:.3f}s 才退出：退避没有走 stop.wait()（硬等了一整个退避档）"
    )


# ---------------------------------------------------------------------------
# **F1/F2/F3 的判别力自证**（变异体 = 修复前的**结构性**形态，直接继承生产类）
# ---------------------------------------------------------------------------
class _PreFixExecuteRunner(TaskRunner):
    """**F1/F2/F3 变异体**：把"进入 `try`"推迟到 `create_task` **之后**、且 `finally` 只收心跳。

    这与修复后的唯一差别是**结构**（不是三条路径各打一个补丁）：

    ```python
    heartbeat = asyncio.create_task(_heartbeat())
    handler_task = asyncio.create_task(handler.handle(claimed))   # ← 修复后它在 try 之内
    await handler_task                                            # ← 非 AiCoreError 从这里冒出
    try: ...
    finally: await self._cancel_heartbeat(heartbeat)   # ← 只有"进了 try"才会执行
    ```

    修复前的生产代码是 `try` 从**更靠后**的位置才开始（`wait` 那一段），
    于是「`create_task` 抛 `TypeError`（F3）」「`result()` 抛非 `AiCoreError`（F1）」
    「取消落在 `execute` 自己身上（F2）」三条路径都在进入 `finally` **之前**冒出 `execute`
    ⇒ 心跳与处理器 task 双双脱离所有回收路径。

    变异体**只保留这三条路径共同需要的那段结构**（起心跳 → 创建/等待处理器 task），
    因为它要证明的是"判据 ②③ 在修复前的结构上会红"，而不是复刻生产代码的每一行
    （复刻越多，变异体本身的错误越容易伪装成"判据的判别力"）。
    """

    async def execute(self, claimed: ClaimedTask, *, claim: TaskClaim | None = None) -> None:
        resolved = self._claims.pop(claimed.task_id, None) if claim is None else claim
        if resolved is None:
            resolved = TaskClaim(task_id=claimed.task_id, token="", attempt=1)
        # 生产用 `run_in_threadpool`（同步 store → 线程池）；变异体只关心"心跳什么时候起、
        # try 从哪里开始、finally 收哪些 task"，故直接调用同步 store —— 记进调用序列的效果一致。
        self._store.begin_attempt(
            claimed.task_id,
            account_id=claimed.account_id,
            created_at=claimed.created_at,
        )

        async def _heartbeat() -> None:
            interval = self._config.lease_ms / 1000.0 / HEARTBEAT_DIVISOR
            while True:
                # 变异体复制的是**修复前的心跳**，它的等待与生产同形（间隔 10ms）。
                await asyncio.sleep(interval)  # ai-allow-sleep: 变异体心跳间隔 10ms，仅证明泄漏
                if not await self._locks.renew(resolved, lease_ms=self._config.lease_ms):
                    return

        handler = self._handlers.get(claimed.task_type)
        heartbeat = asyncio.create_task(_heartbeat())
        # ---- 修复前的结构：create_task 与首次 await 都在 try 之外 ----
        handler_task = asyncio.create_task(handler.handle(claimed))
        await handler_task
        try:
            pass
        finally:
            await self._cancel_heartbeat(heartbeat)


@pytest.mark.parametrize(
    "handler_factory",
    [
        lambda: _ValueErrorHandler(),
        lambda: _SyncHandleHandler(),
    ],
    ids=["F1:处理器抛 ValueError", "F3:handle 是同步函数"],
)
async def test_f1_f3_guard_discriminates(
    handler_factory: Callable[[], object], caplog: pytest.LogCaptureFixture
) -> None:
    """**F1/F3 的判别力自证**：在修复前的结构上，共用判据 `_assert_no_heartbeat_leak`
    **必须变红**，且红在**判据 ②（心跳仍在续期）**上。

    为什么断言的失败信息是"心跳仍在续期"而不是"有心跳 task 泄漏"：② 是**判别力所在**
    （泄漏的唯一后果是"租约被永久续期"），③ 只是同一件事的另一种观察方式。
    这里显式锚定 ②，是为了说明"用例的红来自失效形态本身"，
    而不是来自任何与判据无关的偶然（例如变异体写错了导致不是 `ValueError`/`TypeError`）。

    若变异体**没有**红，说明 F1/F3 的用例另有来源、或该结构其实无害——两种情况都必须查清，
    故这里把"变异体自己也要真的失效"写进断言。
    """
    handler = handler_factory()
    harness = Harness(
        tasks=[_claimed("task-a")],
        handlers={TASK_TYPE: handler},  # type: ignore[dict-item]
        handler=handler,  # type: ignore[arg-type]
        config=RunnerConfig(
            lease_ms=SHORT_LEASE_MS, max_retries=3, concurrency_limit=4, poll_interval_s=0.0
        ),
    )
    runner = _PreFixExecuteRunner(
        store=harness.store,
        locks=harness.locks,
        handlers={TASK_TYPE: handler},  # type: ignore[dict-item]
        policies=REGISTRY,
        config=harness.runner.config,
    )
    claimed = await runner.claim_once()
    assert claimed is not None

    with caplog.at_level(logging.WARNING, logger="aicore.core.task_runner"):
        with pytest.raises((ValueError, TypeError)):
            await runner.execute(claimed, claim=harness.locks.claim_of("task-a"))

        # 判据 ② 必须红 —— 这正是修复前"租约被永久续期"的失效形态。
        with pytest.raises(AssertionError, match="心跳仍在续期"):
            await _assert_no_heartbeat_leak(harness, "task-a")

    # 判据 ③ 也要红（同一形态的另一种观察方式）：泄漏的 `_heartbeat` 仍在 `all_tasks()` 里。
    leaked = [
        task.get_coro().__qualname__
        for task in asyncio.all_tasks()
        if task is not asyncio.current_task() and not task.done()
    ]
    assert any("_heartbeat" in name for name in leaked), (
        f"变异体没有泄漏心跳：{leaked}——那说明 F1/F3 的判据另有来源，本自证不成立"
    )
    # 收尾：把泄漏的心跳收掉，免得影响后续用例。
    for task in asyncio.all_tasks():
        if task is not asyncio.current_task() and "_heartbeat" in task.get_coro().__qualname__:
            task.cancel()


async def test_f2_guard_discriminates() -> None:
    """**F2 的判别力自证**：取消落在 `execute` 自己身上时，修复前的结构**必然泄漏**心跳。

    变异体里"进入 `try` 之前"就有一个 `await handler_task`，故 `execute` 被取消时
    `finally` 不执行 —— 与生产修复前的形态同因同果。断言仍是"红在判据 ② 上"。
    """
    gate = asyncio.Event()
    handler = _ValueErrorHandler(gate=gate)
    harness = Harness(
        tasks=[_claimed("task-a")],
        handlers={TASK_TYPE: handler},
        handler=handler,
        config=RunnerConfig(
            lease_ms=SHORT_LEASE_MS, max_retries=3, concurrency_limit=4, poll_interval_s=0.0
        ),
    )
    runner = _PreFixExecuteRunner(
        store=harness.store,
        locks=harness.locks,
        handlers={TASK_TYPE: handler},
        policies=REGISTRY,
        config=harness.runner.config,
    )
    claimed = await runner.claim_once()
    assert claimed is not None
    executing = asyncio.create_task(
        runner.execute(claimed, claim=harness.locks.claim_of("task-a"))
    )
    await asyncio.wait_for(handler.started.wait(), timeout=5)

    executing.cancel()
    with pytest.raises(asyncio.CancelledError):
        await executing

    with pytest.raises(AssertionError, match="心跳仍在续期"):
        await _assert_no_heartbeat_leak(harness, "task-a")

    # 收尾：把泄漏的心跳与孤儿处理器 task 都收掉。
    for task in asyncio.all_tasks():
        if task is not asyncio.current_task() and not task.done():
            task.cancel()
    await asyncio.sleep(0)  # ai-allow-sleep: 0 秒，让取消请求送达被清理的 task


class _PreFixA2Runner(TaskRunner):
    """**A2 变异体**：`run_forever` 里**没有**领取失败的兜底（一次瞬时错误就死）。

    与修复后的唯一差别：`claimed = await self.claim_once()` **不在 `try` 里**、
    循环里也没有失败退避。其余（含 B1/B2 的修复）与生产逐字相同，
    故"循环会不会被一次瞬时错误杀死"是**唯一**的自变量。
    """

    async def run_forever(self, *, stop: asyncio.Event) -> None:
        """修复前的形态：`claim_once()` 裸调（一次抛错即结束整个协程）。"""
        semaphore = asyncio.Semaphore(self._config.concurrency_limit)
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=self._config.poll_interval_s)
                break
            except TimeoutError:
                pass
            if stop.is_set():
                break
            if len(self._inflight) >= self._config.concurrency_limit:
                with suppress(TimeoutError):
                    await asyncio.wait_for(
                        self._any_task_active.wait(), timeout=self._config.poll_interval_s
                    )
                continue
            await semaphore.acquire()
            claimed = await self.claim_once()  # ← 修复前：没有 try，抛错就死
            if claimed is None:
                semaphore.release()
                continue
            self._track(asyncio.create_task(self._execute_with_permit(semaphore, claimed)))
        await self._drain_inflight()


async def test_a2_guard_discriminates(caplog: pytest.LogCaptureFixture) -> None:
    """**A2 的判别力自证**：去掉领取失败的兜底，`test_transient_claim_failure_...`
    的判据（循环没死）**必须变红**。

    断言的是**变异体的失效形态真的发生了**：一次 `list_claimable` 抛错就把
    `run_forever` 结束掉（`loop_task` 已完成），且**没有任何 ERROR 日志**——
    那正是「进程活着、执行器已死、零信号」的最坏形态。
    """
    harness = Harness(tasks=[], handlers={TASK_TYPE: FakeHandler()})
    harness.store.claim_failures = [RuntimeError("(1146, 表不存在)")]
    runner = _PreFixA2Runner(
        store=harness.store,
        locks=harness.locks,
        handlers={TASK_TYPE: harness.handler},
        policies=REGISTRY,
        config=RunnerConfig(
            lease_ms=LEASE_MS, max_retries=3, concurrency_limit=4, poll_interval_s=0.0
        ),
    )
    stop = asyncio.Event()
    with caplog.at_level(logging.ERROR, logger="aicore.core.task_runner"):
        loop_task = asyncio.create_task(runner.run_forever(stop=stop))
        with pytest.raises(RuntimeError):
            await asyncio.wait_for(loop_task, timeout=5)

    assert loop_task.done(), "变异体的循环没有结束：自证不成立"
    assert "领取任务失败" not in caplog.text, (
        f"变异体竟然记了日志：{caplog.text!r}——那说明这条路径另有兜底，本自证不成立"
    )
def _runner_tree() -> ast.Module:
    return ast.parse(RUNNER_PATH.read_text(encoding="utf-8"))


def _imported_modules(tree: ast.Module) -> list[str]:
    """源码里出现过的全部 import 目标（`from X import y` 取 `X`，`import X` 取 `X`）。"""
    return sorted(
        {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        }
        | {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
    )


def _forbidden_hits(imported: Sequence[str]) -> list[str]:
    """命中禁用包清单的 import 目标（前缀匹配，含子模块）。"""
    return [
        name
        for name in imported
        if any(
            name == bad or name.startswith(f"{bad}.")
            for bad in FORBIDDEN_CORE_IMPORTS
        )
    ]


def test_runner_does_not_import_any_business_layer() -> None:
    """契约 4 的**本地**判据：`core/task_runner.py` MUST NOT import 任何业务层。

    `lint-imports` 守的是全树；这一条守的是**本文件**，且自带判别力自证
    （见 `test_import_guard_discriminates`）——否则判据可能只是"扫了个空文件"。

    **两条都是结构判据（F11 的边界，如实登记）**：本层没有"行为版"的等价判据
    ——"有没有 import 业务层"本身就是一个只能看源码的事实。它的**行为侧含义**
    （策略表由组合根注入而不是自己 import）由
    `test_a_structurally_satisfying_object_can_really_be_injected_and_used`
    与 `tests/integration/test_main_assembly.py` 的装配用例间接覆盖。
    """
    hits = _forbidden_hits(_imported_modules(_runner_tree()))
    assert hits == [], f"core/task_runner.py 导入了业务层 {hits}（契约 4 禁止 core → 业务层）"


def test_import_guard_discriminates() -> None:
    """判别力自证：把「禁 import」的形态**在内存里**合成一次，判据必须判红。

    变异只在内存里做字符串替换，**不落盘**（本组有过"改 `src/` + finally 还原"被打断、
    把注入残留在交付文件里的现场）。
    """
    source = RUNNER_PATH.read_text(encoding="utf-8")
    anchor = "from aicore.core.lease import LockStore, TaskClaim"
    assert anchor in source, (
        "内存变异的锚点没匹配上（runner 的 import 块已改）：自证会退化成空操作，等于没验"
    )
    mutated = source.replace(
        anchor, f"from aicore.service.task.registry import REGISTRY\n{anchor}", 1
    )
    assert mutated != source
    hits = _forbidden_hits(_imported_modules(ast.parse(mutated)))
    assert hits == ["aicore.service.task.registry"], (
        f"判据对注入的 service 导入失去判别力：报出 {hits}"
    )


def _policy_timeout_reads(tree: ast.Module) -> list[tuple[int, str]]:
    """扫出「读 `policy` 的 `timeout_s`」的位置（`(行号, 形态)`）。

    判据刻意取**窄**：只看「属性访问链里出现 `timeout_s`，且接收者名字含 `policy`」。
    取宽（凡出现 `timeout_s` 就判红）会误伤 `handler.timeout_s()`——那是**唯一合法**的
    超时来源（工单 §2.5 硬约束 4）。
    """
    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == "timeout_s":
            target = node.value
            is_policy_read = (
                isinstance(target, ast.Name) and "policy" in target.id
            ) or (isinstance(target, ast.Attribute) and "policy" in ast.unparse(target))
            if is_policy_read:
                hits.append((node.lineno, ast.unparse(node)))
    return hits


def test_runner_never_reads_policy_timeout() -> None:
    """**控制者裁定第 ② 条**：`TaskRunner` MUST NOT 读 `policy.timeout_s`。

    注册表行内的 `timeout_s` 是**配置默认值快照、不是权威值**（Task 4.6 的
    `_BORROWED_TIMEOUT_S`）：权威值只在 `get_policy` 现读 `Settings` 时才产生。
    执行器若读了它，就会静默拿到一个**不随配置变**的超时——"取了一个看起来对的错值"
    比报错更难查。故 `core/task_runner.py` 的 `TaskPolicy` Protocol **不声明**该成员，
    并由本用例逐处钉住。

    **行为判据为主、AST 判据为辅（F11）**：行为侧是
    `test_handler_timeout_goes_through_the_failure_path_with_5002`（超时确实取
    `handler` 声明的值）与 `test_unusable_timeout_declaration_falls_back_and_still_times_out`
    （不可用的声明改走兜底）。本用例的已知弱点：把 `policy.timeout_s` 读进一个
    **接收者名字不含 `policy`** 的局部变量（`t = p.timeout_s`）它就看不见——
    故它只作辅助，MUST NOT 被当成"这条约束已被完整守住"。
    """
    assert _policy_timeout_reads(_runner_tree()) == [], (
        "core/task_runner.py 读了 policy.timeout_s：任务级超时 MUST 取 handler.timeout_s()"
    )
    # 非空下限：判据面对的是有内容的源码，且合法的超时读取确实存在。
    # 实测：生产代码用 `getattr(handler, "timeout_s", None)`（带缺声明兜底），
    # 故非空下限同时认**属性访问**与**字符串常量**两种形态——只认前者会让本用例
    # 在正确实现上恒红（那是"无效判据"，与"恒绿"同样糟）。
    timeout_mentions = [
        node
        for node in ast.walk(_runner_tree())
        if (isinstance(node, ast.Attribute) and node.attr == "timeout_s")
        or (isinstance(node, ast.Constant) and node.value == "timeout_s")
    ]
    assert timeout_mentions, "找不到任何 timeout_s 读取：判据可能扫错了文件（假绿）"
    assert any(
        isinstance(node, ast.FunctionDef) and node.name == "_declared_timeout_s"
        for node in ast.walk(_runner_tree())
    ), "找不到 _declared_timeout_s：任务级超时的唯一取值处不见了"


def test_policy_timeout_guard_discriminates() -> None:
    """判别力自证：合成一段读 `policy.timeout_s` 的源码，判据必须判红（**内存变异，不落盘**）。"""
    source = RUNNER_PATH.read_text(encoding="utf-8")
    anchor = "        self._config = config"
    assert anchor in source, "内存变异的锚点没匹配上，自证会退化成空操作"
    mutated = source.replace(
        anchor,
        "        self._borrowed = policies_timeout(policy)\n" + anchor,
        1,
    )
    mutated = mutated.replace(
        "    def now(self) -> datetime:",
        "    def borrowed(self, policy: TaskPolicy) -> float:\n"
        "        return policy.timeout_s\n\n"
        "    def now(self) -> datetime:",
        1,
    )
    assert mutated != source
    hits = _policy_timeout_reads(ast.parse(mutated))
    assert hits and hits[0][1] == "policy.timeout_s", (
        f"判据对合成的 policy.timeout_s 读取失去判别力：报出 {hits}"
    )


def test_runner_has_no_task_type_literals() -> None:
    """§2.5 补充：`task_runner.py` MUST NOT 出现任何任务类型字面量。

    与 `tests/unit/test_task_registry.py` 的同名判据**同向但独立**：那一条在
    `task_runner.py` 还是空壳时会 `skip`，本文件在它交付后重新钉一遍
    （Task 4.7 之后那条 skip 会自动消失，两条同时生效）。
    本判据**不**断言 `TaskHandler` 之类的形状，只扫字符串常量——取严口径（含 docstring）。

    **行为判据为主、AST 判据为辅（F11）**：行为侧是
    `test_a_structurally_satisfying_object_can_really_be_injected_and_used`
    （执行器经**注入的映射**解析类型，映射里放什么类型它就用什么）与
    `test_unknown_policy_is_treated_as_not_retryable`（表里查不到的类型的处置）。
    本用例的已知弱点：只在**注册表里恰好出现的字符串**上判红，
    写一个不在 `REGISTRY` 里的类型字面量（例如 `"ocr-v2"`）它看不见——
    故它只作辅助。
    """
    types = frozenset(REGISTRY)
    hits = sorted(
        (node.lineno, node.value)
        for node in ast.walk(_runner_tree())
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value in types
    )
    assert hits == [], f"task_runner.py 出现任务类型字面量 {hits}：执行器应按表查找解析类型"


def test_store_calls_go_through_a_worker_thread() -> None:
    """§2.5 补充（控制者裁定）：`TaskStore` 的每个方法都经 `run_in_threadpool` 调用。

    判据：store 被调用时的线程 ident **不等于**建立事件循环的线程 ident。
    直接断言「不等于主线程」不够——`pytest-asyncio` 的事件循环就跑在主线程上，
    而"在主线程"正是同步 SQL 会阻塞事件循环的那种形态。
    """
    harness = Harness(tasks=[_claimed("task-a")], handlers={TASK_TYPE: FakeHandler()})

    async def _scenario() -> int:
        loop_thread = threading.get_ident()
        await harness.claim_and_execute("task-a")
        return loop_thread

    loop_thread = asyncio.run(_scenario())

    assert harness.store.thread_ids, "store 一次都没被调用：判据会变成空断言"
    assert all(ident != loop_thread for ident in harness.store.thread_ids), (
        f"store 在事件循环线程里被调用了：{harness.store.thread_ids}（loop={loop_thread}）"
    )


def test_runner_exposes_the_three_protocols_as_structural_types() -> None:
    """补充：`TaskStore` / `TaskHandler` / `TaskPolicy` 都是 `Protocol`（结构化子类型）。

    ## 判据分两层，缺一不可（N4 的修复：此前只有第 1 层）

    1. **类型层**：三个类都是 `Protocol`（`_is_protocol`）。这条**只说明声明形态**——
       复核者指出它是"纯类型层断言"，一个 `runtime_checkable` 与否、
       方法签名对不对，它一概不管；
    2. **行为层**（本轮补上）：把一个**完全不继承这三个类**的对象真的传进去、
       并且**真的被用起来**——`TaskRunner` 能拿它领取、跑完、写回。
       这才是"组合根可以做结构化注入"的实际含义：`main.py` 注入的是
       `SqlTaskLeaseStore` 与注册表的 `TaskPolicy`，两者**都不继承**本模块的任何基类。

    为什么第 1 层仍要留着：**删掉它就无法区分"结构化子类型成立"与"碰巧能跑"**——
    比如把 `TaskStore` 改成普通类后，第 2 层那组对象依然跑得通（Python 不检查），
    而 mypy 会在组合根报 `arg-type`。两层合起来才同时覆盖"静态可注入"与"运行时可注入"。
    """
    for protocol_cls in (TaskStore, TaskHandler, TaskPolicy):
        assert getattr(protocol_cls, "_is_protocol", False), (
            f"{protocol_cls.__name__} 不是 Protocol：组合根无法做结构化注入"
        )


async def test_a_structurally_satisfying_object_can_really_be_injected_and_used() -> None:
    """**行为层判据**（N4）：不继承任何基类的对象能被 `TaskRunner` 真的用起来。

    用一个**独立定义、不 import 任何 `Protocol`** 的三件套（store / locks / handler）走完
    「领取 → 执行 → 写成功终态」全链路。它们与 `tests/unit/test_task_runner.py` 里那些替身
    一样满足结构化接口；区别在于本用例**只**依赖"方法名与签名对得上"。
    """
    events: list[str] = []

    class _Store:
        """只实现 `TaskStore` 的方法，**不继承**它（且都是**同步**方法，见 `TaskStore`）。"""

        def __init__(self) -> None:
            self.claimed = False

        def list_claimable(self, *, limit: int, now: datetime) -> Sequence[ClaimedTask]:
            events.append(f"list_claimable({limit})")
            return [] if self.claimed else [_claimed("task-a")]

        def begin_attempt(self, task_id: str, *, account_id: str, created_at: datetime) -> None:
            events.append("begin_attempt")

        def mark_succeeded(
            self,
            task_id: str,
            *,
            account_id: str,
            created_at: datetime,
            progress: int,
            finished_at: datetime,
        ) -> None:
            events.append("mark_succeeded")

        def mark_failed(
            self,
            task_id: str,
            *,
            account_id: str,
            created_at: datetime,
            error_code: str,
            finished_at: datetime,
        ) -> None:
            events.append("mark_failed")

        def requeue(self, task_id: str, *, account_id: str, created_at: datetime) -> None:
            events.append("requeue")

    class _Locks:
        """只实现锁店用到的四个方法，**不继承** `LockStore`。"""

        def __init__(self) -> None:
            self._claim: TaskClaim | None = None

        async def acquire(self, task_id: str, *, lease_ms: int) -> TaskClaim | None:
            events.append("acquire")
            self._claim = TaskClaim(task_id=task_id, token="t", attempt=1)
            return self._claim

        async def renew(self, claim: TaskClaim, *, lease_ms: int) -> bool:
            return True

        async def release(self, claim: TaskClaim) -> bool:
            events.append("release")
            return True

        async def is_deferred(self, task_id: str) -> bool:
            return False

        async def defer(self, task_id: str, *, delay_s: float) -> None:
            events.append("defer")

        async def close(self) -> None:
            return None

    class _Handler:
        """只实现 `TaskHandler` 的两个方法，**不继承**它。"""

        def timeout_s(self) -> float:
            return 5.0

        async def handle(self, task: ClaimedTask) -> None:
            events.append(f"handle({task.task_id})")

    runner = TaskRunner(
        store=_Store(),  # type: ignore[arg-type]
        locks=_Locks(),  # type: ignore[arg-type]
        handlers={TASK_TYPE: _Handler()},  # type: ignore[dict-item]
        policies={TASK_TYPE: _Policy()},  # type: ignore[dict-item]
        config=RunnerConfig(
            lease_ms=LEASE_MS, max_retries=3, concurrency_limit=4, poll_interval_s=0.0
        ),
    )

    assert await runner.run_once() is True, "结构化注入的对象没能被真的用起来"
    assert events == ["list_claimable(4)", "acquire", "begin_attempt", "handle(task-a)",
                      "mark_succeeded", "release"], (
        f"全链路没有按结构化接口跑完：{events}"
    )


class _Policy:
    """`TaskPolicy` 的结构化实现（**不继承** `TaskPolicy`）。"""

    task_type = TASK_TYPE
    retryable = True


# ---------------------------------------------------------------------------
# 内存变异工具（判别力自证用；**MUST NOT 落盘**）
# ---------------------------------------------------------------------------
#: 内存变异体的模块名（`sys.modules` 里的临时条目，用完即撤；见 `_mutant_runner_class`）。
_MUTANT_MODULE_NAME = "dsh_mutant_runner"


def _mutant_runner_class(*patches: tuple[str, str]) -> type[Any]:
    """把 `task_runner.py` 的源码在**内存里**改若干处，编译出一个变异类（**文件从不被写**）。

    `patches` 是若干 `(锚点, 替换)`；**每个锚点都必须唯一**（不唯一即 `AssertionError`）。

    ## 为什么必须内存变异（工单纪律）

    "改 `src/` → 跑 → `finally` 还原"这条路一旦中途失败（断言失败、进程被杀、`Ctrl-C`），
    就会把**变异体留在工作树里**，此后所有判据都在一个被改坏的产品上运行——
    那是最难查的一类假绿。这里 `read_text()` → `str.replace` → `compile` → `exec`，
    工作树里的 `.py` 从头到尾没被写过。

    ## 实现上的三个要点

    - **锚点必须唯一**（`source.count(anchor) == 1`）：否则"变异"会变成
      "改了一堆地方"，红了也说不清是哪一处造成的；锚点找不到时是**报错**而不是静默跳过——
      静默跳过会让自证变成"什么都没变、当然不红"。
    - 变异模块临时登记进 `sys.modules`：`@dataclass` 在装饰期需要按 `cls.__module__`
      反查模块（`from __future__ import annotations` 让注解是字符串），缺了它 `exec` 会抛
      `AttributeError`。用完即删，不留痕迹。
    - 返回的是**变异模块自己的** `TaskRunner` 类对象，与生产的类**不是同一个对象**。
      故注入点全部传生产侧的对象（`Harness` 的 store / locks / config）——
      这些注入点都是结构化 `Protocol`，跨模块实例化是合法的；也正因如此，
      "变异体与生产类的差别**只有锚点那几处**"。
    """
    source = RUNNER_PATH.read_text(encoding="utf-8")
    for anchor, replacement in patches:
        count = source.count(anchor)
        assert count == 1, (
            f"变异锚点在 task_runner.py 里出现 {count} 次（要求恰好 1 次）：{anchor!r}——"
            f"锚点漂了就必须先修锚点，MUST NOT 让它静默变成'什么都没变'"
        )
        source = source.replace(anchor, replacement)
    module = types.ModuleType(_MUTANT_MODULE_NAME)
    module.__file__ = str(RUNNER_PATH)
    code = compile(source, str(RUNNER_PATH), "exec")
    sys.modules[_MUTANT_MODULE_NAME] = module
    try:
        exec(code, module.__dict__)
    finally:
        del sys.modules[_MUTANT_MODULE_NAME]
    mutant_cls: type[Any] = module.__dict__["TaskRunner"]
    return mutant_cls


#: 修复前 `run_forever` 的**方法体**（**领了再排队**）——语义说明，**不是可执行代码**。
#:
#: 语义 = 修复前：**先领取、再把协程挂到信号量上排队**（许可的获取时机在领取之后）。
#: 它用的 `self.claim_once()` / `self._execute_with_permit(...)` / `self._track(...)`
#: 都是**生产类自己的**成员。
#:
#: **本常量没有读者**（此前的字符串变异实现已被删除）：B2 的顺序判据的判别力自证
#: 由 `_PreFixB2Runner`（直接继承生产类的子类）承担——字符串变异的锚点在缩进上一错就失真，
#: 实测踩过三次。保留它只为对照"修复前长什么样"，**故 MUST NOT 把它当成活判据**。
_LEGACY_RUN_FOREVER_BODY = """\
semaphore = asyncio.Semaphore(self._config.concurrency_limit)
while not stop.is_set():
    try:
        await asyncio.wait_for(stop.wait(), timeout=self._config.poll_interval_s)
        break
    except TimeoutError:
        pass
    if stop.is_set():
        break
    claimed = await self.claim_once()
    if claimed is None:
        continue
    self._track(asyncio.create_task(self._execute_with_permit(semaphore, claimed)))
await self._drain_inflight()
"""


class _NoCancelRunner(TaskRunner):
    """**B1 的变异体**：租约丢失后**不取消**处理器（修复前就是这么写的）。

    ## 为什么这样造变异体（而不是复制 `execute` 的控制流）

    第一版把生产的 `execute` 控制流整段抄进测试文件、只把"取消"那行去掉。那样造出来的
    变异体**每两行就与生产分叉一次**（哪次同步、哪次分叉全靠人读），而且一改生产代码就失真。

    这里的做法只动**一个注入点**：把处理器包一层 `_DetachedOnCancelHandler` ——
    它在协程被取消时**把工作交给一个脱离的 task** 继续跑（等价于"没人取消它"）。
    于是：

    - **生产 `execute` 一个字都不改**（含取消逻辑）；
    - 变异只体现在"取消之后工作还在不在"这一件事上 —— 与 B1 的语义一一对应；
    - 修复前/修复后的差别因此**只由取消是否真的发生**决定。

    `_DetachedOnCancelHandler` 正是"修复前那条路径"的忠实等价物：
    租约丢失时没人取消处理器 → 它跑完 → 付费调用发生。
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.detached: list[asyncio.Task[None]] = []


class _DetachedOnCancelHandler:
    """包装一个处理器：**被取消时不让它停**，而是把它挪到一个脱离的 task 上继续跑。

    这是"修复前没有取消逻辑"的等价物：`asyncio.Task.cancel()` 只能取消**等待点**，
    而这里的 `except CancelledError` 立刻用一个新 task 从头（或从当前进度）继续，
    于是"取消"变成了"换个人接着跑"。
    """

    def __init__(self, inner: _BadTurnHandler) -> None:
        self._inner = inner
        self.detached: list[asyncio.Task[None]] = []

    def timeout_s(self) -> float:
        return self._inner.timeout_s()

    async def handle(self, task: ClaimedTask) -> None:
        try:
            await self._inner.handle(task)
        except asyncio.CancelledError:
            # 修复前的等价形态：没人真的把工作停下来 —— 换个 task 接着跑完。
            self.detached.append(asyncio.create_task(self._inner.handle(task)))


async def test_lease_loss_cancel_guard_discriminates() -> None:
    """**B1 的判别力自证**：让"取消"失效，同一个场景下**必须变红**。

    变异方式：把处理器包一层 `_DetachedOnCancelHandler` —— 它**被取消时把工作挪到
    一个脱离的 task 上继续跑**，这正是"修复前那条路径"的忠实等价物
    （租约丢失时没人取消处理器 → 它跑完 → 付费调用发生）。
    生产 `execute` 一个字都不改，故修复前后的差别**只由"取消是否真的发生"决定**。

    场景：租约 30ms、心跳 10ms、处理器 300ms、`timeout_s=5.0`。

    - **变异后**：`execute` 在 10ms 左右返回（心跳发现租约丢失），
      而处理器**在脱离的 task 上继续跑完**——它会发出那次付费调用。
      注意此时**不能**断言 `handler.completed` 要紧跟 `execute` 之后：处理器还没跑完，
      要等它跑完才看得到副作用（第一版自证就栽在这个时序上）。
    - **修复后**：`execute` 取消处理器且**不接管**，副作用**永远不发生**
      （由 `test_renew_failure_abandons_without_any_terminal_write` 的 ③ 断言）。

    本用例断言的是**变异后的形态确实复现了"副作用照发"**。
    没有这一步，"取消分支真的有效"就只是代码里的一段话。
    """
    handler = _BadTurnHandler(delay_s=0.3)
    wrapped = _DetachedOnCancelHandler(handler)
    harness = Harness(
        tasks=[_claimed("task-a")],
        handlers={TASK_TYPE: wrapped},
        handler=wrapped,
        renew_result=False,  # 续期首次即被拒 = 租约丢失
    )
    runner = TaskRunner(
        store=harness.store,
        locks=harness.locks,
        handlers={TASK_TYPE: wrapped},
        policies=REGISTRY,
        config=harness.short_heartbeat_config(),
    )
    claimed = await runner.claim_once()
    assert claimed is not None
    started = time.monotonic()
    await asyncio.wait_for(
        runner.execute(claimed, claim=harness.locks.claim_of("task-a")), timeout=3.0
    )
    elapsed = time.monotonic() - started

    # 变异体的特征 ①：`execute` 在远小于处理器时长内返回（它没等处理器）。
    assert elapsed < 0.25, (
        f"execute 花了 {elapsed:.3f}s（处理器耗 0.3s）："
        f"自证的前提不成立（它似乎在等处理器）"
    )
    # 变异体的特征 ②：处理器**被取消后又被接管**，它随后跑完并发出副作用。
    #
    # 等它的方式是**条件等待 + 有界 deadline**（`wrapped.detached` 里的 task 就是
    # "被接管的那些工作"）：`execute` 返回时第一段已被取消、接管 task 已经建好，
    # 故这里不需要"轮询到某个标志位"——直接等那些 task 自己结束。
    assert wrapped.detached, (
        "处理器没有被取消后接管：那说明取消根本没发生，本自证没有复现修复前的形态"
    )
    await asyncio.wait_for(asyncio.gather(*wrapped.detached), timeout=3.0)

    assert handler.completed is True, (
        "被接管的处理器没有跑完：那说明取消另有来源，本自证没有证明 B1 的判别力"
    )
    assert handler.paid_calls == 1, (
        f"外部副作用为 {handler.paid_calls}（期望 1）："
        f"自证没有复现「重复外部调用」这一失效形态"
    )
    # 两条合起来 = 修复后用例的 ②③ 判据必然变红（它断言 completed=False 且 paid_calls=0）。


async def test_m1_abandon_guard_discriminates() -> None:
    """**M1 的判别力自证**：把"取消处理器"整个撤掉，**同一份判据** `_assert_lease_lost_abandons`
    **必须变红**。

    ## 变异（**内存变异，文件从不被写**，见 `_mutant_runner_class`）

    "取消处理器"在本实现里有**两处**（这正是 F2 的修复：`finally` 里也无条件收一次），
    故变异必须两处一起去掉，才等价于"修复前没人取消它"：

    1. `if lease_lost or timed_out:` → `if timed_out:`（撤掉租约丢失时的取消）；
    2. `finally` 里那行 `await _dissolve_task(handler_task)` → 删掉（撤掉兜底取消）。

    第 2 处是**本轮新出现的**：复核者当初只变异第 1 处就全绿了；那个变异**现在不再是
    "撤掉取消"**（`finally` 依然会取消），所以本自证必须两处一起动——
    **这一点本身就是 F2 修复有效的证据**：租约丢失路径的取消从"一处条件分支"变成了
    "结构上必然发生"，单一分支的变异不再能让它失效。

    ## 为什么必须单独证明一次

    判据 ②③（`completed is False` / `paid_calls == 0`）在**紧接着 `execute` 返回时读**是
    **恒真**的——不取消时处理器只是一个脱离的 task 还在 `sleep`。复核者实测：
    撤销取消后全量 1268 passed / 0 failed。所以"判据真的能判红"必须被看见一次。

    本用例与签名用例共用 `_assert_lease_lost_abandons`（**同一份判据、同一个调用形态**），
    差别只在产品代码的那两行。
    """
    mutant_cls = _mutant_runner_class(
        ("if lease_lost or timed_out:", "if timed_out:"),
        (
            "            await self._cancel_heartbeat(heartbeat)\n"
            "            await _dissolve_task(handler_task)\n",
            "            await self._cancel_heartbeat(heartbeat)\n",
        ),
    )
    handler = _BadTurnHandler(delay_s=0.3)
    harness = Harness(
        tasks=[_claimed("task-a")],
        handlers={TASK_TYPE: handler},
        handler=handler,
        renew_result=False,  # 续期首次即被拒 = 租约丢失
    )
    runner = mutant_cls(
        store=harness.store,
        locks=harness.locks,
        handlers={TASK_TYPE: handler},
        policies=REGISTRY,
        config=harness.short_heartbeat_config(),
    )
    claimed = await runner.claim_once()
    assert claimed is not None
    started = time.monotonic()
    await asyncio.wait_for(
        runner.execute(claimed, claim=harness.locks.claim_of("task-a")), timeout=3.0
    )
    elapsed = time.monotonic() - started

    # 变异体不取消处理器 ⇒ 它自己睡醒（0.3s）才停下来 ⇒ **越过那一刻**再读判据。
    stopped = await _wait_handler_stopped(handler, budget_s=2.0)
    assert stopped, "变异体的处理器在 2.0s 内没跑完：本自证的前提不成立"
    assert handler.paid_calls == 1, (
        f"变异体没有复现「付费调用照发」（paid_calls={handler.paid_calls}）：本自证不成立"
    )
    with pytest.raises(AssertionError, match="跑完了"):
        await _assert_lease_lost_abandons(harness, handler, elapsed=elapsed)
    # 收到断言之后把脱离的处理器收掉，免得污染后续用例。
    for task in asyncio.all_tasks():
        if task is not asyncio.current_task() and not task.done():
            task.cancel()
    await asyncio.sleep(0)  # ai-allow-sleep: 0 秒，让取消请求送达被清理的 task
