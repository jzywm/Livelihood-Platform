"""提交幂等与并发冲突的**真 MySQL** 判据（Task 4.9 §5 的待补项 ①②③）。

## 本文件补的是哪三条（默认段补不了的）

1. **①** 真 DDL 的 `UNIQUE KEY uk_idem` 拦下第二行，且报错**指向该索引**——
   沙盒是 `models.py` 的复制表：约束同源，**错误形态不是生产的**；
2. **②** **真并发**：两条**独立连接**同时提交同一键 ⇒ 两个 `202`、同号、一行——
   沙盒是 `StaticPool` **单连接**，并发在那里被序列化；
3. **③** "回读走主库"的端到端对照：本机只有主库 ⇒ 如实登记为
   "**结构层已钉、端到端无从对照**"，MUST NOT 编一个对照出来。

## 并发怎么才算"真"（**实测踩过一次**，写下来免得后人重踩）

第一版用 `TestClient` + 两个线程各 `post` 一次，并在 `find_by_idem_key` 里放了一个
`threading.Barrier(2)`：**15 秒后 `BrokenBarrierError`**——第二个请求根本没进到服务端。
即 `TestClient` 是**单 portal 的同步客户端**，同时 `post` 会被串行化，撞不出并发。

改用 **`httpx.ASGITransport` + `asyncio.gather`**：count 个请求成为**同一个事件循环里的
count 个 task**，路由在 `await run_in_threadpool(...)` 处让出 ⇒ 每个请求各自在线程池里开
**独立会话**（`factory.write_session()` ⇒ 连接池里各自一条连接）⇒ 两条连接**同时在 MySQL
上执行**。栅栏因此必定被满足（下面那条"加宽窗口"用例就是靠它证明冲突分支真的被走到了）。

## 经**真组合根**装配（不是自己拼路由）

`mysql_api_client` 与 `tests/conftest.py::api_client` 同一手法：`create_app()` + 真 lifespan，
再把 `app.state.engine_factory` 换成**真 MySQL** 的工厂——身份依赖、会话装配、写后立即读、
信封与异常处理四条链路都是真的，只有"引擎指向哪个库"不同。

**`env="test"` 是刻意的**：`main.py` 的判据是 `settings.env != "test"` 才装配执行器，
而本文件只验提交路径；若装配了执行器，它会去扫本月的真表并真的处理任务
（那会改动别的用例正在看的行）。

## 数据卫生

本文件用**自己的账号** `ACCOUNT_ID`，前置与收尾各删一次本月表里属于它的行
（判据就是 `account_id`；不碰别人的行——与 `test_runner_redis.py::_purge_stale_tasks` 同口径）。
"""

from __future__ import annotations

import asyncio
import logging
import threading
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy.exc import IntegrityError

from aicore.api.deps import ACCOUNT_ID_HEADER
from aicore.api.ocr import IDEMPOTENCY_KEY_HEADER
from aicore.repository.base import ShardKey, physical_table
from aicore.repository.models import AiTask
from aicore.repository.session import EngineFactory
from aicore.repository.sharding import ensure_month_tables
from aicore.repository.task_repo import TaskRepo
from tests.conftest import integration_settings

pytestmark = pytest.mark.integration

#: 本文件专属账号：清理与断言都按它取范围（MUST NOT 碰别的用例的行）。
ACCOUNT_ID = "acc_it_idem_4_9"
IMAGE_KEY = "cert/oss/it/4_9/idem.jpg"
DOC_TYPE = "BUSINESS_LICENSE"

#: 演练月 = **当前月**（`uk_idem` 是「同月表内唯一」，而提交侧用墙钟算月；
#: 与 `test_runner_redis.py::DRILL_MONTH` 同一理由：本文件走的是真路由的真路径）。
_RUN_NOW = datetime.now(UTC)
DRILL_MONTH = f"{_RUN_NOW:%Y%m}"
#: 写进 `created_at` 的时刻：本月内的固定时刻，避免月末跑测试时落到下个月。
DRILL_NOW = datetime(_RUN_NOW.year, _RUN_NOW.month, 1, 4, 0, tzinfo=UTC)

#: 真并发跑几轮（每轮换一个幂等键）：跑几轮不会让判据变弱，只增加"真的交错"的机会。
CONCURRENT_ROUNDS = 3


def _task_id() -> str:
    """`task_` + 创建月 + UUID hex（`er.md` §5.4 的形态，总长 32）。"""
    return f"task_{DRILL_MONTH}{uuid.uuid4().hex[:20]}"


