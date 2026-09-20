"""`repository/session.py`（会话与连接池，Task 3.4）的契约用例。

分两段：

- **默认跑**（不连数据库）：池参数随配置、读写引擎分离与回落、口令不泄漏、空串不回落、
  会话生命周期（内存 SQLite）、写后立即读标记与只读守卫、`dispose` 幂等，
  外加三条**源码扫描**用例（池参数不得写死、不得引入异步会话 API、repository 的
  导入边界）——这三条把硬约束从"文档要求"变成"改坏了就变红"；
- **`@pytest.mark.integration`**（默认不跑）：真实 `aicore_test` 上的写后立即读与
  双引擎 / 双连接池。连不上 MUST 显式 `skip` 并说明原因（静默通过等于门禁失效）。

**本机只有一个 MySQL 实例（没有真实从库）**：故"读写分离"在本任务里只验到
**地址可配**与"两个引擎 / 两个池"，主从延迟**未验证**——集成用例里只读引擎连的是同一实例。

禁止项：MUST NOT 出现 `sleep`（等待一律走断言）；口令 MUST NOT 硬编码（用一眼假的哨兵）。
"""

from __future__ import annotations

import ast
import logging
import os
import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import QueuePool

from aicore.core.config import Settings
from aicore.core.errors import PARAM_FORMAT_CODE, AiCoreError, ParamError
from aicore.repository import session as session_module
from aicore.repository.session import (
    EngineFactory,
    build_engine,
    dispose_engines,
    mark_write_then_read,
    session_needs_primary,
    session_scope,
)

#: 口令哨兵：一眼假、且只在本文件里出现。出现"哨兵进可打印形式"即用例失败。
SENTINEL_PASSWORD = "SENTINEL_PW_9f3a"

#: 只读地址哨兵：与主库地址**不同**，使"读 / 写引擎确实分开"这条断言有判别力。
REPLICA_HOST = "10.20.30.40"
REPLICA_PORT = 3307

#: 模块源码（源码扫描用例用）。路径取自模块自身，避免与目录结构漂移。
SESSION_SOURCE = Path(session_module.__file__).read_text(encoding="utf-8")

#: 演练库（集成用例用；MUST NOT `DROP DATABASE`，只 DROP 自己建的临时表）。
DRILL_DATABASE = "aicore_test"

#: 临时表名按**进程**唯一：本文件可能与别的用例/别的 subagent 并发跑，
#: 固定表名会让两个进程互相 DROP 对手刚建的表（Task 3.1 实测过这种互扰）。
TEMP_TABLE = f"tmp_session_probe_{os.getpid()}"

#: 硬约束 4 的受检关键字：池容量两项只允许来自 `settings`。
_POOL_KEYWORD_NAMES = ("pool_size", "max_overflow")


def _settings(**overrides: object) -> Settings:
    """测试用配置：取值全是 `test_*` / 哨兵占位符，且 `_env_file=None` 不读本地 `.env`。

    显式传 `mysql_readonly_host=None` 等默认值（而不是依赖进程环境）：
    `conftest` 默认注入了一个只读地址，本文件需要在两条分支上都可复现。
    """
    base: dict[str, object] = {
        "mysql_host": "127.0.0.1",
        "mysql_port": 3306,
        "mysql_user": "test_user",
        "mysql_password": SENTINEL_PASSWORD,
        "mysql_database": DRILL_DATABASE,
        "mysql_pool_size": 5,
        "mysql_max_overflow": 10,
        "mysql_readonly_host": None,
        "mysql_readonly_port": None,
        "redis_host": "127.0.0.1",
        "provider": "mock",
        "internal_token": "test_internal_token",
        "daily_quota_per_account": 1000,
        "daily_budget_total": 100000,
    }
    base.update(overrides)
    return Settings(_env_file=None, **base)


