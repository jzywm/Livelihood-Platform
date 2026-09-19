"""`main.py` 组合根的**执行器装配与关停顺序**（Task 4.7 修复轮，第 5 个提交 + 第 4 批加固）。

## 这个文件补的是哪个空白

前几轮的报告一直登记着一条「`main.py` 的装配与关停**没有任何用例**」——
`env != "test"` 那条分支在默认段跑不到（默认段禁连 Redis），而集成段此前**自己构造**
`TaskRunner`、不走 lifespan。于是「装配顺序对不对」「关停顺序对不对」全靠人读代码。
本文件把它变成可执行的判据，含 **A2** 那处修复（执行器死亡时关停块仍须跑完）。

## 怎么让 lifespan 走到"装配"分支（控制者查清的三条事实）

- `core/config.py` 的 `Env = Literal["dev","test","prod"]`、`_NON_PROD_ENVS = {"dev","test"}`、
  只有 **prod + mock** 才被拒 ⇒ **`env="dev"` 就能触发装配**，且不触发布局校验；
- `pyproject.toml` 已注册 `integration` marker（「需要真实 MySQL / Redis……默认不执行」），
  而「默认段 MUST NOT 连 Redis」约束的是**默认段**——本文件的用例带该 marker，
  与它不冲突；
- `conftest.integration_settings()` 默认 `env="test"`（那是给"自建执行器"的用例用的），
  故本文件传 `env="dev"`（该形参是本轮为这个文件加的，默认值不变）。

## 本文件**不需要任何真实凭据**（N6 的修复）

装配与关停顺序与外部的 MySQL / Redis **无关**：三个装配点（`EngineFactory` /
`RedisLockStore` / `TaskRunner`）都被换成了记录版，`RedisLockStore` 的构造**不连接**
（`redis.asyncio.Redis` 惰性），`EngineFactory` 的构造也不连接（`create_engine` 惰性）。
实测：把 MySQL / Redis 都指向死端口，本文件仍然全绿。

故 `DSH_IT_MYSQL_PASSWORD` 缺失时**不再 skip**——那是**假 skip**：
凭据跟这些用例的真实需求无关，而 skip 会让 CI 上显示 "1 passed, 3 skipped"，
**静默砍掉三条行为覆盖**（比 marker 问题更值得修）。

## ⚠ 边界：本文件**不验轮询**（如实登记，MUST NOT 被读成"轮询也验过了"）

`_RecordingRunner.run_forever` **只等 `stop`、不轮询**。让它真轮询会真的去扫真库，
并在 `handlers={}` 下把扫到的任何任务判成 `FAILED`（`5000`）——**那会改动其它用例共用的数据**
（真库当月表里可能有别的用例留下的行）。装配与关停顺序不需要轮询即可判定，
故这里刻意不轮询；「真的会领任务并执行」由 `test_runner_redis.py` 的端到端用例覆盖。

## 所有等待都有界（N7）

「挂死」在 CI 上比「变红」贵一个数量级。本文件的可观测桩都带**有界 deadline**：

- `_RecordingRunner.run_forever` 等 `stop` 的上界是 `_STOP_BUDGET_S`：`stop` 没被 set 时
  它记一条 `run_forever.stop_missing` 后自己退出 ⇒ **删掉 `runner_stop.set()` 变成断言失败**
  （实测修复前：>8 分钟零输出，只能 kill）；
- `_RecordingLockStore.close` 的上界是 `_CLOSE_BUDGET_S`；
- F7 的"退出需要多次让出"用 `loop.call_soon` 串起来的 future 链实现，**不含任何 `asyncio.sleep`**
  （故本文件的 `ai-allow-sleep` 豁免数是 **0**，这一点由
  `tests/structural/test_sleep_exemption_counts.py` 机械核对）。
"""

from __future__ import annotations

import ast
import asyncio
import logging
import os
import types
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from aicore.core.lease import RedisLockStore
from aicore.core.task_runner import TaskRunner
from aicore.repository.session import EngineFactory
from aicore.repository.task_lease_store import SqlTaskLeaseStore
from aicore.service.task.registry import REGISTRY
from tests.conftest import integration_settings

pytestmark = pytest.mark.integration

#: `main.py` 的路径（结构判据要读它的源码）。
MAIN_PATH = Path(__file__).resolve().parents[2] / "src" / "aicore" / "main.py"