@pytest.fixture
def mysql_tables(integration_engine_factory: EngineFactory) -> Iterator[EngineFactory]:
    """确保本月的三张分片表存在，并清掉本文件自己账号的历史行（前置 + 收尾各一次）。

    表**不 DROP**（理由见 `test_runner_redis.py::DRILL_MONTH` 的注释：同一天可能有别的进程
    正在用同一张月表）。
    """
    factory = integration_engine_factory
    with factory.write_session() as session:
        ensure_month_tables(session.connection(), DRILL_MONTH)
    _purge_own_rows(factory)
    yield factory
    _purge_own_rows(factory)


def _purge_own_rows(factory: EngineFactory) -> None:
    table = physical_table("ai_task", DRILL_MONTH)
    with factory.write_session() as session:
        session.execute(table.delete().where(table.c.account_id == ACCOUNT_ID))


@pytest.fixture
def mysql_api_client(
    monkeypatch: pytest.MonkeyPatch, mysql_tables: EngineFactory
) -> Iterator[TestClient]:
    """经真组合根 + 真 MySQL 的 API 客户端（`env="test"` ⇒ 不装配执行器）。"""
    from aicore.main import create_app

    settings = integration_settings(env="test")
    monkeypatch.setattr("aicore.main.get_settings", lambda: settings)
    app = create_app()
    with TestClient(app) as client:
        # 装配点替换（与 `tests/conftest.py::api_client` 同一手法）：lifespan 之后覆盖，
        # 因为反过来会先被 lifespan 的真装配覆盖掉。
        app.state.engine_factory = mysql_tables
        yield client


def _rows_for_key(factory: EngineFactory, idem_key: str) -> list[dict[str, Any]]:
    """按 `(account_id, idem_key)` 读回本月的行（**新会话**：走连接池的另一条连接）。"""
    table = physical_table("ai_task", DRILL_MONTH)
    with factory.primary_read_session() as session:
        rows = (
            session.execute(
                table.select().where(
                    table.c.account_id == ACCOUNT_ID, table.c.idem_key == idem_key
                )
            )
            .mappings()
            .all()
        )
    return [dict(row) for row in rows]


def _submit_concurrently(
    app: Any, *, idempotency_key: str, count: int = 2
) -> list[Response]:
    """用 **ASGI 传输 + `asyncio.gather`** 同时发 `count` 个请求（**真并发**）。

    为什么要换掉 `TestClient`：见模块 docstring 的"并发怎么才算真"一节
    （实测：两个线程同时 `post` 会被串行化，栅栏 15s 超时）。

    `ASGITransport` 不跑 lifespan，故本文件仍由 `mysql_api_client` 的 `TestClient`
    负责启动（装配 `app.state`），这里只借用**同一个 `app` 对象**发并发请求。
    """

    async def _run() -> list[Response]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            gathered = await asyncio.gather(
                *[
                    client.post(
                        "/aicore/ocr",
                        json={"imageKey": IMAGE_KEY, "docType": DOC_TYPE},
                        headers={
                            ACCOUNT_ID_HEADER: ACCOUNT_ID,
                            IDEMPOTENCY_KEY_HEADER: idempotency_key,
                        },
                    )
                    for _ in range(count)
                ]
            )
        return list(gathered)

    return asyncio.run(_run())


# ---------------------------------------------------------------------------
# ① 真 DDL 的 uk_idem 真的拦第二行（且报错指向该索引）
# ---------------------------------------------------------------------------
def test_real_uk_idem_rejects_the_second_row_and_the_repo_reads_the_first(
    mysql_tables: EngineFactory,
) -> None:
    """**①**：真 `UNIQUE KEY uk_idem(account_id, idem_key)` 在真库上拦下第二行。

    两半，缺一不可：

    1. **拦得住**：同 `(account_id, idem_key)` 插第二行 → `IntegrityError`，
       且错误信息里**出现 `uk_idem`**（证明拦它的是**那个**索引，不是别的主键/外键）；
    2. **回读得到**：`TaskRepo.find_by_idem_key`（带账号、同月表）拿到的是**第一行**
       —— 这正是 `submit_ocr_task` 吸收冲突时依赖的那一步。

    第一行用 `TaskRepo.insert` 落（**生产写路径**），第二行换一个 `task_id`
    （否则会先撞主键，那验的就不是唯一键了）。
    """
    idem_key = f"it-uk-{uuid.uuid4().hex}"
    repo = TaskRepo()
    first_task_id = _task_id()

    with mysql_tables.write_session() as session:
        repo.insert(
            session,
            AiTask(
                task_id=first_task_id,
                account_id=ACCOUNT_ID,
                idem_key=idem_key,
                type="OCR",
                status="PROCESSING",
                progress=0,
                created_at=DRILL_NOW,
            ),
        )

    with pytest.raises(IntegrityError) as excinfo, mysql_tables.write_session() as session:
        repo.insert(
            session,
            AiTask(
                task_id=_task_id(),  # 不同的主键 ⇒ 撞的只能是 uk_idem
                account_id=ACCOUNT_ID,
                idem_key=idem_key,
                type="OCR",
                status="PROCESSING",
                progress=0,
                created_at=DRILL_NOW,
            ),
        )

    message = str(excinfo.value)
    assert "uk_idem" in message, (
        f"第二行被拦下了，但报错没有指向 `uk_idem`：{message[:400]}——"
        f"拦它可能是别的约束（主键/其它唯一键），那本用例证明的就不是幂等键"
    )

    with mysql_tables.primary_read_session() as session:
        found = repo.find_by_idem_key(
            session,
            shard=ShardKey(account_id=ACCOUNT_ID, created_at=DRILL_NOW),
            account_id=ACCOUNT_ID,
            idem_key=idem_key,
        )
    assert found is not None, "冲突之后按 (account_id, idem_key) 竟然读不回第一行"
    assert found.task_id == first_task_id
    assert len(_rows_for_key(mysql_tables, idem_key)) == 1, "真库里应恰好一行"