def _sqlite_engine() -> Engine:
    """内存 SQLite 引擎：只用来验证会话生命周期。

    MUST NOT 用真实 MySQL 验这两条（工单明确要求）：提交 / 回滚 / 关闭是 SQLAlchemy 的
    会话语义，与方言无关；内存库更快、且不依赖任何外部服务。

    默认池是 `SingletonThreadPool`：同一线程内**复用同一条 DBAPI 连接**，
    故「上一个会话提交的数据，下一个会话看得见」——这正是提交 / 回滚用例需要的前提。
    """
    return create_engine("sqlite://")


def _sqlite_queue_pool_engine() -> Engine:
    """内存 SQLite + `QueuePool`：用来观察「连接是否归还连接池」。

    `checkedout()` 是 `QueuePool` 的公开 API（`SingletonThreadPool` 没有它），
    而生产用的 MySQL 池正是 `QueuePool`，故用同一个池类型做这条断言才有代表性。
    """
    return create_engine("sqlite://", poolclass=QueuePool)


def _call_keyword_values() -> dict[str, list[str]]:
    """收集源码里 `pool_size=` / `max_overflow=` 关键字实参的取值（`ast.unparse` 后的文本）。

    **只在 AST 的调用实参上找**：注释与 docstring 里提到 `pool_size=5`（本模块 docstring
    正是拿它举例说明「不许这么写」）不算违规——被扫描的对象是代码，不是文字。
    """
    found: dict[str, list[str]] = {}
    for node in ast.walk(ast.parse(SESSION_SOURCE)):
        if not isinstance(node, ast.Call):
            continue
        for keyword in node.keywords:
            if keyword.arg in _POOL_KEYWORD_NAMES:
                found.setdefault(keyword.arg, []).append(ast.unparse(keyword.value))
    return found


def _identifiers() -> set[str]:
    """源码里出现的**标识符**集合（注释与 docstring 的文本都不算）。"""
    names: set[str] = set()
    for node in ast.walk(ast.parse(SESSION_SOURCE)):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.keyword) and node.arg:
            names.add(node.arg)
    return names


# ---------------------------------------------------------------------------
# 硬约束的源码扫描（把"改了实现就静默违反"变成"用例变红"）
# ---------------------------------------------------------------------------


def test_pool_parameters_are_never_literal_in_the_source() -> None:
    """硬约束：池参数只从配置读，源码里 MUST NOT 出现数字字面量。

    扫描的是**代码**（AST 的调用实参），注释与 docstring 里拿 `pool_size=5` 举例说明
    「不许这么写」不算违规——否则这条用例会因为它自己的说明文字而变红。
    """
    literals = {
        name: values
        for name, values in _call_keyword_values().items()
        if any(re.fullmatch(r"\d+", value) for value in values)
    }
    assert not literals, (
        f"session.py 里出现池参数字面量 {literals}：容量是部署决策，"
        f"必须取 Settings.mysql_pool_size / mysql_max_overflow"
    )


def test_pool_parameters_are_passed_from_settings() -> None:
    """阳性对照：两个池参数**确实**作为关键字实参传给了建引擎的调用，取值来自 settings。

    没有这一步，上面那条"没有字面量"可能只是因为参数压根没传（静默用默认值）——
    那正是硬约束 4 要防的另一半。
    """
    values = _call_keyword_values()

    assert values.get("pool_size") == ["settings.mysql_pool_size"], values
    assert values.get("max_overflow") == ["settings.mysql_max_overflow"], values


@pytest.mark.parametrize(
    "forbidden",
    ["async_sessionmaker", "AsyncEngine", "create_async_engine", "AsyncSession"],
)
def test_no_async_session_api_in_the_source(forbidden: str) -> None:
    """硬约束 1：同步会话 + 线程池（spec §5.4 已定档），异步会话 API 一律不得出现。

    同样只看标识符：模块 docstring 里写着「MUST NOT 引入 `AsyncEngine`」，
    那是说明文字，不是用法。
    """
    assert forbidden not in _identifiers(), (
        f"session.py 出现异步会话 API {forbidden}：本服务的会话是同步的"
        f"（分表动态 SQL 直观、规避「会话跨事件循环」陷阱）"
    )


