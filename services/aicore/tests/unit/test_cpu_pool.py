"""`core/task_runner.py` 的线程池边界用例（Task 4.8，工单 §3.3 的四条）。

**权威依据**：`design.md` L200-206 的并发模型表——「图像解码、脱敏处理、哈希与存证计算」
走 `run_in_executor`（CPU 密集），而「MySQL 访问」走线程池（阻塞 I/O）是**另一行**；
L206 逐字「若在协程内直接调用，一次脱敏就会卡住整个事件循环，使同一实例上所有任务受理
与轮询一起变慢——表现为『并发数不高但 P95 爆表』」。

## 关于 sleep 的两条纪律

1. **本文件是全套测试里唯一允许出现真等待的地方**（工单 §2.5b 逐字：「sleep 只允许出现在
   **专门验证线程边界**的那条用例，且时长 ≤ 0.15s」）。这里用的两个值：CPU 函数
   `time.sleep(0.1)`、定时协程 `asyncio.sleep(0.01)`——都在 0.15s 之内，
   且**每一处都带 `# ai-allow-sleep: <理由>`**（验收脚本第 4 项的判据支持行级豁免，
   理由必填；本文件共 2 处豁免，报告里有清单）。
2. **等待是判据本身的一部分**：「事件循环不被阻塞」只能靠"同时发生的两件事谁先完成"
   来判定，这一点无法用注入时钟替代——被注入的时钟不会真的把 `time.sleep` 放进线程里。
   故这两处等待不是"测试凑合等一会儿"，而是被测行为的载体。
"""

from __future__ import annotations

import ast
import asyncio
import inspect
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

from aicore.core.lease import InMemoryLockStore
from aicore.core.task_runner import (
    CPU_THREAD_PREFIX,
    ClaimedTask,
    RunnerConfig,
    TaskRunner,
    cpu_pool,
    run_cpu_bound,
)
from aicore.service.task.registry import REGISTRY

TASK_TYPE = "OCR"
#: `core/task_runner.py` 的路径（M3 的"无阻塞调用"判据要读它的源码）。
RUNNER_PATH = Path(__file__).resolve().parents[2] / "src" / "aicore" / "core" / "task_runner.py"


class _ThreadReporter:
    """在**工作线程**里跑的重活替身：报告线程 ident 与线程名，并提交一个"返回体"。"""

    def __init__(self, *, sleep_s: float = 0.0, order: list[str] | None = None) -> None:
        self.sleep_s = sleep_s
        self.order: list[str] | None = order

    def __call__(self) -> tuple[int, str]:
        if self.sleep_s:
            # 模拟一次真实 CPU 密集工作（解码 / 脱敏 / 哈希）的**时长**。
            time.sleep(self.sleep_s)  # ai-allow-sleep: 模拟 CPU 密集工作的时长（0.1s）
        if self.order is not None:
            self.order.append("cpu")
        return threading.get_ident(), threading.current_thread().name


async def test_cpu_bound_work_runs_outside_the_event_loop_thread() -> None:
    """22. `run_cpu_bound(fn)` 的返回体报告 `threading.get_ident()` **≠** 事件循环线程，
    且该线程名**属于注入的池**。

    线程名断言是「属于哪个池」的唯一可判定证据：只断言"不在事件循环线程"会漏掉
    「跑到了 anyio 的 worker 池」这类实现——那正是 `design.md:200-206` 要把两类工作
    分开的原因（一次图像解码会占住 MySQL 查询要用的线程）。
    """
    loop_thread = threading.get_ident()
    order: list[str] = []
    pool = cpu_pool(max_workers=2)
    try:
        ident, name = await run_cpu_bound(_ThreadReporter(order=order), executor=pool)
    finally:
        pool.shutdown(wait=False)

    assert ident != loop_thread, "重活跑在事件循环线程里：整个服务会被它卡住"
    assert name.startswith(CPU_THREAD_PREFIX), (
        f"线程名 {name!r} 不属于专用 CPU 池（前缀应为 {CPU_THREAD_PREFIX!r}）："
        f"「谁在用哪个池」在排障时看不出来"
    )
    assert order == ["cpu"]