#: 关停阶段的可观测事件（按发生顺序追加）。每个用例由 autouse 夹具清空。
_EVENTS: list[str] = []

#: 等 `stop` 的上界（N7）：`stop` 没被 set 时**不许永久等**。
_STOP_BUDGET_S = 2.0
#: `locks.close()` 的上界（N7）：真实 `aclose()` 本应立刻返回，上界只是防"永不返回"。
_CLOSE_BUDGET_S = 5.0
#: `run_forever` 在 `stop` 置位后、记 `run_forever.end` 之前**需要多次让出**的轮数（F7）。
#:
#: 3 轮的来历：把 `await runner_task` 换成 `await asyncio.sleep(0)`（一次让出）时，
#: 关停块会在第 2 轮就走到 `runner.stop()` —— 于是顺序判据**必然**变红。
#: 少于 2 轮则一次让出就可能凑够，判据失效。
_SETTLE_TURNS = 3

#: 死亡**当场**那条日志的独有子串（`main.py::_log_runner_death`）。
#:
#: F6 的修复点：第一版断言用的是 `"异常退出"`，而关停收尾那条日志
#: （`main.py` 的「任务执行器在关停前已**异常退出**：继续执行关停清理」）**也含同一个子串**
#: ⇒ 删掉 done-callback 之后断言照样被满足（复核者实测：仍 4 passed）。
_DEATH_LOG_SUBSTRING = "进程仍然存活"
#: 关停**收尾**那条日志的独有子串（同一文件的关停块）。
_SHUTDOWN_TAIL_SUBSTRING = "关停前已异常退出"


# ---------------------------------------------------------------------------
# 记录版装配点（三个）
# ---------------------------------------------------------------------------
class _RecordingEngineFactory(EngineFactory):
    """包住生产的 `EngineFactory`，只记录 `dispose()`（关停顺序判据要看到它）。"""

    def dispose(self) -> None:
        _EVENTS.append("dispose")
        super().dispose()


class _RecordingLockStore(RedisLockStore):
    """包住生产的 `RedisLockStore`，只记录 `close()`。

    继承真实类而不是造一个替身：`main.py` 里那行 `locks.close()` 要执行的是**真实实现**，
    替身会让"关的是不是真的锁店"变成一句无人验证的话。
    """

    async def close(self) -> None:
        _EVENTS.append("locks.close")
        # 有界（N7）：真实 `aclose()` 立刻返回，上界只用来把"永不返回"变成失败。
        await asyncio.wait_for(super().close(), timeout=_CLOSE_BUDGET_S)


class _RecordingTaskLeaseStore(SqlTaskLeaseStore):
    """记录**组合根传进来的那个 `EngineFactory`**（F12(c)）。

    F12(c) 的判据是「`SqlTaskLeaseStore` 的注入有没有被验过」——第一版一条都没有。
    这里继承真实类（而不是造替身），于是被验的是 `main.py` 里那一行**真实构造**；
    捕获 `engine_factory` 让"它拿的是同一个工厂"成为可断言的事实，
    而不是"它拿了个不是 None 的东西"。
    """

    #: 最近一次构造收到的 `engine_factory`（类属性：用例要在构造之后读它）。
    last_engine_factory: Any = None

    def __init__(self, engine_factory: EngineFactory) -> None:
        type(self).last_engine_factory = engine_factory
        super().__init__(engine_factory)


class _RecordingRunner(TaskRunner):
    """把「起来了 / 退出了 / 被 stop 了」记进事件序列；`run_forever` 只等 `stop`（不轮询）。

    `run_forever.end` 出现在关停序列里 `runner.stop` **之前**，就是
    「**先 `stop.set()`、再 `await runner_task` 且真的等它退出**」这条顺序的证据。

    ## 两处刻意的设计（F7 / N7）

    - **退出需要多次让出**（F7）：`stop` 置位后还要跑完 `_SETTLE_TURNS` 轮的
      `loop.call_soon` future 链才记 `run_forever.end`。第一版是 `await stop.wait()` 之后
      直接收尾——一次 `await asyncio.sleep(0)` 就够它先记下 `end`，于是
      「等执行器真的退出」这件事**没有判据**（复核者实测：把 `await runner_task` 换成
      `await asyncio.sleep(0)` 仍 4 passed，连跑 5 次）。
    - **等 `stop` 有上界**（N7）：`stop` 没被 set 时记 `run_forever.stop_missing` 后退出，
      于是"忘了 `stop.set()`"表现为**断言失败**而不是 CI 挂死。
    """

    async def run_forever(self, *, stop: asyncio.Event) -> None:
        _EVENTS.append("run_forever.start")
        try:
            try:
                await asyncio.wait_for(stop.wait(), timeout=_STOP_BUDGET_S)
            except TimeoutError:
                _EVENTS.append("run_forever.stop_missing")
            await self._settle_after_stop()
        finally:
            _EVENTS.append("run_forever.end")

    @staticmethod
    async def _settle_after_stop() -> None:
        """让出 `_SETTLE_TURNS` 次事件循环（**不用 `asyncio.sleep`**，故不需要豁免）。"""
        loop = asyncio.get_running_loop()
        for _ in range(_SETTLE_TURNS):
            gate: asyncio.Future[None] = loop.create_future()
            loop.call_soon(gate.set_result, None)
            await gate

    async def stop(self) -> None:
        _EVENTS.append("runner.stop")
        await super().stop()