def test_repository_imports_stay_within_the_contract() -> None:
    """硬约束 7：`repository` 只可 import `aicore.core.*` / 同包 / `sqlalchemy` / 标准库。

    import-linter 守的是"repository 不得反向依赖 service"这条大边界；本用例把
    「这个模块具体能碰什么」也钉住：一旦有人在这里 import `aicore.provider` 或
    `aicore.service`，用例当场变红（而不是等到分层检查在别处报出来）。
    """
    stdlib_allowed = {
        "__future__",
        "collections",
        "collections.abc",
        "contextlib",
        "logging",
        "typing",
    }
    imported: set[str] = set()
    for node in ast.walk(ast.parse(SESSION_SOURCE)):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    offenders = [
        name
        for name in imported
        if not (
            name.split(".")[0] in stdlib_allowed
            or name.split(".")[0] == "sqlalchemy"
            or name.startswith("aicore.core")
            or name.startswith("aicore.repository")
        )
    ]
    assert not offenders, f"session.py 引入了越界依赖：{sorted(offenders)}"


# ---------------------------------------------------------------------------
# 池参数（硬约束 4）
# ---------------------------------------------------------------------------


def test_pool_parameters_come_from_settings_not_literals() -> None:
    """池大小 / 溢出上限随配置变化：两个不同配置 → 两个不同的池参数。

    `pool.size()` 是公开 API；`_max_overflow` 是 QueuePool 上**唯一**能读到溢出上限的
    属性（带下划线，工单明确要求断言它）。两组不同取值一起断言，才能证明值来自配置
    而不是某个恰好相等的常量。
    """
    small = EngineFactory(_settings(mysql_pool_size=3, mysql_max_overflow=2))
    large = EngineFactory(_settings(mysql_pool_size=17, mysql_max_overflow=0))
    try:
        assert small.write_engine.pool.size() == 3
        assert small.write_engine.pool._max_overflow == 2
        assert large.write_engine.pool.size() == 17
        assert large.write_engine.pool._max_overflow == 0
        # 只读引擎走同一份配置（两个池各自独立，故要分别断言）。
        assert large.read_engine.pool.size() == 17
        assert large.read_engine.pool._max_overflow == 0
    finally:
        small.dispose()
        large.dispose()


# ---------------------------------------------------------------------------
# 读写引擎分离与回落（`er.md` §5.5 的可配部分）
# ---------------------------------------------------------------------------


def test_read_engine_targets_the_configured_replica() -> None:
    """配了只读地址：读 / 写引擎的 URL 不同，且回落标志为 False。"""
    factory = EngineFactory(
        _settings(mysql_readonly_host=REPLICA_HOST, mysql_readonly_port=REPLICA_PORT)
    )
    try:
        assert str(factory.read_engine.url) != str(factory.write_engine.url)
        assert factory.read_engine.url.host == REPLICA_HOST
        assert factory.read_engine.url.port == REPLICA_PORT
        assert factory.write_engine.url.host == "127.0.0.1"
        assert factory.read_target_is_primary is False
    finally:
        factory.dispose()


def test_read_engine_falls_back_to_primary_when_no_replica_is_configured() -> None:
    """没配只读地址：只读回落主库——地址相同，但**仍是两个不同的 Engine / 池**。

    两件事都要成立才算对：① 地址确实回落（可断言，见 `read_target_is_primary`）；
    ② 回落不是"把写引擎拿来复用"（那会让只读流量与写流量抢同一条池，
    日后接上真从库时"悄悄还是走主库"就没人发现）。
    """
    factory = EngineFactory(_settings(mysql_readonly_host=None))
    try:
        assert factory.read_target_is_primary is True
        assert factory.read_engine.url.host == factory.write_engine.url.host
        assert factory.read_engine.url.port == factory.write_engine.url.port
        assert factory.read_engine is not factory.write_engine
        assert factory.read_engine.pool is not factory.write_engine.pool
    finally:
        factory.dispose()