async def test_event_loop_keeps_running_while_cpu_work_is_in_flight() -> None:
    """23. **事件循环不被阻塞**：重活在跑的同时，定时协程先完成。

    这是「并发提交时受理接口耗时不劣化」在离线段的**可判定替身**（真压测归 13.4）：

    - CPU 函数在线程里睡 0.1s；
    - 一个 `asyncio` 定时协程在主循环上等 0.01s；
    - `run_cpu_bound` **返回之后**事件循环才第一次得到机会运行；
    - 故定时协程若在 CPU 函数**完成前**就已结束，说明它跑在自己的线程里。

    判据取**完成顺序**（同一个 `order` 列表里的先后）而不是耗时数字：顺序不受机器
    快慢影响，而"耗时小于某值"这类断言会在慢机器上假红。
    """
    order: list[str] = []
    pool = cpu_pool(max_workers=1)
    try:
        async def _cpu() -> tuple[int, str]:
            return await run_cpu_bound(
                _ThreadReporter(sleep_s=0.1, order=order), executor=pool
            )

        async def _timer() -> None:
            await asyncio.sleep(0.01)  # ai-allow-sleep: 定时协程（0.01s），证明循环没被挡住
            order.append("timer")

        cpu_task = asyncio.create_task(_cpu())
        timer_task = asyncio.create_task(_timer())
        await asyncio.wait_for(cpu_task, timeout=5)
        await asyncio.wait_for(timer_task, timeout=5)
    finally:
        pool.shutdown(wait=False)

    assert order == ["timer", "cpu"], (
        f"完成顺序是 {order}（期望 ['timer', 'cpu']）："
        f"重活把事件循环挡住了，10ms 的定时协程只能等它跑完"
    )


async def test_default_executor_path_still_runs_off_the_event_loop_thread() -> None:
    """24. `executor=None` 时用事件循环默认执行器，且仍是**别的线程**。

    这一条钉住 `loop.run_in_executor(None, ...)` 这条退化路径仍然成立：
    `run_cpu_bound` 的 `executor` 是必填参数，但调用方可能显式传 `None`
    （Python 语义里 `None` 表示"事件循环的默认执行器"）。此时"不在事件循环线程"
    这条**最低**保证仍必须成立——否则一个传 `None` 的调用点会静默卡住整个服务。
    **它的边界（如实登记）**：默认池是进程共享的，故"属于哪个池"在这里无从断言，
    只能断言"不是事件循环线程"。

    ## R2 修复点：本用例**真的**传 `None` 了

    第一版的名字与 `_run_with_none_executor` 都说在测 `executor=None`，实际传的是
    `runner.executor`（自建池）——于是 `run_cpu_bound(..., executor=None)`
    **从未被任何用例执行过**，而本用例却"绿"着。现在直接传 `None`。
    """
    loop_thread = threading.get_ident()
    order: list[str] = []

    ident, name = await run_cpu_bound(_ThreadReporter(order=order), executor=None)

    assert ident != loop_thread, "默认执行器把重活放在了事件循环线程里"
    assert order == ["cpu"]
    assert name, "线程名不该是空串（排障要靠它定位）"