class _ExplodingRunner(_RecordingRunner):
    """**A2 的判据**：`run_forever` 以**异常**结束（模拟"执行器死了、进程还活着"）。

    修复前的关停块是裸 `await runner_task`：这里抛出的异常会让
    `runner.stop()` / `locks.close()` / `dispose()` **全部被跳过**。
    """

    async def run_forever(self, *, stop: asyncio.Event) -> None:
        _EVENTS.append("run_forever.raise")
        raise RuntimeError("模拟执行器异常死亡（A2 的关停块判据）")


@pytest.fixture(autouse=True)
def _reset_events() -> Iterator[None]:
    """每个用例一份干净的事件序列（模块级可变状态必须逐用例清）。"""
    _EVENTS.clear()
    _RecordingTaskLeaseStore.last_engine_factory = None
    yield
    _EVENTS.clear()


# ---------------------------------------------------------------------------
# `Settings`：**不需要任何真实凭据**（N6）
# ---------------------------------------------------------------------------
#: 未配置真实口令时用的占位符。它**不会被用来连接任何东西**（本文件的三个装配点全被替换），
#: 只是为了让 `Settings` 能解析出来。
_PLACEHOLDER_PASSWORD = "assembly-test-placeholder"


def _assembly_settings(env: str, **overrides: Any) -> Any:
    """本文件要的 `Settings`：`DSH_IT_MYSQL_PASSWORD` 缺失时**用占位符**，不 skip。

    N6 的修复：第一版在缺凭据时 `pytest.skip`，而这三条用例**一条外部依赖都不需要**
    （死端口下仍 4 passed 已证）⇒ 那是**假 skip**：凭据缺失时覆盖被静默砍掉，
    CI 上只显示 "1 passed, 3 skipped"。判据必须与用例的**真实需求**对齐。

    `overrides` 用来造**彼此不同**的取值（F12(b)）：只有三个值互不相同时，
    「`lease_ms` 与 `concurrency_limit` 装配反了」这类错误才可能被看见。
    """
    injected = "DSH_IT_MYSQL_PASSWORD" not in os.environ
    if injected:
        os.environ["DSH_IT_MYSQL_PASSWORD"] = _PLACEHOLDER_PASSWORD
    try:
        settings = integration_settings(env=env)
    finally:
        if injected:
            del os.environ["DSH_IT_MYSQL_PASSWORD"]
    if not overrides:
        return settings
    # `model_copy` 不做校验，故这里先 dump 再重新构造：overrides 也走一遍校验，
    # 免得"测试自己造了一个生产不接受的值"。
    return type(settings)(**{**settings.model_dump(), **overrides})


@contextmanager
def _mutant_main(*patches: tuple[str, str]) -> Iterator[Any]:
    """把 `main.py` 的源码在**内存里**改若干处，产出一个变异模块（**文件从不被写**）。

    与 `test_task_runner.py::_mutant_runner_class` 同一取向（工单纪律：
    MUST NOT「改 `src/` + `finally` 还原」——那条路一旦被打断就把变异体留在工作树里）。
    """
    source = MAIN_PATH.read_text(encoding="utf-8")
    for anchor, replacement in patches:
        count = source.count(anchor)
        assert count == 1, (
            f"变异锚点在 main.py 里出现 {count} 次（要求恰好 1 次）：{anchor!r}——"
            f"锚点漂了就必须先修锚点，MUST NOT 让它静默变成'什么都没变'"
        )
        source = source.replace(anchor, replacement)
    module = types.ModuleType("dsh_mutant_main")
    module.__file__ = str(MAIN_PATH)
    exec(compile(source, str(MAIN_PATH), "exec"), module.__dict__)
    yield module