def test_primary_read_engine_is_the_write_engine() -> None:
    """写后立即读用的主库只读引擎**就是**写引擎（同一对象、同一条池）——意图写显式。"""
    factory = EngineFactory(_settings())
    try:
        assert factory.primary_read_engine is factory.write_engine
    finally:
        factory.dispose()


# ---------------------------------------------------------------------------
# 口令安全（硬约束 5）
# ---------------------------------------------------------------------------


def test_password_never_appears_in_printable_forms() -> None:
    """口令 MUST NOT 出现在 engine 的 repr / url 以及两个 DSN 里。

    阴性对照（本用例的判别力所在）：`render_as_string(hide_password=False)` 里**必须**
    看得见口令——否则"没出现"可能只是因为口令压根没进 URL，断言就是空的。
    """
    settings = _settings(mysql_readonly_host=REPLICA_HOST, mysql_readonly_port=REPLICA_PORT)
    factory = EngineFactory(settings)
    try:
        assert settings.mysql_password == SENTINEL_PASSWORD, "哨兵没生效，本用例会退化成空断言"
        printable = {
            "repr(write_engine)": repr(factory.write_engine),
            "repr(read_engine)": repr(factory.read_engine),
            "str(write_engine.url)": str(factory.write_engine.url),
            "str(read_engine.url)": str(factory.read_engine.url),
            "settings.mysql_dsn": settings.mysql_dsn,
            "settings.mysql_read_dsn": settings.mysql_read_dsn,
        }
        leaked = [name for name, figure in printable.items() if SENTINEL_PASSWORD in figure]
        assert not leaked, f"口令出现在可打印形式里：{leaked}"
        assert SENTINEL_PASSWORD in factory.write_engine.url.render_as_string(hide_password=False)
    finally:
        factory.dispose()


def test_read_target_is_visible_in_the_assembly_log(caplog: pytest.LogCaptureFixture) -> None:
    """回落主库 MUST 在日志/自检里看得见（不许把"回落"伪装成"已分离"）。

    本机只有一个实例，回落是常态；这条日志就是运维判断"只读到底连哪里"的依据。
    同时断言口令不进日志——日志是本模块唯一允许"输出配置"的地方。
    """
    caplog.set_level(logging.INFO, logger=session_module.__name__)
    settings = _settings(mysql_readonly_host=None)
    factory = EngineFactory(settings)
    try:
        lines = [
            record.getMessage()
            for record in caplog.records
            if record.name == session_module.__name__
        ]
        assert lines, "EngineFactory 装配时没有任何日志：只读目标无从核对"
        text_all = "\n".join(lines)
        assert settings.mysql_dsn in text_all
        assert settings.mysql_read_dsn in text_all
        assert "回落主库" in text_all, f"未配置从库时日志必须写明回落，实际：{text_all}"
        assert SENTINEL_PASSWORD not in text_all, "装配日志泄漏了口令"
    finally:
        factory.dispose()


# ---------------------------------------------------------------------------
# 空串 MUST NOT 静默回落（工单 §新增字段的硬要求）
# ---------------------------------------------------------------------------


def test_blank_readonly_host_is_rejected_at_construction() -> None:
    """`mysql_readonly_host=""` 在构造期就被拒——回落只认 `None`。"""
    with pytest.raises(ValidationError) as excinfo:
        _settings(mysql_readonly_host="")

    assert ("mysql_readonly_host",) in [err["loc"] for err in excinfo.value.errors()]


# ---------------------------------------------------------------------------
# 会话生命周期（内存 SQLite；不连真实 MySQL）
# ---------------------------------------------------------------------------