# ---------------------------------------------------------------------------
# 25. 判别力自证
# ---------------------------------------------------------------------------
async def test_criteria_discriminate_against_a_direct_call() -> None:
    """25. **判别力自证**：把 `run_cpu_bound` 换成直接 `fn()`，第 22 / 23 条**必须变红**。

    用**合成实现**（等价于"不经过执行器"的直调版本），在内存里跑，不落盘。
    没有这一步，第 22 / 23 条可能只是"永远为真"的断言——本组已被抓到三处假绿，
    故每条结构判据都要自带判别力证明。
    """
    loop_thread = threading.get_ident()
    order: list[str] = []

    async def _naive_cpu_bound() -> tuple[int, str]:
        """直调版本（变异体）：不经过任何执行器。"""
        return _ThreadReporter(sleep_s=0.1, order=order)()

    async def _timer() -> None:
        await asyncio.sleep(0.01)  # ai-allow-sleep: 判别力自证里的定时协程（0.01s）
        order.append("timer")

    cpu_task = asyncio.create_task(_naive_cpu_bound())
    timer_task = asyncio.create_task(_timer())
    ident, name = await asyncio.wait_for(cpu_task, timeout=5)
    await asyncio.wait_for(timer_task, timeout=5)

    # 判据 22 的断言在直调版本上必须失败：
    assert ident == loop_thread, (
        "直调版本竟然不在事件循环线程里：自证的前提不成立，第 22 条的判别力未被证明"
    )
    assert not name.startswith(CPU_THREAD_PREFIX), (
        f"直调版本的线程名 {name!r} 竟然属于 CPU 池：自证失效"
    )
    # 判据 23 的断言在直调版本上也必须失败：
    assert order == ["cpu", "timer"], (
        f"直调版本的完成顺序是 {order}（期望 ['cpu', 'timer']）："
        f"第 23 条在变异体上仍会通过，说明它没有判别力"
    )


# ---------------------------------------------------------------------------
# `TaskRunner` 的池归属：自建 / 注入 / 关闭
# ---------------------------------------------------------------------------
def _claimed(task_id: str = "task-a") -> ClaimedTask:
    return ClaimedTask(
        task_id=task_id,
        task_type=TASK_TYPE,
        account_id="acc_0000000000000000000000000001",
        created_at=datetime(2026, 9, 16, 10, 30, tzinfo=UTC),
    )


class _NoopHandler:
    def timeout_s(self) -> float:
        return 1.0

    async def handle(self, task: ClaimedTask) -> None:
        return None


class _NoopStore:
    def list_claimable(self, *, limit: int, now: datetime) -> list[ClaimedTask]:
        return []

    def begin_attempt(self, task_id: str, *, account_id: str, created_at: datetime) -> None:
        return None

    def mark_succeeded(
        self,
        task_id: str,
        *,
        account_id: str,
        created_at: datetime,
        progress: int,
        finished_at: datetime,
    ) -> None:
        return None

    def mark_failed(
        self,
        task_id: str,
        *,
        account_id: str,
        created_at: datetime,
        error_msg: str = "",
        error_code: str = "",
        finished_at: datetime | None = None,
    ) -> None:
        return None

    def requeue(self, task_id: str, *, account_id: str, created_at: datetime) -> None:
        return None


def _minimal_runner(*, executor: ThreadPoolExecutor | None = None) -> TaskRunner:
    """一个最小的 `TaskRunner`（只为拿它的 `executor` 与 `stop()` 语义）。"""
    return TaskRunner(
        store=_NoopStore(),  # type: ignore[arg-type]
        locks=InMemoryLockStore(),
        handlers={TASK_TYPE: _NoopHandler()},
        policies=REGISTRY,
        config=RunnerConfig(lease_ms=30_000, max_retries=3, concurrency_limit=3),
        executor=executor,
    )


async def test_runner_builds_a_dedicated_pool_sized_by_concurrency_limit() -> None:
    """`executor=None` 时**自建**专用池（`max_workers=concurrency_limit`），
    MUST NOT 落到默认执行器。

    判据取 `_max_workers`（池的自省属性）：只断言"不是默认执行器"没有可判定的形态
    ——默认执行器是进程级的共享池，拿不到一个可以比较的对象。
    """
    runner = _minimal_runner()

    assert isinstance(runner.executor, ThreadPoolExecutor)
    assert runner.executor._max_workers == 3
    # 自建的池确实带我们的线程名前缀（与 `cpu_pool` 同一处实现）。
    _ident, name = await run_cpu_bound(_ThreadReporter(), executor=runner.executor)
    assert name.startswith(CPU_THREAD_PREFIX)

    await runner.aclose()