@contextmanager
def _lifespan_app(
    monkeypatch: pytest.MonkeyPatch,
    *,
    env: str,
    runner_cls: type[TaskRunner] = _RecordingRunner,
    mutant: Any = None,
    settings: Any = None,
) -> Iterator[Any]:
    """经**真组合根**跑一次完整 lifespan（启动 → 关闭），把装配点换成记录版。

    替换的是 `aicore.main` 里的**名字**（组合根的装配点），不是 patch 某个内部函数：
    装配点是公开契约的一部分，替换它等价于替换部署形态，而 lifespan 的**行为**（顺序、
    判据分支）一个字节都不改——那正是本文件要验的东西。

    `mutant` 非 `None` 时用**变异模块的** `lifespan`（F7 的判别力自证）：
    变异模块的装配点名也一并换成记录版（它引用的是它自己的全局命名空间）。
    """
    from fastapi.testclient import TestClient

    from aicore.main import create_app

    resolved = _assembly_settings(env) if settings is None else settings
    monkeypatch.setattr("aicore.main.get_settings", lambda: resolved)
    monkeypatch.setattr("aicore.main.EngineFactory", _RecordingEngineFactory)
    monkeypatch.setattr("aicore.main.RedisLockStore", _RecordingLockStore)
    monkeypatch.setattr("aicore.main.TaskRunner", runner_cls)
    monkeypatch.setattr("aicore.main.SqlTaskLeaseStore", _RecordingTaskLeaseStore)
    # F12(a)：`flush_logging()` 此前**完全不可观测**（删掉它 / 提前调用都 4 passed）。
    # 换成记录版即可把"它跑了、而且跑在最后"变成判据。
    monkeypatch.setattr("aicore.main.flush_logging", lambda: _EVENTS.append("flush_logging"))
    if mutant is not None:
        monkeypatch.setattr("aicore.main.lifespan", mutant.lifespan)
        mutant.get_settings = lambda: resolved
        mutant.EngineFactory = _RecordingEngineFactory
        mutant.RedisLockStore = _RecordingLockStore
        mutant.TaskRunner = runner_cls
        mutant.SqlTaskLeaseStore = _RecordingTaskLeaseStore
        mutant.flush_logging = lambda: _EVENTS.append("flush_logging")

    app = create_app()
    with TestClient(app) as client:
        yield app, client


# ---------------------------------------------------------------------------
# F6：死亡日志的**断言助手**（同一份助手喂给合成记录序列，验证它能判红）
# ---------------------------------------------------------------------------
def _death_log_indexes(records: Sequence[logging.LogRecord]) -> list[int]:
    """死亡**当场**那条日志在记录序列里的下标（`_DEATH_LOG_SUBSTRING` 是它的独有子串）。"""
    return [
        index
        for index, record in enumerate(records)
        if record.name == "aicore.main" and _DEATH_LOG_SUBSTRING in record.getMessage()
    ]


def _shutdown_tail_indexes(records: Sequence[logging.LogRecord]) -> list[int]:
    """关停**收尾**那条日志的下标（`_SHUTDOWN_TAIL_SUBSTRING` 是它的独有子串）。"""
    return [
        index
        for index, record in enumerate(records)
        if record.name == "aicore.main" and _SHUTDOWN_TAIL_SUBSTRING in record.getMessage()
    ]