# ---------------------------------------------------------------------------
# ② 真并发：两条独立连接同时提交同键
# ---------------------------------------------------------------------------
def test_concurrent_submits_from_two_connections_yield_one_task(
    mysql_api_client: TestClient, mysql_tables: EngineFactory
) -> None:
    """**②**：两条**独立连接**同时提交同一键 ⇒ **两个 202 + 同一个 `taskId` + 一行**。

    判据与工单逐字一致：**两个响应都必须成功**（MUST NOT 让其中一个报 5000）、
    **`taskId` 相同**、**库里只有一行**（`spec.md:25`「不重复产生任务与调用费用」）。

    ## 它不保证"一定走到冲突分支"（那是下面那条的事）

    两个请求谁先提交是不确定的：若第一个已提交、第二个才查幂等，第二个走的是**普通幂等命中**
    路径——同样满足本用例的三条断言（这正是"重复提交无论如何都幂等"的要求）。
    "**一定**走到冲突分支"由下面那条加宽窗口的用例给出。
    """
    for _round in range(CONCURRENT_ROUNDS):
        idem_key = f"it-race-{uuid.uuid4().hex}"

        responses = _submit_concurrently(mysql_api_client.app, idempotency_key=idem_key)

        assert [response.status_code for response in responses] == [202, 202], (
            f"并发同键的两个请求必须都成功（工单 §2.2），实际 "
            f"{[(r.status_code, r.text[:120]) for r in responses]}"
        )
        task_ids = {response.json()["data"]["taskId"] for response in responses}
        assert len(task_ids) == 1, f"并发同键返回了两个不同的任务号：{task_ids}"
        rows = _rows_for_key(mysql_tables, idem_key)
        assert len(rows) == 1, (
            f"库里应恰好一行，实际 {len(rows)} 行：重复提交产生了第二个任务"
        )