async def test_runner_shuts_down_only_the_pool_it_created() -> None:
    """自建的池在 `stop()` / `aclose()` 里 `shutdown(wait=False)`；注入的池**不**被关闭。

    两半都要断言：

    - 自建的池：关闭之后**不能再提交**（`RuntimeError`）——这是"确实关了"的可判定证据，
      比断言"调用过 shutdown"强（后者可以用一个假对象糊过去）；
    - 注入的池：`stop()` 之后**仍能提交并跑出结果**——谁创建谁释放，执行器不该越权
      关掉调用方的资源。
    """
    owned = _minimal_runner()
    await owned.stop()
    await owned.aclose()  # 幂等：重复调用不报错
    try:
        owned.executor.submit(lambda: None)
    except RuntimeError:
        pass
    else:  # pragma: no cover - 走到这里说明池没被关闭
        raise AssertionError("自建的池在 stop() 之后仍能提交：shutdown 没有生效")

    external = ThreadPoolExecutor(max_workers=2, thread_name_prefix="caller-pool")
    try:
        runner = _minimal_runner(executor=external)
        await runner.stop()
        # 注入的池必须还活着：提交一个任务并等它出结果。
        assert external.submit(lambda: 42).result(timeout=5) == 42, (
            "执行器关掉了调用方注入的池（谁创建谁释放）"
        )
    finally:
        external.shutdown(wait=False)


def test_cpu_pool_threads_carry_the_documented_prefix() -> None:
    """`cpu_pool` 建出的线程名带 `CPU_THREAD_PREFIX`（排障与用例共用的判据来源）。"""
    pool = cpu_pool(max_workers=1)
    try:
        name = pool.submit(lambda: threading.current_thread().name).result(timeout=5)
    finally:
        pool.shutdown(wait=False)
    assert name.startswith(CPU_THREAD_PREFIX), f"线程名 {name!r} 不带池前缀"


def test_run_cpu_bound_requires_an_explicit_executor() -> None:
    """`run_cpu_bound` 的 `executor` **必须显式传入、MUST NOT 有默认值**。

    设计文档要求两类工作分开（CPU 密集 vs 阻塞 I/O），把池做成默认值会让「用了哪个池」
    变成隐式事实——故这是一条**签名级**约束，用 `inspect.signature` 钉住，
    而不是靠"实现里别写默认值"的口头约定。
    """
    signature = inspect.signature(run_cpu_bound)
    executor_param = signature.parameters["executor"]
    assert executor_param.kind is inspect.Parameter.KEYWORD_ONLY, "executor 必须是 keyword-only"
    assert executor_param.default is inspect.Parameter.empty, (
        "run_cpu_bound 的 executor 有默认值：谁在用哪个池会变成隐式事实（design.md:200-206）"
    )


def test_runner_module_has_no_blocking_sleep_calls() -> None:
    """`core/task_runner.py` 里**没有** `time.sleep` / `time.join` 这类阻塞调用。

    它是"本层只提供机制、不判定重活"的结构证据：把同步阻塞调用写进 `core` 就是
    把"什么算重活"的判断搬进了机制层（而 `design.md:200-206` 把那个判断交给调用方）。
    真正的等待（心跳间隔、轮询节拍）走 `asyncio.sleep` / `stop.wait()`，两者都不是
    `time.*`，故本判据不会误伤它们。

    ## M3 修复点

    本函数原名 `test_claim_probe_placeholder`（一次性探针的残留命名，会让复核者
    误以为它是残留物），末尾还有一条 `assert TaskClaim and InMemoryLockStore`
    ——那是一条**永远为真**的断言，存在的唯一目的是压住未使用的导入。
    现在：改成本名，并**删掉那两个无用导入**（连断言一起删）。
    """
    source = RUNNER_PATH.read_text(encoding="utf-8")
    blocking = [
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"sleep", "join"}
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "time"
    ]
    assert blocking == [], "task_runner.py 里出现了 time.sleep / time.join：本层只提供机制"
