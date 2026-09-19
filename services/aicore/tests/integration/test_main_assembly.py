"""`main.py` 组合根的**执行器装配与关停顺序**（Task 4.7 修复轮，第 5 个提交）。

## 这个文件补的是哪个空白

前几轮的报告一直登记着一条「`main.py` 的装配与关停**没有任何用例**」——
`env != "test"` 那条分支在默认段跑不到（默认段禁连 Redis），而集成段此前**自己构造**
`TaskRunner`、不走 lifespan。于是「装配顺序对不对」「关停顺序对不对」全靠人读代码。
本文件把它变成可执行的判据，含 **A2** 那处修复（执行器死亡时关停块仍须跑完）。

## 怎么让 lifespan 走到"装配"分支（控制者查清的三条事实）

- `core/config.py:80` 的 `Env = Literal["dev","test","prod"]`、`:86` 的
  `_NON_PROD_ENVS = {"dev","test"}`、`:23` 只有 **prod + mock** 才被拒
  ⇒ **`env="dev"` 就能触发装配**，且不触发布局校验；
- `pyproject.toml:97` 已注册 `integration` marker（「需要真实 MySQL / Redis……默认不执行」），
  而「默认段 MUST NOT 连 Redis」约束的是**默认段**——本文件的用例带该 marker，
  与它不冲突；
- `conftest.integration_settings()` 默认 `env="test"`（那是给"自建执行器"的用例用的），
  故本文件传 `env="dev"`（该形参是本轮为这个文件加的，默认值不变）。

## ⚠ 边界：本文件**不验轮询**（如实登记，MUST NOT 被读成"轮询也验过了"）

`_RecordingRunner.run_forever` **只等 `stop`、不轮询**。让它真轮询会真的去扫真库，
并在 `handlers={}` 下把扫到的任何任务判成 `FAILED`（`5000`）——**那会改动其它用例共用的数据**
（真库当月表里可能有别的用例留下的行）。装配与关停顺序不需要轮询即可判定，
故这里刻意不轮询；「真的会领任务并执行」由 `test_runner_redis.py` 的端到端用例覆盖。
"""

from __future__ import annotations

import ast
import asyncio
import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from aicore.core.lease import RedisLockStore
from aicore.core.task_runner import TaskRunner
from aicore.repository.session import EngineFactory
from aicore.service.task.registry import REGISTRY
from tests.conftest import integration_settings

pytestmark = pytest.mark.integration

#: `main.py` 的路径（结构判据要读它的源码）。
MAIN_PATH = Path(__file__).resolve().parents[2] / "src" / "aicore" / "main.py"

#: 关停阶段的可观测事件（按发生顺序追加）。每个用例由 autouse 夹具清空。
_EVENTS: list[str] = []


def _require_integration_settings(env: str) -> Any:
    """取一份集成用的 `Settings`；没配凭据 → **显式 skip 并说明**（不静默通过）。

    `integration_settings()` 直接读 `DSH_IT_MYSQL_PASSWORD`（`os.environ[...]`），
    没配时是 `KeyError` 而不是 skip —— 故这里先探测，与 `integration_engine_factory` 同口径。
    """
    if not os.environ.get("DSH_IT_MYSQL_PASSWORD"):
        pytest.skip(
            "未配置 DSH_IT_MYSQL_PASSWORD（或 .env 里的 AICORE_MYSQL_PASSWORD）："
            "本用例经真组合根装配，需要一份可解析的 Settings"
        )
    return integration_settings(env=env)


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
        await super().close()


class _RecordingRunner(TaskRunner):
    """把「起来了 / 退出了 / 被 stop 了」记进事件序列；`run_forever` 只等 `stop`（不轮询）。

    `run_forever.end` 出现在关停序列里，就是「**先 `stop.set()`、再 `await runner_task`**」
    这条顺序的证据：这个空转的 `run_forever` **只可能**因 `stop` 被置位而返回
    （`stop.set()` 本身不在本进程外可观测，故用它作为代理判据——这点如实写明）。
    """

    async def run_forever(self, *, stop: asyncio.Event) -> None:
        _EVENTS.append("run_forever.start")
        try:
            await stop.wait()
        finally:
            _EVENTS.append("run_forever.end")

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
    yield
    _EVENTS.clear()


@contextmanager
def _lifespan_app(
    monkeypatch: pytest.MonkeyPatch, *, env: str, runner_cls: type[TaskRunner] = _RecordingRunner
) -> Iterator[Any]:
    """经**真组合根**跑一次完整 lifespan（启动 → 关闭），把三个装配点换成记录版。

    替换的是 `aicore.main` 里的**名字**（组合根的装配点），不是 patch 某个内部函数：
    装配点是公开契约的一部分，替换它等价于替换部署形态，而 lifespan 的**行为**（顺序、
    判据分支）一个字节都不改——那正是本文件要验的东西。
    """
    from fastapi.testclient import TestClient

    from aicore.main import create_app

    settings = _require_integration_settings(env)
    monkeypatch.setattr("aicore.main.get_settings", lambda: settings)
    monkeypatch.setattr("aicore.main.EngineFactory", _RecordingEngineFactory)
    monkeypatch.setattr("aicore.main.RedisLockStore", _RecordingLockStore)
    monkeypatch.setattr("aicore.main.TaskRunner", runner_cls)

    app = create_app()
    with TestClient(app) as client:
        yield app, client