def test_session_scope_closes_the_session_on_normal_exit() -> None:
    """正常退出后会话已关闭：连接归还连接池、会话上没有活动事务。

    **`session.is_active is False` 这条工单断言在 SQLAlchemy 2.0.54 上不成立**（实测）：
    `is_active` 的语义是「会话不处于部分回滚态」，`close()` 之后它仍为 `True`。
    故「已关闭」改用两条可观察事实证明，其中 `pool.checkedout()` 是关键的一条——
    会话没关就会一直占着连接，池的借出计数不会归零（这正是连接泄漏的形状）。

    池类型刻意用 `QueuePool`：`SingletonThreadPool` 没有 `checkedout()`，
    而生产上的 MySQL 池就是 `QueuePool`，同类型断言才有代表性。
    """
    engine = _sqlite_queue_pool_engine()
    try:
        with session_scope(engine) as session:
            session.execute(text("CREATE TABLE probe (id INTEGER)"))
            assert session.in_transaction() is True, "体内应当有活动事务"
            assert engine.pool.checkedout() == 1, "体内应当占着一条连接"

        assert engine.pool.checkedout() == 0, "退出后连接没归还连接池（会话没关）"
        assert session.in_transaction() is False
    finally:
        engine.dispose()


def test_session_scope_commits_the_work_on_success() -> None:
    """正常退出即提交：写会话的语义基础（否则"提交后立即轮询"根本查不到数据）。"""
    engine = _sqlite_engine()
    try:
        with session_scope(engine) as session:
            session.execute(text("CREATE TABLE probe (id INTEGER)"))
        with session_scope(engine) as session:
            session.execute(text("INSERT INTO probe (id) VALUES (7)"))
        with session_scope(engine) as session:
            rows = session.execute(text("SELECT id FROM probe")).scalars().all()

        assert list(rows) == [7]
    finally:
        engine.dispose()


def test_session_scope_rolls_back_when_the_body_raises() -> None:
    """体内抛异常 MUST 回滚：未提交的写入不得留在库里。"""

    class _BodyError(Exception):
        """体内异常（只为触发回滚路径）。"""

    engine = _sqlite_engine()
    try:
        with session_scope(engine) as session:
            session.execute(text("CREATE TABLE probe (id INTEGER)"))

        with pytest.raises(_BodyError), session_scope(engine) as session:
            session.execute(text("INSERT INTO probe (id) VALUES (1)"))
            raise _BodyError

        with session_scope(engine) as session:
            remaining = session.execute(text("SELECT COUNT(*) FROM probe")).scalar_one()

        assert remaining == 0, "体内抛异常后数据仍在：会话没有回滚"
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# 写后立即读（`er.md` §5.5）：标记 + 只读路径守卫
# ---------------------------------------------------------------------------


def test_write_then_read_mark_is_visible_on_the_session() -> None:
    """`mark_write_then_read` 在 `session.info` 上打标记，`session_needs_primary` 读它。"""
    engine = _sqlite_engine()
    try:
        with session_scope(engine) as session:
            assert session_needs_primary(session) is False, "新会话不该带写后立即读标记"
            mark_write_then_read(session)
            assert session_needs_primary(session) is True
    finally:
        engine.dispose()


def test_read_session_serves_a_clean_session() -> None:
    """没带标记时只读会话正常工作，且绑定的确实是只读引擎。"""
    factory = EngineFactory(_settings(mysql_readonly_host=REPLICA_HOST))
    try:
        with factory.read_session() as session:
            assert session.get_bind() is factory.read_engine
            assert session_needs_primary(session) is False
        with factory.write_session() as session:
            assert session.get_bind() is factory.write_engine
        with factory.primary_read_session() as session:
            assert session.get_bind() is factory.primary_read_engine
    finally:
        factory.dispose()