def _assert_death_logged_before_shutdown_tail(records: Sequence[logging.LogRecord]) -> None:
    """**F6 的判据本体**：死亡当场那条日志存在，且**早于**关停收尾那条。

    抽成函数是为了让判别力自证把**合成的记录序列**喂给它（同一份判据），
    而不是让自证复制一份判据——复制出来的判据与真判据会各自漂移。

    两条断言缺一不可：

    1. **存在**（且用独有子串）：`"异常退出"` 这类子串被关停收尾那条日志共用，
       拿它做判据等于**没有任何判据**（删掉 done-callback 也能满足）；
    2. **顺序**：死亡当场**必然**早于关停收尾（前者发生在 `run_forever` 结束的那一刻，
       后者发生在 lifespan 的关停块里）。只断言"都出现过"的话，
       "只有关停收尾那条"与"两条都有"仍然无法区分——而前者正是缺 done-callback 的形态。
    """
    death = _death_log_indexes(records)
    tail = _shutdown_tail_indexes(records)
    assert death, (
        f"没有死亡**当场**那条日志（独有子串 {_DEATH_LOG_SUBSTRING!r}）："
        f"执行器异常死亡时进程存续期间一行日志都没有——最坏形态是"
        f"「进程活着、执行器已死、零信号」。实际记录："
        f"{[r.getMessage()[:60] for r in records]}"
    )
    assert tail, (
        f"没有关停**收尾**那条日志（独有子串 {_SHUTDOWN_TAIL_SUBSTRING!r}）："
        f"关停块似乎没走到——本判据的前提不成立"
    )
    assert death[0] < tail[0], (
        f"死亡日志（下标 {death[0]}）不早于关停收尾日志（下标 {tail[0]}）："
        f"死亡当场没有记日志，只有关停时才补记——那正是缺少 done-callback 的形态"
    )


def _synthetic_record(message: str, *, level: int = logging.ERROR) -> logging.LogRecord:
    """造一条 `aicore.main` 的记录（只用于 F6 的判别力自证）。

    `logging.LogRecord` 的构造参数很多且与日志内容无关，故集中在一处；
    这样"合成序列"与真实 `caplog.records` 在助手眼里是**同一种东西**。
    """
    return logging.LogRecord(
        name="aicore.main",
        level=level,
        pathname=str(MAIN_PATH),
        lineno=0,
        msg=message,
        args=(),
        exc_info=None,
    )


def test_death_log_criterion_discriminates() -> None:
    """**F6 的判别力自证**：只含"关停收尾"那条日志的序列，喂给同一助手**必须判红**。

    这正是复核者用来证明"断言是空的"那个实验的离线版本：删掉
    `add_done_callback(_log_runner_death)` 之后，记录序列里**只剩**关停收尾那一行
    （因为 `main.py` 的关停块自己也会记一条）。第一版的断言用共享子串 `"异常退出"`，
    于是它照样通过。

    本用例断言两件事：
    1. 合成序列（只有关停收尾）⇒ 助手抛 `AssertionError`（**能判红**）；
    2. 合成序列（两条都在、顺序正确）⇒ 助手通过（**不是"一律判红"**）。
    """
    tail_only = [_synthetic_record("任务执行器在关停前已异常退出：继续执行关停清理")]
    with pytest.raises(AssertionError, match="没有死亡\\*\\*当场\\*\\*那条日志"):
        _assert_death_logged_before_shutdown_tail(tail_only)

    # 顺序反了也必须红（"都出现过"不等于"死亡在关停之前记的"）。
    reversed_order = [
        _synthetic_record("任务执行器在关停前已异常退出：继续执行关停清理"),
        _synthetic_record("任务执行器协程异常退出：进程仍然存活，但**不会再领取任何任务**"),
    ]
    with pytest.raises(AssertionError, match="不早于关停收尾日志"):
        _assert_death_logged_before_shutdown_tail(reversed_order)

    # 阳性对照：顺序正确时助手通过 —— 否则上面两条可能是"助手一律抛错"。
    _assert_death_logged_before_shutdown_tail(list(reversed(reversed_order)))


# ---------------------------------------------------------------------------
# 行为用例
# ---------------------------------------------------------------------------
def test_lifespan_does_not_assemble_the_runner_in_test_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """① `env == "test"` 时**不装配**执行器（工单 §2.7 的闸门）。

    断言两半：

    - `app.state` 上**没有** `task_runner`（`hasattr` 判据：Starlette 的 `State.__getattr__`
      缺属性即抛，故"没挂上"是可判定的）；
    - 关停序列里**只有 `dispose` 与 `flush_logging`**：没有 `run_forever`、没有 `locks.close()`。
      这一半更严——它同时排除了"装配了但没挂到 state 上"这种形态。

    `dispose` 仍在（它是 `engine_factory` 的清理，与执行器那个 `if` 无关）：
    连接池的释放在**任何 env** 下都必须发生。
    """
    with _lifespan_app(monkeypatch, env="test") as (app, _client):
        assert not hasattr(app.state, "task_runner"), (
            "env=test 时装配了执行器：每个用 TestClient 的用例都会去连 Redis"
            "（默认段的离线保证会被破坏）"
        )

    assert _EVENTS == ["dispose", "flush_logging"], (
        f"env=test 的关停序列应为 ['dispose', 'flush_logging']（只有连接池释放 + 刷日志），"
        f"实际 {_EVENTS}"
    )