def test_a_widened_race_window_really_hits_the_conflict_branch(
    mysql_api_client: TestClient,
    mysql_tables: EngineFactory,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """**②（加强版）**：把竞态窗口**加宽到必然**，于是**一定**走到冲突分支。

    ## 为什么要加宽

    上面那条是"真并发但不确定谁先谁后"；若两个请求恰好错开，走的可能是普通幂等命中路径，
    于是"撞 `uk_idem` 后回读"这段**可能一次都没被执行**（绿灯却没验到东西）。
    这里让**每个请求的第一次幂等查询**在栅栏上等另一个请求——两个请求因此**必然**
    都越过"查幂等"之后才有人插入 ⇒ 后插入的那个**必然**撞 `uk_idem`。

    **栅栏必须放在"查完（且没查到）之后"**（实测踩过一次）：第一版把 `barrier.wait()`
    放在**查询之前**，两个线程放行后仍然会各自去查，先查完的那个可能**已经把行插进去了**
    ——后查的那个于是直接命中，冲突根本没发生（用例三条断言全绿，只有成因断言把我拦住了）。
    放在"查完且为空之后"，才是把**真实存在的窗口**（SELECT 与 INSERT 之间）加宽到必然命中。

    这不是"造一个假场景"：被测的仍然是**真 MySQL 的真唯一键**与**生产的那段代码**
    （只多一个栅栏，且栅栏只作用在"第一次查询"上，回读那一次不拦）。

    ## 判据

    除了上面那三条（202 / 同号 / 一行），再加一条**成因**：日志里出现
    「撞了 `uk_idem` …… 已回读」——否则"两个请求都成功"可能只是因为它们错开了，
    本用例就退化成上面那条的重复。
    """
    idem_key = f"it-window-{uuid.uuid4().hex}"
    barrier = threading.Barrier(2)
    local = threading.local()
    real_find = TaskRepo.find_by_idem_key

    def racy_find(self: TaskRepo, session: Any, **kwargs: Any) -> Any:
        found = real_find(self, session, **kwargs)
        # 每个**线程**只在它自己的第一次查询上等栅栏，且**只在"没查到"时**等
        # （回读那一次、以及已经查到的那一次都不等——否则会自己跟自己死锁）。
        if found is None and not getattr(local, "waited", False):
            local.waited = True
            barrier.wait(timeout=15)
        return found

    monkeypatch.setattr(TaskRepo, "find_by_idem_key", racy_find)

    with caplog.at_level(logging.INFO, logger="aicore.service.task.submit"):
        responses = _submit_concurrently(mysql_api_client.app, idempotency_key=idem_key)

    assert [response.status_code for response in responses] == [202, 202], (
        f"加宽窗口之后仍有一个请求失败：{[(r.status_code, r.text[:200]) for r in responses]}"
    )
    assert len({response.json()["data"]["taskId"] for response in responses}) == 1
    assert len(_rows_for_key(mysql_tables, idem_key)) == 1
    assert any("撞了 uk_idem" in record.getMessage() for record in caplog.records), (
        "没有出现冲突被吸收的日志：两个请求可能只是恰好错开，本用例没有验到冲突分支"
        f"（caplog：{caplog.text!r}）"
    )


# ---------------------------------------------------------------------------
# ③ "回读走主库"：如实登记（没有从库可对照）
# ---------------------------------------------------------------------------
def _called_session_entries(source: str) -> set[str]:
    """源码里**真正被调用**的会话入口方法名（AST 层；docstring 里的示例文字不算）。"""
    import ast

    entries: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"write_session", "read_session", "primary_read_session"}
        ):
            entries.add(node.func.attr)
    return entries


def test_primary_read_has_no_replica_to_compare_against() -> None:
    """**③**：`er.md:287` 的"写后立即读强制走主库"——**结构层已钉，端到端无从对照**。

    ## 为什么"端到端"这条在本机做不出来（如实登记，MUST NOT 编一个对照）

    `er.md:287` 要防的是「从从库读到了旧的（还没同步的）状态」。要**端到端**验证它，
    前提是**存在一个会返回旧值的从库**。而本机：

    - 没有任何从库配置——`integration_settings()` 的 `mysql_readonly_host` **就是** `mysql_host`
      （`repository/session.py` 在没有独立从库时回落到主库，并记一条 `[自检]` 日志说明
      "只读到底连哪里"）；
    - 故"从从库读到旧值"这个反例**造不出来**：无论代码走哪条会话入口，读到的都是主库。

    ⇒ 本用例**不造那个对照**，只做两件真能做的事：

    1. **结构层**（可机械检查）：`service/task/submit.py` **不自开会话**
       （会话入口集合为空）⇒ 冲突后的回读只能用**调用方给的那个**会话，
       而路由给的是 `write_session()`（主库）。这条与
       `tests/api/test_task_poll.py::test_session_entries_match_the_declared_split` 同源，
       这里在集成段再记一遍，让"这条没验"出现在集成报告里；
    2. **把缺口的触发条件写死**：一旦本机真的配了独立从库，本用例**立刻变红**，
       提示必须补一条真的对照用例（而不是让"无从对照"这句话无限期地留下来）。
    """
    from pathlib import Path

    settings = integration_settings()
    assert settings.mysql_readonly_host == settings.mysql_host, (
        f"本机配了独立从库（readonly={settings.mysql_readonly_host!r}、"
        f"primary={settings.mysql_host!r}）：那么'走主库'这条**可以**端到端对照了——"
        f"请补一条「冲突回读没有从从库读到旧值」的用例，并删掉本用例的'无从对照'结论"
    )

    submit_source = (
        Path(__file__).resolve().parents[2] / "src" / "aicore" / "service" / "task" / "submit.py"
    ).read_text(encoding="utf-8")
    assert _called_session_entries(submit_source) == set(), (
        f"service/task/submit.py 自己开了会话：回读就不再保证走调用方给的主库写会话"
        f"（er.md:287）——{_called_session_entries(submit_source)}"
    )