def test_read_session_rejects_a_session_carrying_the_mark(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """带「写后立即读」标记的会话落到只读路径 MUST 抛错，而不是从从库读旧值。

    构造方式：把会话工厂（`_open_session`）换成"造出来就带标记"的实现——
    `read_session()` 在 yield 之前检查，故用例不必连库（工单允许 monkeypatch）。
    """
    factory = EngineFactory(_settings(mysql_readonly_host=REPLICA_HOST))
    marked = Session(bind=factory.read_engine)
    mark_write_then_read(marked)
    monkeypatch.setattr(session_module, "_open_session", lambda engine: marked)
    try:
        with pytest.raises(ParamError) as excinfo, factory.read_session():
            pass  # pragma: no cover —— 进不来：read_session 在 yield 前就拒了

        assert excinfo.value.code == PARAM_FORMAT_CODE
        assert isinstance(excinfo.value, AiCoreError), "必须是业务异常子类（走统一信封）"
        assert "primary_read_session" in str(excinfo.value), "错误消息必须给出正确的替代入口"
        # 被拒的会话同样要关掉：否则每次误用都漏一条连接。
        assert marked.in_transaction() is False
    finally:
        factory.dispose()


# ---------------------------------------------------------------------------
# 引擎生命周期（硬约束 6）
# ---------------------------------------------------------------------------


def test_dispose_is_idempotent() -> None:
    """`dispose()` 幂等：重复调用不报错、不重复释放。"""
    factory = EngineFactory(_settings())
    factory.dispose()
    factory.dispose()


def test_dispose_engines_accepts_the_same_engine_twice() -> None:
    """`dispose_engines` 对同一引擎重复传入安全（`Engine.dispose()` 自身也是幂等的）。"""
    engine = build_engine(_settings(), read_only=False)
    dispose_engines(engine, engine)


def test_build_engine_read_only_flag_switches_the_address() -> None:
    """`build_engine` 的 `read_only` 开关：两个取值分别落到写地址与只读地址。"""
    settings = _settings(mysql_readonly_host=REPLICA_HOST, mysql_readonly_port=REPLICA_PORT)
    write_engine = build_engine(settings, read_only=False)
    read_engine = build_engine(settings, read_only=True)
    try:
        assert (write_engine.url.host, write_engine.url.port) == ("127.0.0.1", 3306)
        assert (read_engine.url.host, read_engine.url.port) == (REPLICA_HOST, REPLICA_PORT)
    finally:
        dispose_engines(write_engine, read_engine)


# ---------------------------------------------------------------------------
# 真实 MySQL（默认不跑）：`-m integration` 才执行
# ---------------------------------------------------------------------------


def _integration_settings() -> Settings:
    """集成用例的配置：MySQL 连接信息取 `DSH_IT_MYSQL_*`（与 Task 3.1 同一约定）。

    口令只从 `DSH_IT_MYSQL_PASSWORD` 取（`conftest` 会从本机已被 gitignore 的 `.env`
    回填）；取不到即 `skip`，而不是把凭据写进版本库换一次"绿灯"。
    """
    password = os.environ.get("DSH_IT_MYSQL_PASSWORD")
    if not password:
        pytest.skip(
            "未配置 DSH_IT_MYSQL_PASSWORD（或 .env 里的 AICORE_MYSQL_PASSWORD）："
            "集成用例需要真实演练库凭据；凭据 MUST NOT 硬编码进仓库"
        )
    return _settings(
        mysql_host=os.environ.get("DSH_IT_MYSQL_HOST", "127.0.0.1"),
        mysql_port=int(os.environ.get("DSH_IT_MYSQL_PORT", "3306")),
        mysql_user=os.environ.get("DSH_IT_MYSQL_USER", "aicore_dev"),
        mysql_password=password,
        mysql_database=os.environ.get("DSH_IT_MYSQL_DATABASE", DRILL_DATABASE),
        # 本机只有**一个**实例：只读地址只能配成同一个地址。这验证的是"地址可配"，
        # 主从延迟与从库一致性**未验证**（见模块 docstring）。
        mysql_readonly_host=os.environ.get("DSH_IT_MYSQL_HOST", "127.0.0.1"),
        mysql_readonly_port=int(os.environ.get("DSH_IT_MYSQL_PORT", "3306")),
    )


def _skip_unless_mysql_reachable(engine: Engine) -> None:
    """连不上就**显式跳过**（含原因），而不是随机失败或静默通过。"""
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:
        pytest.skip(
            f"需要真实 MySQL（{DRILL_DATABASE}@127.0.0.1:3306）才能验证会话与连接池："
            f"{type(exc).__name__}: {exc}"
        )


def _drop_temp_table(factory: EngineFactory) -> None:
    """只清理本用例自己建的临时表（MUST NOT 碰别的表、MUST NOT `DROP DATABASE`）。"""
    with factory.write_session() as session:
        session.execute(text(f"DROP TABLE IF EXISTS `{TEMP_TABLE}`"))


@pytest.fixture
def drill_factory() -> Iterator[EngineFactory]:
    """演练库上的引擎工厂（用例结束无条件释放连接池）。"""
    factory = EngineFactory(_integration_settings())
    try:
        yield factory
    finally:
        factory.dispose()


@pytest.mark.integration
def test_write_then_primary_read_sees_the_written_row(drill_factory: EngineFactory) -> None:
    """写会话写入 → `primary_read_session()` 立即读回：**同一事务边界内可见**。

    这条覆盖 `er.md` §5.5 的「写后立即读强制走主库」：写完立刻读不得经过从库
    （从库有延迟，会读到旧状态）；用例不做任何等待——若真走了从库，这里读不到就该失败，
    而不是靠 `sleep` 掩盖。末尾顺带断言写会话把连接归还了池（生产池就是 `QueuePool`）。
    """
    _skip_unless_mysql_reachable(drill_factory.write_engine)
    _drop_temp_table(drill_factory)
    try:
        with drill_factory.write_session() as session:
            session.execute(
                text(f"CREATE TABLE `{TEMP_TABLE}` (id INT PRIMARY KEY, note VARCHAR(32))")
            )
            session.execute(
                text(f"INSERT INTO `{TEMP_TABLE}` (id, note) VALUES (1, 'write-then-read')")
            )
            assert drill_factory.write_engine.pool.checkedout() == 1, "体内应当占着一条连接"

        assert drill_factory.write_engine.pool.checkedout() == 0, "写会话退出后连接没归还池"

        with drill_factory.primary_read_session() as session:
            rows = session.execute(text(f"SELECT note FROM `{TEMP_TABLE}` WHERE id = 1")).all()

        assert rows == [("write-then-read",)], f"写后立即读没读到自己刚写的数据：{rows}"
    finally:
        _drop_temp_table(drill_factory)


@pytest.mark.integration
def test_read_and_write_sessions_use_distinct_engines_and_pools(
    drill_factory: EngineFactory,
) -> None:
    """只读会话与写会话绑定**不同的 Engine 对象与不同的连接池**，且两者都能真连库。

    只读引擎在本机连的是同一个实例（没有真实从库），故这条只证明"两条池确实分开了"：
    接上真从库时地址改成从库即可，不需要再动代码。
    """
    _skip_unless_mysql_reachable(drill_factory.write_engine)
    with (
        drill_factory.read_session() as read_session,
        drill_factory.write_session() as write_session,
    ):
        read_bind = read_session.get_bind()
        write_bind = write_session.get_bind()

        assert read_bind is not write_bind
        assert read_bind is drill_factory.read_engine
        assert write_bind is drill_factory.write_engine
        assert read_bind.pool is not write_bind.pool
        assert read_session.execute(text("SELECT 1")).scalar_one() == 1
        assert write_session.execute(text("SELECT 1")).scalar_one() == 1