def test_lifespan_does_not_assemble_the_runner_in_test_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """① `env == "test"` 时**不装配**执行器（工单 §2.7 的闸门）。

    断言两半：

    - `app.state` 上**没有** `task_runner`（`hasattr` 判据：Starlette 的 `State.__getattr__`
      缺属性即抛，故"没挂上"是可判定的）；
    - 关停序列里**只有 `dispose`**：没有 `run_forever`、没有 `locks.close()`。
      这一半更严——它同时排除了"装配了但没挂到 state 上"这种形态。

    `dispose` 仍在（它是 `engine_factory` 的清理，与执行器那个 `if` 无关）：
    连接池的释放在**任何 env** 下都必须发生。
    """
    with _lifespan_app(monkeypatch, env="test") as (app, _client):
        assert not hasattr(app.state, "task_runner"), (
            "env=test 时装配了执行器：每个用 TestClient 的用例都会去连 Redis"
            "（默认段的离线保证会被破坏）"
        )

    assert _EVENTS == ["dispose"], (
        f"env=test 的关停序列应为 ['dispose']（只有连接池释放），实际 {_EVENTS}"
    )


def test_lifespan_assembles_and_stops_in_order_outside_test_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """②③④ `env="dev"` 时装配、注入空 handler 与整张策略表、并按**固定顺序**关停。

    ② 装配点挂上且非 `None`；
    ③ `handlers={}`（M1 的事实，工单 §2.8）+ `policies=dict(REGISTRY)`（组合根注入）；
    ④ 关停顺序 `stop.set() → await runner_task → runner.stop() → locks.close() → dispose()`
       ——由事件序列**逐项**钉住（`run_forever.end` 是"`stop` 已 set 且执行器已退出"的证据）。
    """
    with _lifespan_app(monkeypatch, env="dev") as (app, client):
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
        # 装配完成后：只有执行器起来了，清理都还没发生
        assert _EVENTS == ["run_forever.start"], (
            f"关停清理在启动阶段就跑了？实际 {_EVENTS}"
        )

    assert _EVENTS == [
        "run_forever.start",
        "run_forever.end",  # ← stop 已 set，且 `await runner_task` 已完成
        "runner.stop",
        "locks.close",
        "dispose",
    ], (
        f"关停顺序不对：{_EVENTS}。硬要求是"
        f"「先 set stop、await 执行器退出，**再**关 Redis、最后释放连接池」——"
        f"先关 Redis 会让在跑任务的续期失败，被执行器判成『租约已失去』而主动放弃"
        f"（表现为一串「无故放弃」的告警，而真正的原因是我们先拔了 Redis）"
    )


def test_shutdown_cleanup_completes_even_if_the_runner_died(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """**⑤ A2 的判据**：执行器以异常结束后，关停块**仍然跑完**全部清理。

    修复前是裸 `await runner_task`：死亡原因会从那句抛出，
    于是 `runner.stop()` / `locks.close()` / `dispose()` **全部被跳过**
    （评审实测：关停块里执行到的清理步骤 = `[]`）。
    「另一个组件死过」不该让资源清理整体不做。

    同时断言**死亡有日志**：`create_task` 的异常在有人 retrieve 之前是沉默的，
    而 `runner_task` 正常情况下要到关停才被 await ⇒ 没有 done-callback 的话，
    「进程活着、执行器已死」在整个进程存续期间**一行日志都没有**。
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
    ], f"执行器死亡后关停清理被跳过了：{_EVENTS}"
    assert "异常退出" in caplog.text or "不会再领取任何任务" in caplog.text, (
        f"执行器异常死亡没有留下 ERROR 日志：{caplog.text!r}"
        f"（最坏形态是「进程活着、执行器已死、零信号」）"
    )


def test_shutdown_block_guards_the_runner_await() -> None:
    """④⑤ 的**结构判据**：关停块里 `await runner_task` MUST 被 `try/except` 包住（A2）。

    行为判据是上一条（它在修复前后的差别是"清理跑没跑完"）。这一条从**源码侧**再钉一遍，
    两条各自的守备范围不同：

    - 行为判据证明"死亡时清理真的跑完了"——它是最强的判据；
    - 结构判据钉住"为什么能跑完"（`await` 在 try 里），并且**判得更直白**：
      行为判据在回归时会以"`_EVENTS` 缺三项"或"`TestClient.__exit__` 把异常抛回来"
      两种形态变红，而这条直接指出缺的是哪一个结构。

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
