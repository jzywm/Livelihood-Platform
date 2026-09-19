"""数据库沙盒：按**物理表名**建表的 sqlite 内存库（Task 4.5 抽取）。

## 为什么抽到共享层

该构造器原在 `tests/repository/test_repos.py` 内部（Task 3.7）。Task 4.5 的接口用例
同样需要它，若在那边复制一份，就会造出**第二套会漂移的沙盒口径**——
而沙盒的三处「缩水」一旦两边理解不一致，「沙盒绿」与「生产行为」的差距就再也说不清。
按第 3 组 `task-3.6b` 的先例（把重复的 DDL 解析助手提成共享层），此处同样抽取。

## 沙盒的三处「缩水」（MUST 知道，否则会把沙盒的绿灯当成生产保证）

1. `server_default='CURRENT_TIMESTAMP(3)'` 是 MySQL 语法，sqlite 报
   `near "(" syntax error`（实测）。沙盒里**只抹掉时间类默认值**；
   `DEFAULT 0` / `DEFAULT 'PROCESSING'` 这类 sqlite 认得，一律保留。
   故「库默认值」的真实行为由集成用例覆盖，沙盒只覆盖**语句语义与对象映射**。
2. 物理表副本的外键在模型里指向**逻辑名**（`ocr_correction` → `ocr_result`），
   而生产上那个名字由 DDL 模板渲染成带月份的物理名；sqlite 里无法随物理名解析，
   故沙盒**不建分片表外键**（`include_foreign_key_constraints=[]`，实测可行）。
   外键的真实行为由集成用例与 `test_apply_ddl_mysql.py` 覆盖。
3. sqlite 默认**不校验外键**；只有需要验外键路径的用例才显式
   `PRAGMA foreign_keys=ON` 并把固定表的外键建出来。

## `server_default` 抹除的**一处副作用**（Task 4.5 实测发现，如实登记）

抹掉 `CURRENT_TIMESTAMP(3)` 之后，沙盒里**没有** `created_at` 的库级默认值。
生产上 `ai_task.created_at` 有 `DEFAULT CURRENT_TIMESTAMP(3)`（`er.md` §6.1 L297），
而 `TaskRepo.insert` **要求调用方给非空带时区的 `created_at`**（分表月份由它现算，
Task 3.7 的硬约束）。故两条路径在沙盒里**表现一致**，但**原因不同**：
生产是"给了值所以不触发默认"，沙盒是"默认值被抹了"。
若哪天有人改成不传 `created_at` 指望库兜底，沙盒会以
`NOT NULL constraint failed` 报错、生产会以"月份算不出来"报错——两种都不会静默，
故这个差异**不构成掩盖**，登记在此以免后人误判。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import MetaData, Table, create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.schema import CreateTable

from aicore.repository.models import AiTask, Base, OcrCorrection, OcrResult

#: 沙盒要建的表：(逻辑名, 物理名)。两个月 + 三张分片表的固定名，
#: 用于覆盖「跨月边界」与「同分片 1:1 / 1:N」两类路径。
SANDBOX_TABLES: tuple[tuple[str, str], ...] = (
    ("ai_task", "ai_task_202607"),
    ("ai_task", "ai_task_202608"),
    ("ocr_result", "ocr_result_202607"),
    ("ocr_correction", "ocr_correction_202607"),
)

_MODELS: dict[str, type[Base]] = {
    "ai_task": AiTask,
    "ocr_result": OcrResult,
    "ocr_correction": OcrCorrection,
}


def sandbox_copy(logical: str, physical: str, meta: MetaData) -> Table:
    """把模型里的逻辑表复制成**物理表名**的副本（列定义全部来自 `models.py`）。"""
    copy = _MODELS[logical].__table__.to_metadata(meta, name=physical)
    for column in copy.columns:
        default = column.server_default
        # 只抹时间类默认值：`DEFAULT (CURRENT_TIMESTAMP(3))` 是 sqlite 的唯一硬伤。
        if default is not None and "CURRENT_TIMESTAMP" in str(default.arg).upper():
            column.server_default = None
    return copy


def _enable_sqlite_foreign_keys(dbapi_connection: Any, _record: Any) -> None:
    """sqlite 默认**不**校验外键；要验外键路径时必须显式打开。"""
    dbapi_connection.execute("PRAGMA foreign_keys=ON")


def build_sqlite_engine(
    tables: tuple[tuple[str, str], ...] = SANDBOX_TABLES,
    *,
    enforce_foreign_keys: bool = False,
) -> Engine:
    """建 sqlite 内存库并按**物理名**建表。

    ## 必须 `StaticPool` + `check_same_thread=False`（Task 4.5 实测，欠了会静默失效）

    裸 `create_engine("sqlite://")` 的默认池是 **`SingletonThreadPool`**：
    **每个线程一条独立连接**，而 sqlite 的内存库是**连接级**的——
    于是"每线程"就等于"每个线程一个空库"。

    实测（Task 4.5 实现者复现、控制者复核）：

    ```
    池类型       = SingletonThreadPool
    主线程表数   = ['ai_task_202607', 'ai_task_202608',
                    'ocr_correction_202607', 'ocr_result_202607']
    工作线程表数 = []        ← 空库
    ```

    而 FastAPI 的**同步路由**跑在「AnyIO worker thread」、`TestClient` 经 portal 线程驱动应用
    ——**都不是 pytest 主线程**。故主线程建的表，路由侧一条也看不到
    （真实 SQL 会报 `no such table`）。

    `StaticPool` 让所有线程共用**同一条**连接，从而共用同一个内存库；
    `check_same_thread=False` 是 sqlite3 驱动层的对应开关（否则跨线程用连接直接抛
    `ProgrammingError`）。

    **为什么这条必须写进 docstring 而不是只改一行**：它的失效形态是
    **「主线程看得到、路由看不到」**——一个只在"经过真应用发请求"时才暴露的差异。
    只在主线程直接读写引擎的用例会**全绿**，从而把这道坎藏起来
    （控制者的第一版夹具自证正是这样绿的：它绕过了路由线程这一环）。
    `tests/api/test_deps.py::test_sandbox_tables_are_visible_from_a_route` 现在
    **经真组合根发一条真请求**来守这条。

    `enforce_foreign_keys=True` 时打开 `PRAGMA foreign_keys`，
    用于验证「外键失败 MUST NOT 被误报成业务冲突」这类路径。
    """
    engine = create_engine(
        "sqlite://",
        poolclass=StaticPool,
        # sqlite3 默认拒跨线程使用连接；StaticPool 下所有线程共用一条，故必须关掉该检查。
        connect_args={"check_same_thread": False},
    )
    if enforce_foreign_keys:
        event.listen(engine, "connect", _enable_sqlite_foreign_keys)
    meta = MetaData()
    copies = [(logical, sandbox_copy(logical, physical, meta)) for logical, physical in tables]
    with engine.begin() as conn:
        for _logical, table in copies:
            conn.exec_driver_sql(
                str(
                    CreateTable(
                        table,
                        include_foreign_key_constraints=[],
                    ).compile(dialect=conn.dialect)
                )
            )
    return engine
