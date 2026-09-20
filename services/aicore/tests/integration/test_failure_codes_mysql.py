"""`4003` / `5002` **分别落库**与"降级不阻塞受理"的真 MySQL 判据（Task 4.11 §3）。

## 本文件补的是哪几条

| 工单 §3 | 判据 |
|---|---|
| 1 两码不混用 | `test_two_failure_codes_land_separately_on_the_real_db`：两行的码各自正确、互不串 |
| 2 分别计数 | 同一条用例里的 `WHERE status='FAILED' GROUP BY error_code` ⇒ `{4003: 1, 5002: 1}` |
| 3 降级不阻塞核心业务 | `test_channel_downtime_...`：通道真不可用期间，提交仍 `202` + `taskId` |
| 4 两条异常路径分别触发 | 两条用例都用**真实 mock 通道的故障注入**产生两码，由**真执行器**写回 |

## 为什么故障用 `MockFault` 而不是"处理器里 `raise ChannelFailureError(...)`"

`provider/mock.py` 的 `MockFault` 就是为此准备的（其 docstring 逐字给出可核点：
`kind="timeout"` ⇒ `exc.code == 5002`、`kind="error"` ⇒ `exc.code == 4003`），
故**不需要改 `provider/`**（工单 §4："若已由 mock 支持则不改"）。
用它产生的异常是**通道层真实抛的**（`ProviderChannelFailureError` / `ProviderTimeoutError`
多重继承自 `ChannelFailureError` / `DependencyTimeoutError`），执行器取的是异常自带的
`AiCoreError.code`（Task 4.7 已实现：**MUST NOT 由执行器猜**）⇒ 这条链路的两端都是生产代码。

## 数据卫生

本文件用自己的账号 `ACCOUNT_ID`，前置与收尾各删一次本月表里属于它的行
（与 `test_runner_redis.py::_purge_stale_tasks` 同口径；不碰别人的行）。
演练月 = **当前月**（提交侧用墙钟算月；理由见 `test_runner_redis.py::DRILL_MONTH`）。
"""

from __future__ import annotations

import sys
import types
import uuid
from collections.abc import Iterator, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from aicore.api.deps import ACCOUNT_ID_HEADER
from aicore.core.lease import RedisLockStore
from aicore.core.task_runner import ClaimedTask, RunnerConfig, TaskRunner
from aicore.provider.errors import ProviderChannelFailureError, ProviderTimeoutError
from aicore.provider.mock import MockFault, MockOcrProvider, MockScript
from aicore.repository.base import physical_table
from aicore.repository.models import AiTask
from aicore.repository.session import EngineFactory
from aicore.repository.sharding import ensure_month_tables
from aicore.repository.task_lease_store import SqlTaskLeaseStore
from aicore.repository.task_repo import TaskRepo
from aicore.service.task.registry import REGISTRY
from tests.conftest import integration_settings

pytestmark = pytest.mark.integration

#: 本文件专属账号（清理与断言都按它取范围）。
ACCOUNT_ID = "acc_it_codes_4_11"
TASK_TYPE = "OCR"
IMAGE_KEY = "cert/oss/it/4_11/codes.jpg"
DOC_TYPE = "BUSINESS_LICENSE"

_RUN_NOW = datetime.now(UTC)
DRILL_MONTH = f"{_RUN_NOW:%Y%m}"
DRILL_NOW = datetime(_RUN_NOW.year, _RUN_NOW.month, 1, 5, 0, tzinfo=UTC)


def _task_id() -> str:
    return f"task_{DRILL_MONTH}{uuid.uuid4().hex[:20]}"


def _purge_own_rows(factory: EngineFactory) -> None:
    table = physical_table("ai_task", DRILL_MONTH)
    with factory.write_session() as session:
        session.execute(table.delete().where(table.c.account_id == ACCOUNT_ID))


@pytest.fixture
def codes_env(integration_engine_factory: EngineFactory) -> Iterator[EngineFactory]:
    """真 MySQL：确保本月分片表存在，并清掉本文件自己账号的历史行（前置 + 收尾）。"""
    factory = integration_engine_factory
    with factory.write_session() as session:
        ensure_month_tables(session.connection(), DRILL_MONTH)
    _purge_own_rows(factory)
    yield factory
    _purge_own_rows(factory)