def test_lifespan_assembles_and_stops_in_order_outside_test_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """②③④⑥ `env="dev"` 时装配、注入空 handler / 整张策略表 / 从 `Settings` 取值，
    并按**固定顺序**关停。

    ② 装配点挂上且非 `None`；
    ③ `handlers={}`（M1 的事实，工单 §2.8）+ `policies=dict(REGISTRY)`（组合根注入）；
    ⑥ **`RunnerConfig` 的三个值来自 `Settings`**（F12(b)：此前把 `lease_ms` 与
      `max_retries` 在装配处对调也 4 passed）；取值**两两不同**，故"装配反了"可被判红；
    ④ 关停顺序：
      `stop.set() → await runner_task（真的等它退出）→ runner.stop()`
      `→ locks.close() → dispose() → flush_logging()`
      ——由事件序列**逐项**钉住。`run_forever.end` 出现在 `runner.stop` **之前**，
      是"等到了执行器退出"的证据（退出需要多轮让出，见 `_RecordingRunner`）。
    """
    # 三个值**两两不同**，且都与 `Settings` 的默认值不同：任何一处装反都会被看见。
    settings = _assembly_settings(env="dev", lease_ms=1234, max_retries=7, concurrency_limit=3)
    with _lifespan_app(monkeypatch, env="dev", settings=settings) as (app, client):
        # **发一条真请求来推进事件循环**：`asyncio.create_task(run_forever(...))` 只是**排期**，
        # 被排的协程不保证在 `TestClient.__enter__` 返回前就跑过。
        # 不推进就断言 `_EVENTS` 会变成"偶发为空"的时序赌注（本用例第一版就有这个隐患）。
        # `/health` 不碰库、不碰 Redis，是这里最便宜的推进手段。
        assert client.get("/health").status_code == 200
        runner = app.state.task_runner
        assert runner is not None, "env=dev 时必须装配执行器并挂到 app.state.task_runner"
        assert isinstance(runner, _RecordingRunner), (
            f"装配出来的不是组合根里那一行构造的类：{type(runner).__name__}"
        )
        # ③ handlers={}：M1 的现状（`service/ocr_service.py` 仍是空壳）
        assert runner.registered_handlers == (), (
            f"装配时注入了处理器 {runner.registered_handlers}：M1 的注册表此刻解析不出任何处理器，"
            f"MUST NOT 用假处理器填满它（工单 §2.8）"
        )
        # ③ policies=dict(REGISTRY)：键集合必须**恰好**等于注册表
        assert set(runner.registered_policy_types) == set(REGISTRY), (
            f"注入的策略表与注册表不一致："
            f"{sorted(runner.registered_policy_types)} vs {sorted(REGISTRY)}"
        )
        # ⑥ 配置逐项来自 Settings（F12(b)）
        assert runner.config.lease_ms == settings.lease_ms == 1234, (
            f"装配进去的 lease_ms 是 {runner.config.lease_ms}，Settings 里是 {settings.lease_ms}"
        )
        assert runner.config.max_retries == settings.max_retries == 7, (
            f"装配进去的 max_retries 是 {runner.config.max_retries}，"
            f"Settings 里是 {settings.max_retries}"
        )
        assert runner.config.concurrency_limit == settings.concurrency_limit == 3, (
            f"装配进去的 concurrency_limit 是 {runner.config.concurrency_limit}，"
            f"Settings 里是 {settings.concurrency_limit}"
        )
        # ⑥(F12c) 租约存储的注入：拿的是**组合根自己建的那个 engine_factory**
        assert _RecordingTaskLeaseStore.last_engine_factory is app.state.engine_factory, (
            "`SqlTaskLeaseStore` 拿到的不是组合根自己那个 `engine_factory`："
            "存储层与连接池会各自持有不同的池（关停时只会释放其中一个）"
        )
        assert app.state.engine_factory is not None
        # 装配完成后：只有执行器起来了，清理都还没发生
        assert _EVENTS == ["run_forever.start"], (
            f"关停清理在启动阶段就跑了？实际 {_EVENTS}"
        )

    _assert_shutdown_order(_EVENTS)


