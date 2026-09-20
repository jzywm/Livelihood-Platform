"""`api/deps.py` 依赖提供者的契约用例。

## 两条用例覆盖的是**两件不同的事**（缺一不可）

1. `test_get_settings_returns_assembled_instance`：**提供者自身的语义**——
   装配什么就返回什么，不自行构造、不包装、不做类型转换。用桩请求即可验证，
   而且**必须**用桩：它测的是取值路径，不是组合根。
2. `test_dependency_resolves_through_the_real_composition_root`（Task 4.5 T1 新增）：
   **组合根真的把值装配上去了**。

## 第 2 条补的是 L2 这道断链（如实留档）

`main.py` 的 lifespan 在 T1 之前**从未写 `app.state.settings`**，而 `get_settings`
正是从那里取。在此之前本服务没有任何走 `Depends(get_settings)` 的路由，
故这条断链一直**不可见**；Task 4.5 一加真实路由就会
`AttributeError`（Starlette `State.__getattr__` 缺属性即抛）。

**它为什么没被第 1 条抓到**：桩请求自己造了 `SimpleNamespace(state=SimpleNamespace(
settings=sentinel))`——把**被测的那一环（组合根装配）整个绕过去了**。
这是本项目反复出现的同一形态：**用例把关键环节替成了桩，于是那一环永远不会有红灯**
（同第 3 组 `<= MAX_ID_LENGTH` 假绿、第 4 组 `get_args(type 别名)` 恒真、以及
「判别力自证没让真判据参与」）。故第 2 条**必须**经真组合根，且**不允许**任何桩。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient

from aicore.api.deps import get_settings
from aicore.core.config import Settings
from aicore.main import create_app


def test_get_settings_returns_assembled_instance() -> None:
    """装配什么就返回什么：以 sentinel 断言**同一性**（is），而不是相等性。"""
    sentinel = object()
    # 桩请求：get_settings 只要求 request.app.state.settings 这一条取值路径。
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(settings=sentinel)))

    assert get_settings(request) is sentinel  # type: ignore[arg-type]


def _build_probe_app(observed: list[Settings]) -> FastAPI:
    """全新应用 + 一条挂 `Depends(get_settings)` 的探针路由（不进生产代码）。"""
    app = create_app()
    router = APIRouter(include_in_schema=False)

    @router.get("/__probe__/settings")
    def read_settings(
        # B008：FastAPI 的依赖注入**惯用法**就是在默认值位置调用 `Depends(...)`。
        # 此处行级豁免而不是全局关掉 B008：B008 防的是「可变默认值 / 每次调用都求值的默认值」
        # 这类真实陷阱，全局关掉会把它们在别处的价值一起丢掉
        #（第 3 组评审对 `allowed-confusables` 提过同样的建议：豁免要落在行上）。
        settings: Settings = Depends(get_settings),  # noqa: B008
    ) -> dict[str, str]:
        observed.append(settings)
        # 只回不含取值的字段：本用例不校验配置内容，只校验"取到了真对象"。
        return {"env": settings.env, "provider": settings.provider}

    app.include_router(router)
    return app


def test_dependency_resolves_through_the_real_composition_root() -> None:
    """**经真组合根**装配后，`Depends(get_settings)` 必须解析成功且交出 `Settings` 实例。

    MUST NOT 用桩：桩会绕过组合根，而组合根装配**正是**本用例的被测对象。
    `TestClient` 的 `with` 块会真正触发 lifespan，故 `app.state.settings` 的装配
    就在这一步发生——直接构造 client 而不进 `with`，本用例会红，那也正是它该有的行为。
    """
    observed: list[Settings] = []
    app = _build_probe_app(observed)

    with TestClient(app) as client:
        response = client.get("/__probe__/settings")

    assert response.status_code == 200, (
        f"经组合根解析依赖失败（HTTP {response.status_code}）："
        f"lifespan 可能没有装配 app.state.settings，响应体={response.text[:200]}"
    )
    assert len(observed) == 1, "探针路由没有被真正调用：本用例退化成空转"
    assert isinstance(observed[0], Settings), (
        f"依赖交出的不是 Settings 实例而是 {type(observed[0]).__name__}："
        f"说明取值路径被包装或替换过"
    )


def test_dependency_is_not_available_before_startup() -> None:
    """**阴性对照**：未经 lifespan（未进 `with`）时依赖必须失败。

    这条证明上面那条的绿灯**来自装配**，而不是来自某种"取不到就给个默认值"的兜底。
    若哪天有人把 `get_settings` 改成"缺属性就 `Settings()`"，本用例立刻变红——
    那正是 `api/deps.py` 的 docstring 明确禁止的形态（兜底会把误配置推迟到运行期）。

    ## 判据键的是**异常出处**，不只是异常类型（本轮收紧）

    第一版写成 `try: client.get(...) except AttributeError: return`，即"抛了
    `AttributeError` 就算走对了路"。问题在于 `TestClient` 会把**处理函数内部**的
    `AttributeError` 原样抛出：于是"取不到就造个假的兜底"这类实现也落进同一个
    `except` 分支 ⇒ 用例**仍然全绿**。实测（内存变异 `get_settings` 的兜底写法）：

    - 兜底 `Settings()`（请求变成 200）→ 判红 ✓；
    - 兜底 `Settings.model_construct()` / `SimpleNamespace()` → **仍绿** ✗：
      它们让请求在处理函数里炸出
      `AttributeError: 'types.SimpleNamespace' object has no attribute 'env'`，
      走的是**完全不同的那条路**，却被当成了"期望路径"。

    故判据收紧成两条**正面事实**：① 抛出的必须是 `State.__getattr__` 那一条
    （消息里点名缺失的属性 `settings`）；② 路由**没有**观察到任何 settings 值。
    兜底一旦出现，两者必有一条不成立——"红了"不再等于"走对了路"。

    **`match` 刻意不带引号**：键的是"**缺的是哪个属性**"，不是上游文案的标点。
    写成 `match="'settings'"` 会把判据耦合到 Starlette 今天的排版（单引号）：
    上游改成双引号、或写成 `State has no attribute settings`，这条就会因**纯排版**变红
    ——那种红换不来任何判别力，却会**训练人忽略红**（本项目刚花一轮消灭随机假红，
    这是同一类成本）。去掉引号后信息一字不少，判别力实测不受影响：
    `SimpleNamespace` 兜底的异常消息
    `'types.SimpleNamespace' object has no attribute 'env'` 里没有 `settings`，照样判红。
    """
    observed: list[Settings] = []
    app = _build_probe_app(observed)

    client = TestClient(app)  # 刻意不进 `with`：不触发 lifespan
    with pytest.raises(AttributeError, match="settings"):
        client.get("/__probe__/settings")

    assert observed == [], (
        "依赖竟然解析出值并交给了路由：说明有人加了兜底取值"
        "（`api/deps.py` 明令禁止，它会把误配置推迟到运行期）"
    )


# ---------------------------------------------------------------------------
# `api_client` 夹具的自证（Task 4.5 T1）
#
# 夹具由控制者提供、并被 Task 4.5/4.6 的实现者**禁止修改**。故它必须**自证可用**：
# 一个坏夹具会让实现者卡在"路由写对了但用例跑不起来"，而那种卡点最容易被误判成
# 自己的代码问题。
#
# ## 第一版自证是**假绿**，形态与本项目反复出现的那一类完全相同（如实留档）
#
# 初版 `test_api_client_fixture_reaches_a_writable_sandbox` 在**主线程**直接对
# `sandbox_engine` 建表/写入/读回，全绿。但路由跑在「AnyIO worker thread」，
# 而裸 `create_engine("sqlite://")` 的默认池是 `SingletonThreadPool`
# ——**每线程一条独立连接 = 每线程一个空库**。实测：
#
#     主线程表数   = ['ai_task_202607', ...]
#     工作线程表数 = []
#
# 即：**用例把"经真应用发请求"这一环替成了直接读写引擎**，于是那个环永远不会有红灯。
# 由 Task 4.5 的实现者发现并给出复现证据，控制者复核后修 `build_sqlite_engine`
# （`StaticPool` + `check_same_thread=False`），并把下面这条改写成**经真组合根发真请求**。
#
# 这与今天另外三处是同一形态：`<= MAX_ID_LENGTH` 假绿、`get_args(type 别名)` 恒真、
# 「判别力自证没让真判据参与」。**判据必须经过被测的那一环。**
# ---------------------------------------------------------------------------
def test_sandbox_tables_are_visible_from_a_route(
    api_client: TestClient, sandbox_engine: Any
) -> None:
    """**经真组合根发一条真请求**，断言路由线程能看见沙盒里建的表。

    与下面那条的分工：本条走**完整链路**（TestClient → portal 线程 → AnyIO worker thread
    → 引擎），故它能抓到"池类型不对导致每线程一个空库"这类**只在真实请求路径上暴露**的缺陷；
    下面那条只验替身指向的库可写。两条都在，但**本条才是夹具可用的判据**。

    ## 为什么表名在**运行期算**，而不是写死 `ai_task_202607`

    写死会造出一个**随时钟漂移的判据**：`2026-09` 之后，一个真实的
    `datetime.now()` 路由会去打 `ai_task_202609`，而写死的断言仍只查 `ai_task_202607`
    ——那时它验的是"某张固定表在不在"，**与路由真正会访问的表无关**。
    （控制者用真实时钟写探针时正是撞上这个：`no such table: ai_task_202609`。
    实现者的用例没有这个问题，因为它们用 `dependency_overrides[get_now]` 把时钟
    钉进沙盒有表的那两个月——那是正确的做法，本用例改为不依赖时钟。）

    做法：**先用同一个沙盒建出当前月的月表**（复用 `sandbox_copy`），再让请求去打它。
    于是本用例断言的是「路由线程能看到**路由自己会用的那张表**」，何时运行都成立。
    """
    from datetime import UTC, datetime

    from sqlalchemy import MetaData, text
    from sqlalchemy.schema import CreateTable

    from tests.support.db_sandbox import sandbox_copy

    app = api_client.app
    month = datetime.now(UTC).strftime("%Y%m")
    physical = f"ai_task_{month}"

    meta = MetaData()
    table = sandbox_copy("ai_task", physical, meta)
    with sandbox_engine.begin() as conn:
        conn.exec_driver_sql(
            str(
                CreateTable(table, include_foreign_key_constraints=[]).compile(
                    dialect=conn.dialect
                )
            )
        )

    router = APIRouter(include_in_schema=False)

    @router.get("/__probe__/sandbox-tables")
    def sandbox_tables() -> dict[str, object]:
        factory = app.state.engine_factory
        with factory.primary_read_session() as session:
            rows = session.execute(text(f"SELECT count(*) FROM {physical}")).scalar_one()
        return {"rows": rows, "table": physical}

    app.include_router(router)

    response = api_client.get("/__probe__/sandbox-tables")

    assert response.status_code == 200, (
        f"路由线程看不到沙盒表 {physical}（HTTP {response.status_code}）：{response.text[:300]}\n"
        f"最常见原因是内存库用了默认的 SingletonThreadPool——每线程一个空库；"
        f"见 tests/support/db_sandbox.py::build_sqlite_engine 的 docstring"
    )
    assert response.json()["rows"] == 0, "沙盒表存在但初始行数不为 0：夹具没有隔离干净"


def test_api_client_fixture_reaches_a_writable_sandbox(
    api_client: TestClient, sandbox_engine: Any
) -> None:
    """`api_client` 必须同时满足：真组合根已装配、且沙盒库**可写**。

    **为什么必须写一行而不只是读**：只读探针（`SELECT 1`）在"引擎接错但恰好能连"时
    也会绿；而"写进去再查回来"才证明替身确实指向那个沙盒库、且事务能提交。
    这正是 Task 4.5 的 `POST /aicore/ocr` 要依赖的能力。

    同时断言 `app.state.settings` 与 `app.state.engine_factory` 都在——
    它们是组合根的两个装配点，缺一个都会让真实路由 `AttributeError`。

    **能力边界（如实写明）**：本条在**主线程**直接操作引擎，故它**不能**替代上面那条
    ——"路由线程能看到表"这件事只有经真请求才验得了。
    """
    from sqlalchemy import text

    app = api_client.app
    assert app.state.settings is not None, "组合根没有装配 app.state.settings"
    assert app.state.engine_factory is not None, "组合根没有装配 app.state.engine_factory"

    with sandbox_engine.begin() as conn:
        conn.execute(text("CREATE TABLE probe_writable (v INT)"))
        conn.execute(text("INSERT INTO probe_writable (v) VALUES (42)"))
    with sandbox_engine.connect() as conn:
        value = conn.execute(text("SELECT v FROM probe_writable")).scalar_one()

    assert value == 42, f"沙盒库写入后读回不一致（读到 {value!r}）：替身没有指向该库"