class _FaultingOcrHandler:
    """真实调用 mock OCR 通道并注入故障的处理器（见模块 docstring）。"""

    def __init__(self, fault_kind: str) -> None:
        self._provider = MockOcrProvider(
            script=MockScript(fault=MockFault(kind=fault_kind))  # type: ignore[arg-type]
        )

    def timeout_s(self) -> float:
        return 10.0

    async def handle(self, task: ClaimedTask) -> None:
        # 不 try/except：通道层异常**原样冒到执行器**，由它按异常自带的 code 写终态。
        await self._provider.recognize(
            image_key=IMAGE_KEY,
            doc_type=DOC_TYPE,
            timeout_s=self.timeout_s(),
        )


def _insert_task(factory: EngineFactory, task_id: str) -> None:
    """按提交侧的口径落一行 `PROCESSING`（必须走 `TaskRepo.insert`：分片表物理名由它算）。"""
    with factory.write_session() as session:
        TaskRepo().insert(
            session,
            AiTask(
                task_id=task_id,
                account_id=ACCOUNT_ID,
                type=TASK_TYPE,
                status="PROCESSING",
                progress=0,
                created_at=DRILL_NOW,
            ),
        )


async def _run_one_task(
    factory: EngineFactory,
    locks: RedisLockStore,
    handler: Any,
    *,
    runner_cls: type[TaskRunner] = TaskRunner,
) -> None:
    """用**真执行器**跑一条任务（`max_retries=0` ⇒ 首次失败即终态，失败分流走 `mark_failed`）。

    写成 `async def` 并在**同一个事件循环**里 `await`（`pytest-asyncio` 的 `asyncio_mode=auto`）：
    本文件另有同步用例（`TestClient`），若在这里用 `asyncio.run()` 另起一个循环，
    `redis_store` 夹具的连接池会在**另一个**（已关闭的）循环上收尾，
    实测报 `AttributeError: 'NoneType' object has no attribute 'send'` +
    `RuntimeError: Event loop is closed`（teardown error）。
    这条纪律与 `test_runner_redis.py` 一致：**异步夹具 + 异步用例 = 同一个循环**。
    """
    runner = runner_cls(
        store=SqlTaskLeaseStore(factory),
        locks=locks,
        handlers={TASK_TYPE: handler},
        policies=REGISTRY,
        config=RunnerConfig(lease_ms=30_000, max_retries=0, concurrency_limit=1),
    )
    assert await runner.run_once() is True, "没有领到任务：本用例的前提不成立"


def _read_rows(factory: EngineFactory, task_ids: Sequence[str]) -> dict[str, dict[str, Any]]:
    """按 `task_id` 读回这些行（新会话 ⇒ 走连接池的另一条连接）。"""
    table = physical_table("ai_task", DRILL_MONTH)
    with factory.primary_read_session() as session:
        rows = (
            session.execute(
                table.select().where(
                    table.c.account_id == ACCOUNT_ID, table.c.task_id.in_(list(task_ids))
                )
            )
            .mappings()
            .all()
        )
    return {str(row["task_id"]): dict(row) for row in rows}


def _counts_by_error_code(factory: EngineFactory) -> dict[str, int]:
    """**"分别计数"的可验收形态**：`WHERE status='FAILED' GROUP BY error_code`。

    裸 SQL 而不是经仓储：这是"事实源的分组能力"，与执行器的写路径相互独立
    （用被测代码的读路径去验它自己的写路径，同一个缺陷会在两侧同时成立）。
    """
    with factory.primary_read_session() as session:
        rows = session.execute(
            text(
                f"select error_code, count(*) as n from `ai_task_{DRILL_MONTH}` "
                "where account_id = :account_id and status = 'FAILED' "
                "group by error_code order by error_code"
            ),
            {"account_id": ACCOUNT_ID},
        ).all()
    return {str(code): int(count) for code, count in rows}