def _assert_shutdown_order(events: Sequence[str]) -> None:
    """**关停顺序的判据本体**（生产用例与 F7 的变异体自证**共用同一份**）。

    顺序是硬要求（工单 §2.7）：先 `stop.set()`、**等执行器真的退出**，再关 Redis，
    最后释放连接池与刷日志。反过来的话，在跑任务的续期会失败——那会被执行器判成
    「租约已失去」而**主动放弃**（`design.md:208` 的语义），表现为一串"无故放弃"的告警，
    而真正的原因是我们先拔了 Redis。

    `run_forever.end` 的位置是**F7 的关键**：它必须在 `runner.stop` **之前**出现，
    否则说明关停块并没有等执行器退出（`await runner_task` 被换成了"让出一次"之类）。
    """
    assert list(events) == [
        "run_forever.start",
        "run_forever.end",  # ← stop 已 set，且 `await runner_task` **真的等到了它退出**
        "runner.stop",
        "locks.close",
        "dispose",
        "flush_logging",  # ← F12(a)：最后一步，且 MUST 在最后
    ], (
        f"关停顺序不对：{list(events)}。硬要求是"
        f"「先 set stop、await 执行器退出，**再**关 Redis，最后释放连接池并刷日志」——"
        f"先关 Redis 会让在跑任务的续期失败，被执行器判成『租约已失去』而主动放弃；"
        f"而 `run_forever.end` 若出现在 `runner.stop` 之后，说明关停**没有等**执行器退出"
        f"（F7 的失效形态）"
    )


def test_f7_shutdown_order_guard_discriminates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """**F7 的判别力自证**：把 `await runner_task` 换成 `await asyncio.sleep(0)`，
    **同一份顺序判据** `_assert_shutdown_order` **必须变红**。

    内存变异（**文件从不被写**）：只用一次让出代替"等执行器退出"。
    复核者当初就是这么证明"这个 join 没有判据"的（连跑 5 次仍 4 passed）。

    变异为什么现在会红：`_RecordingRunner` 在 `stop` 置位后还需要 `_SETTLE_TURNS`
    轮才记 `run_forever.end`，而关停块在一次让出之后就走到 `runner.stop()` ⇒
    `runner.stop` 抢在 `run_forever.end` 前面（或者 `run_forever.end` 干脆赶不上断言）。
    """
    with _mutant_main(
        ("            await runner_task\n", "            await asyncio.sleep(0)\n"),
    ) as mutant, _lifespan_app(monkeypatch, env="dev", mutant=mutant) as (_app, client):
        assert client.get("/health").status_code == 200

    with pytest.raises(AssertionError, match="关停顺序不对"):
        _assert_shutdown_order(_EVENTS)