def _assert_codes_are_separated(
    rows: Mapping[str, Mapping[str, Any]], *, expected: Mapping[str, str]
) -> None:
    """**判据本体（§3.1）**：每行 `status='FAILED'` 且 `error_code` 各自正确、互不串。

    `expected` 是**任务号 → 期望的码**（键必须能在 `rows` 里查到——第一版把中文标签写进键里，
    于是判据自己在 `rows[key]` 上抛 `KeyError`，那是**判据的实现错**而不是被测对象的失败）。
    抽成函数是为了让判别力自证把**变异体跑出来的行**喂给同一份判据。

    为什么**必须**同时断言 `status='FAILED'`：M1 的裁定是"两个码都是 `FAILED` 的
    `error_code`，不使用 `MANUAL_REVIEW`"——只断言 `error_code` 会让一个
    "把 4003 写成 `MANUAL_REVIEW` + `error_code` 照写"的实现绿着通过。
    """
    for task_id, code in expected.items():
        row = rows[task_id]
        assert row["status"] == "FAILED", (
            f"{task_id} 的 status 应为 FAILED（M1 的失败终态只有它），实际 {row['status']!r}"
        )
        assert row["error_code"] == code, (
            f"{task_id} 的 error_code 应为 {code}，实际 {row['error_code']!r}——"
            f"两个码被写成了同一个（'都算失败'式的实现会绿）"
        )
    observed = {str(row["error_code"]) for row in rows.values()}
    assert observed == set(expected.values()), (
        f"两条失败行的码应恰好是 {sorted(expected.values())}，实际 {sorted(observed)}："
        f"两码串了（或有一行没写码）"
    )


def _assert_counts_are_separated(counts: Mapping[str, int], *, expected: Mapping[str, int]) -> None:
    """**判据本体（§3.2）**：`GROUP BY error_code` 的结果恰好是期望的分组计数。"""
    assert dict(counts) == dict(expected), (
        f"按 error_code 分组的计数应为 {dict(expected)}，实际 {dict(counts)}——"
        f"运维的『人工复核队列视图』（WHERE status='FAILED' AND error_code='4003'）与"
        f"『依赖劣化视图』（error_code='5002'）都靠这条分组"
    )


# ---------------------------------------------------------------------------
# §3.1 + §3.2 + §3.4：两码分别落库、分别计数
# ---------------------------------------------------------------------------
async def test_two_failure_codes_land_separately_on_the_real_db(
    codes_env: EngineFactory, redis_store: RedisLockStore
) -> None:
    """**§3.1 / §3.2 / §3.4**：`4003`（通道失败）与 `5002`（依赖超时）各自落库、可分组计数。

    两条任务各自经过**真实通道故障**（`MockFault(kind="error"/"timeout")`）由**真执行器**写回：
    先跑通道失败那条、再跑依赖超时那条（一次只留一条未处理的任务 ⇒ `run_once` 领到的必然是本条）。
    """
    channel_failure_task = _task_id()
    timeout_task = _task_id()

    _insert_task(codes_env, channel_failure_task)
    await _run_one_task(codes_env, redis_store, _FaultingOcrHandler("error"))

    _insert_task(codes_env, timeout_task)
    await _run_one_task(codes_env, redis_store, _FaultingOcrHandler("timeout"))

    rows = _read_rows(codes_env, [channel_failure_task, timeout_task])
    assert set(rows) == {channel_failure_task, timeout_task}, (
        f"两条任务都该在库里：{sorted(rows)}——有一行没落或没被读到"
    )
    _assert_codes_are_separated(
        rows,
        # `task_id → 期望的码`（通道失败那条、依赖超时那条）
        expected={channel_failure_task: "4003", timeout_task: "5002"},
    )
    _assert_counts_are_separated(_counts_by_error_code(codes_env), expected={"4003": 1, "5002": 1})


def _mutant_runner_class(anchor: str, replacement: str) -> Any:
    """把 `core/task_runner.py` 在**内存里**改一处，编译出一个变异 `TaskRunner`。

    与 `tests/unit/test_task_runner.py::_mutant_runner_class` 同一取向
    （工单纪律：变异一律在内存里，MUST NOT「改 `src/` + `finally` 还原」；
    `core/task_runner.py` 本身也不许改）。
    """
    runner_path = (
        Path(__file__).resolve().parents[2] / "src" / "aicore" / "core" / "task_runner.py"
    )
    source = runner_path.read_text(encoding="utf-8")
    count = source.count(anchor)
    assert count == 1, (
        f"变异锚点在 task_runner.py 里出现 {count} 次（要求恰好 1 次）：{anchor!r}——"
        f"锚点漂了就必须先修锚点，MUST NOT 让它静默变成'什么都没变'"
    )
    module = types.ModuleType("dsh_mutant_runner_codes")
    module.__file__ = str(runner_path)
    code = compile(source.replace(anchor, replacement), str(runner_path), "exec")
    sys.modules["dsh_mutant_runner_codes"] = module
    try:
        exec(code, module.__dict__)
    finally:
        del sys.modules["dsh_mutant_runner_codes"]
    return module.TaskRunner


async def test_failure_code_classification_guard_discriminates(
    codes_env: EngineFactory, redis_store: RedisLockStore
) -> None:
    """**判别力自证（§3.6）**：把"两码分别落库"改成"都写死 `4003`"，判据**必须变红**。

    内存变异（**文件从不被写**）：`_handle_failure` 里那行
    `error_code=str(error.code)` → `error_code="4003"`——即"无论哪种失败都写通道失败码"。
    复现的正是要防的形态：`design.md:210` 逐字要求「外部通道失败与依赖超时**分别计数**，
    避免把『通道挂了』误判成『任务有问题』」，写死一个码会让两个视图合并、运维失去区分能力。

    ## 断言（两半）

    1. 变异**真的生效**：同样两条任务跑完，变异体的库里**两个码都是 4003**；
    2. 同一份判据（`_assert_codes_are_separated` / `_assert_counts_are_separated`）
       喂给变异体的读数 ⇒ **必须抛**，且红在"两个码被写成了同一个"上。
    """
    mutant_cls = _mutant_runner_class(
        "            error_code=str(error.code),\n",
        '            error_code="4003",\n',
    )

    channel_failure_task = _task_id()
    timeout_task = _task_id()
    _insert_task(codes_env, channel_failure_task)
    await _run_one_task(codes_env, redis_store, _FaultingOcrHandler("error"), runner_cls=mutant_cls)
    _insert_task(codes_env, timeout_task)
    await _run_one_task(
        codes_env, redis_store, _FaultingOcrHandler("timeout"), runner_cls=mutant_cls
    )

    rows = _read_rows(codes_env, [channel_failure_task, timeout_task])
    assert {str(row["error_code"]) for row in rows.values()} == {"4003"}, (
        f"变异没有生效（两码仍然分开）：{ {k: v['error_code'] for k, v in rows.items()} }——"
        f"本自证的前提不成立"
    )
    with pytest.raises(AssertionError, match="两个码被写成了同一个"):
        _assert_codes_are_separated(
            rows,
            expected={channel_failure_task: "4003", timeout_task: "5002"},
        )
    with pytest.raises(AssertionError, match="分组的计数"):
        _assert_counts_are_separated(
            _counts_by_error_code(codes_env), expected={"4003": 1, "5002": 1}
        )


# ---------------------------------------------------------------------------
# §3.3 降级不阻塞核心业务（通道不可用期间仍能受理新任务）
# ---------------------------------------------------------------------------
@pytest.fixture
def mysql_api_client(
    monkeypatch: pytest.MonkeyPatch, codes_env: EngineFactory
) -> Iterator[TestClient]:
    """经真组合根 + 真 MySQL 的 API 客户端（`env="test"` ⇒ 不装配执行器）。

    与 `tests/integration/test_submit_mysql.py::mysql_api_client` 同一手法：
    进 `TestClient`（跑 lifespan）之后再替换 `app.state.engine_factory`——反过来会先被真装配覆盖。
    """
    from aicore.main import create_app

    settings = integration_settings(env="test")
    monkeypatch.setattr("aicore.main.get_settings", lambda: settings)
    app = create_app()
    with TestClient(app) as client:
        app.state.engine_factory = codes_env
        yield client