def test_shutdown_cleanup_completes_even_if_the_runner_died(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """**⑤ A2 的判据**：执行器以异常结束后，关停块**仍然跑完**全部清理。

    修复前是裸 `await runner_task`：死亡原因会从那句抛出，
    于是 `runner.stop()` / `locks.close()` / `dispose()` **全部被跳过**
    （评审实测：关停块里执行到的清理步骤 = `[]`）。
    「另一个组件死过」不该让资源清理整体不做。

    同时断言**死亡有日志、且死亡当场就记了**：`create_task` 的异常在有人 retrieve
    之前是沉默的，而 `runner_task` 正常情况下要到关停才被 await ⇒ 没有 done-callback 的话，
    「进程活着、执行器已死」在整个进程存续期间**一行日志都没有**。

    **F6 的修复点**：判据是 `_assert_death_logged_before_shutdown_tail(caplog.records)` ——
    用**独有子串 + 顺序**，而不是第一版那个与关停收尾日志共用的 `"异常退出"`。
    """
    with (
        caplog.at_level(logging.ERROR, logger="aicore.main"),
        _lifespan_app(monkeypatch, env="dev", runner_cls=_ExplodingRunner) as (app, client),
    ):
        # 推进事件循环（同上一用例的理由）：死亡发生在被排期的协程里。
        assert client.get("/health").status_code == 200
        assert app.state.task_runner is not None, (
            "装配点必须已挂上（否则本用例测不到关停块）"
        )

    assert _EVENTS == [
        "run_forever.raise",
        "runner.stop",  # ← 死亡之后这三步**必须仍然发生**
        "locks.close",
        "dispose",
        "flush_logging",
    ], f"执行器死亡后关停清理被跳过了：{_EVENTS}"
    # F6：死亡当场那条日志必须存在，且早于关停收尾那条（同一份判据也喂给了合成序列）。
    _assert_death_logged_before_shutdown_tail(caplog.records)


def test_n7_missing_stop_becomes_a_failure_instead_of_a_hang(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """**N7 的判据 + 判别力自证**：`stop` 没被 set 时**变红**，而不是把 CI 挂住。

    复核者的实测：删掉 `main.py` 的 `runner_stop.set()`，后台跑 **>8 分钟零输出**，
    只能 `job_kill`——因为关停块里的 `await runner_task` 会**永远等**下去。
    「挂死」在 CI 上比「变红」贵一个数量级（它烧的是流水线的墙钟预算，而且没有诊断信息）。

    修法在**可观测桩**这一侧：`_RecordingRunner.run_forever` 等 `stop` 有 `_STOP_BUDGET_S`
    的上界，超界记 `run_forever.stop_missing` 后自己退出 ⇒ 事件序列多出一项、
    `_assert_shutdown_order` 当场判红。

    本用例即那次删除的**内存版本**（文件从不被写），并断言两件事：
    ① 判据变红；② 它是在**有界**时间内红的（与"挂死"区分开）。
    """
    import time

    with _mutant_main(("        runner_stop.set()\n", "")) as mutant:
        started = time.monotonic()
        with _lifespan_app(monkeypatch, env="dev", mutant=mutant) as (_app, client):
            assert client.get("/health").status_code == 200
        elapsed = time.monotonic() - started

    with pytest.raises(AssertionError, match="关停顺序不对"):
        _assert_shutdown_order(_EVENTS)
    assert "run_forever.stop_missing" in _EVENTS, (
        f"变异体（缺 `stop.set()`）没有走『等不到 stop』那条有界出口：{_EVENTS}——"
        f"那说明它靠别的方式退出了，本判据证明的不是这件事"
    )
    assert elapsed < _STOP_BUDGET_S * 5, (
        f"变异体花了 {elapsed:.1f}s 才收场：它仍然在无界地等（N7 的失效形态就是挂死）"
    )


def test_shutdown_block_guards_the_runner_await() -> None:
    """④⑤ 的**结构判据**：关停块里 `await runner_task` MUST 被 `try/except` 包住（A2）。

    **行为判据为主、AST 判据为辅（F11）**：行为判据是
    `test_shutdown_cleanup_completes_even_if_the_runner_died`（死亡时清理真的跑完）
    与 `test_f7_shutdown_order_guard_discriminates`（不等执行器退出就红）。
    这一条只是**补充**，它有两个已知弱点，如实登记：

    - **可以被仍然错的代码满足**：把 `await runner_task` 放进一个与关停无关的 `try` 里、
      或者 `except` 里只有一句无意义的 `pass  # noqa`，它都会通过；
    - **对等价的正确写法可能误报**：例如把 join 抽成辅助函数
      （`await self._join(runner_task)`）之后，本判据找不到 `await runner_task` 会**报错**，
      尽管行为完全正确。

    那为什么还留着：它在回归时会**直白地指出缺的是哪一个结构**，而行为判据只会说
    "事件序列缺三项"。两条判据的守备范围不同，不是重复。

    `except` 分支 MUST NOT 只是 `raise`（那样等于没兜）：判据要求它**至少有一个语句**，
    且该语句不是裸 `raise`。
    """
    lifespan = next(
        node
        for node in ast.walk(ast.parse(MAIN_PATH.read_text(encoding="utf-8")))
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "lifespan"
    )
    awaits = [
        node
        for node in ast.walk(lifespan)
        if isinstance(node, ast.Await)
        and isinstance(node.value, ast.Name)
        and node.value.id == "runner_task"
    ]
    assert awaits, f"{MAIN_PATH.name} 的 lifespan 里找不到 `await runner_task`：判据失去对象"
    guards = [
        node
        for node in ast.walk(lifespan)
        if isinstance(node, ast.Try) and any(inner in set(ast.walk(node)) for inner in awaits)
    ]
    assert guards, (
        "`await runner_task` 不在任何 try 块里：执行器异常死亡时，"
        "`runner.stop()` / `locks.close()` / `dispose()` / `flush_logging()` 会**全部被跳过**（A2）"
    )
    swallowing = [
        handler
        for guard in guards
        for handler in guard.handlers
        if any(not isinstance(stmt, ast.Raise) for stmt in handler.body)
    ]
    assert swallowing, (
        "关停块里的 `except` 只有裸 `raise`（等于没兜）：异常照样会跳过全部清理"
    )