def test_channel_downtime_does_not_block_new_submissions(
    mysql_api_client: TestClient, codes_env: EngineFactory
) -> None:
    """**§3.3**：通道不可用期间，`POST /aicore/ocr` 仍返回 `202` + `taskId`。

    依据 `er.md:176`：「云视觉/OCR 不可用 → 任务**转人工复核队列原样流转**、
    AI 标记缺席**不阻塞**」——判据要断言**受理链路**不受影响，
    而不是只断言"失败任务变成了 FAILED"。

    ## 两步（第一步是"通道真的不可用"的证据）

    1. **把通道打到不可用**：用真 mock 通道的故障注入调用一次，拿到
       `ProviderChannelFailureError`（`code == 4003`）——"降级状态"因此不是用例假定的，
       而是**当场观测到的**；
    2. **不可用期间提交新任务**：`202` + `taskId` + 库里确实多一行 `PROCESSING`。

    ## M1 的边界（如实登记）

    M1 的受理路径**不调通道**（`handlers={}`，没有 OCR 执行），故这条判据证明的是
    "**受理链路不被通道健康状态阻塞**"（它压根不查询通道状态）。
    端到端形态（真通道失败 → 任务 FAILED(4003) → 期间新单仍被受理）由
    `test_two_failure_codes_land_separately_on_the_real_db` + 本用例**共同**覆盖：
    前者证明失败被正确分类，后者证明受理不受影响。
    """
    # ① 通道真的不可用（当场观测，不是假定）。
    broken_channel = MockOcrProvider(script=MockScript(fault=MockFault(kind="error")))

    async def _call_broken_channel() -> None:
        await broken_channel.recognize(image_key=IMAGE_KEY, doc_type=DOC_TYPE, timeout_s=10.0)

    import asyncio

    with pytest.raises(ProviderChannelFailureError) as excinfo:
        asyncio.run(_call_broken_channel())
    assert excinfo.value.code == 4003, f"通道失败应带 4003：{excinfo.value.code}"

    # ② 不可用期间受理新任务。
    response = mysql_api_client.post(
        "/aicore/ocr",
        json={"imageKey": IMAGE_KEY, "docType": DOC_TYPE},
        headers={
            ACCOUNT_ID_HEADER: ACCOUNT_ID,
            "Idempotency-Key": f"idem-codes-{uuid.uuid4().hex}",
        },
    )

    assert response.status_code == 202, (
        f"通道不可用期间受理被阻塞了：HTTP {response.status_code} {response.text[:200]}——"
        f"er.md:176 要求『原样流转、AI 标记缺席不阻塞』"
    )
    task_id = response.json()["data"]["taskId"]
    rows = _read_rows(codes_env, [task_id])
    assert rows[task_id]["status"] == "PROCESSING", (
        f"新任务应落成 PROCESSING（受理成功、等待执行），实际 {rows[task_id]['status']!r}"
    )
    # 通道不可用**不改变**失败计数：本次受理既没产生 4003 也没产生 5002
    # （它压根没调通道）——这条把"不阻塞"与"失败计数"两件事分开，免得混成一个信号。
    assert _counts_by_error_code(codes_env) == {}, (
        f"受理本身不该产生失败码：{_counts_by_error_code(codes_env)}"
    )


async def test_timeout_path_comes_from_a_real_timeout_not_a_reused_channel_failure(
    codes_env: EngineFactory, redis_store: RedisLockStore
) -> None:
    """**§3.4**：`5002` 走的是**依赖超时**那条路径，不是复用通道失败。

    手法：先断言**通道层**两种故障各自给出自己的异常类与码（这一步不碰执行器），
    再断言执行器把**超时那个**落成 `5002`（`ProviderChannelFailureError` 是
    `ChannelFailureError` 的子类、`ProviderTimeoutError` 是 `DependencyTimeoutError` 的子类，
    两者是**兄弟**——若谁把超时路径改成"抛通道失败"，下面的 `isinstance` 断言会红）。

    这条与 `test_two_failure_codes_land_separately_on_the_real_db` 的分工：
    那条验"落库的码对"，这条验"**来源**对"（借 `provider/errors.py` 的类型层级）。
    """
    error_provider = MockOcrProvider(script=MockScript(fault=MockFault(kind="error")))
    timeout_provider = MockOcrProvider(script=MockScript(fault=MockFault(kind="timeout")))

    async def _collect() -> tuple[BaseException, BaseException]:
        try:
            await error_provider.recognize(image_key=IMAGE_KEY, doc_type=DOC_TYPE, timeout_s=10.0)
        except BaseException as exc:  # 这里就是要抓住它来断言类型
            error_exc = exc
        try:
            await timeout_provider.recognize(
                image_key=IMAGE_KEY, doc_type=DOC_TYPE, timeout_s=10.0
            )
        except BaseException as exc:
            timeout_exc = exc
        return error_exc, timeout_exc

    error_exc, timeout_exc = await _collect()

    assert isinstance(error_exc, ProviderChannelFailureError)
    assert error_exc.code == 4003
    assert isinstance(timeout_exc, ProviderTimeoutError)
    assert timeout_exc.code == 5002
    assert not isinstance(timeout_exc, ProviderChannelFailureError), (
        "超时路径抛的是通道失败类：两条路径被合并了（那正是 §3.4 要拦的形态）"
    )

    # 执行器把超时那条落成 5002（真库上确认，而不是只看异常类型）。
    timeout_task = _task_id()
    _insert_task(codes_env, timeout_task)
    await _run_one_task(codes_env, redis_store, _FaultingOcrHandler("timeout"))
    rows = _read_rows(codes_env, [timeout_task])
    _assert_codes_are_separated(rows, expected={timeout_task: "5002"})
