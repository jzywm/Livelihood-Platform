"""全局测试夹具。

约定：测试内 MUST NOT 出现任意 sleep；等待一律走轮询断言或注入的时钟。
"""

from __future__ import annotations

import inspect
import os
import socket
import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from dotenv import dotenv_values
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from tests.support.db_sandbox import build_sqlite_engine

# ---------------------------------------------------------------------------
# 测试环境变量注入（Task 2.1 起必需）
#
# 为什么：`Settings` 的必填项**刻意不给默认值**（默认值会把配置错误隐藏到运行时），
# 没有可用配置时 `Settings()` 直接抛 ValidationError。CI 与全新 checkout 都没有
# `services/aicore/.env`，本地开发者则可能有且内容各不相同——若依赖 `.env`，
# 测试会随环境漂移、甚至在收集阶段就失败。故这里注入一组 test_* 占位值，
# 让**注入的环境变量**成为测试的唯一配置来源：进程环境在 pydantic-settings 中
# 优先于 `.env` 文件，本地即使存在 `.env` 也以这里为准。
#
# 位置约束（MUST）：本块必须在任何 `aicore` 导入之前。pytest 先导入 conftest、
# 后导入测试模块，而测试模块经 `aicore.main` 触发配置读取；本块一旦下移到文件尾部，
# 注入就等于没发生。下面的 `from aicore.main import create_app` 因此带 E402 豁免。
#
# 用 `setdefault` 而非赋值：真实环境（CI 指向真实 MySQL 等）仍可覆盖，
# 注入只兜「本机什么都没配」这一种情况。
#
# 值一律是 test_* 占位符，MUST NOT 出现真实凭据。
# ---------------------------------------------------------------------------
_TEST_ENV_DEFAULTS: dict[str, str] = {
    "AICORE_ENV": "test",
    "AICORE_MYSQL_HOST": "127.0.0.1",
    "AICORE_MYSQL_USER": "test_user",
    "AICORE_MYSQL_PASSWORD": "test_password",
    "AICORE_MYSQL_DATABASE": "aicore_test",
    # 连接池两项是 Task 3.4 起的**必填**字段（容量是部署决策，刻意不给默认值）：
    # 不注入的话，任何「清空 AICORE_* 再构造 Settings」的用例都会变成缺必填项而报错。
    "AICORE_MYSQL_POOL_SIZE": "5",
    "AICORE_MYSQL_MAX_OVERFLOW": "10",
    # 只读地址可空，但这里**注入一个具体地址**：让「有独立从库」这条分支成为默认环境，
    # 用例只在需要时显式传 `mysql_readonly_host=None` 去覆盖「回落主库」那条分支。
    # 注入值与主库同址（本机只有一个实例），但配置上是分开的两个地址——这正是
    # read_target_is_primary 要表达的区别：它看的是「配没配」，不是「地址是否相同」。
    "AICORE_MYSQL_READONLY_HOST": "127.0.0.1",
    "AICORE_MYSQL_READONLY_PORT": "3306",
    "AICORE_REDIS_HOST": "127.0.0.1",
    "AICORE_PROVIDER": "mock",
    "AICORE_INTERNAL_TOKEN": "test_internal_token",
    "AICORE_DAILY_QUOTA_PER_ACCOUNT": "1000",
    "AICORE_DAILY_BUDGET_TOTAL": "100000",
}

for _key, _value in _TEST_ENV_DEFAULTS.items():
    os.environ.setdefault(_key, _value)

# ---------------------------------------------------------------------------
# 真实 MySQL 的集成测试**专用的另一组环境变量**（Task 3.1 FIX-5 起必需）
#
# 两个问题要同时解决，故前缀既不能复用也不能"看起来像"应用配置：
#
# ① **不能复用 `AICORE_MYSQL_*`**：上面那块注入在 CI 与全新 checkout 里**必然生效**，
#    于是集成测试读 `AICORE_MYSQL_USER` 只会拿到 `test_user`，连库失败 → 走 `pytest.skip`
#    → **整条"真实库结构"门禁静默失效**。实测现场（skip 原因把它点破了）：
#        SKIPPED ... 需要真实 MySQL ... (1045, "Access denied for user 'test_user'@'localhost'")
#
# ② **更不能叫 `AICORE_TEST_MYSQL_*`**：`core/config.py` 的 `_UnknownEnvVarSource` 会
#    **拒绝任何未声明的 `AICORE_*` 变量**（Task 2.1 的防线，本身完全正确）。用它做集成测试
#    变量名会让每次应用启动都撞上"Extra inputs are not permitted" → `ConfigRejected`。
#    实测：全量套件 35 failed / 63 errors，阻断项正是这 5 个变量名。
#    **那不是防线太严，是命名侵入了应用配置的命名空间。**
#
# 故用**完全独立的前缀** `DSH_IT_MYSQL_*`（DSH integration-test）：既绕开应用配置命名空间，
# 又从名字上表明"这不是应用配置"。
#
# **口令不入库（安全红线）**：`DSH_IT_MYSQL_PASSWORD` MUST NOT 在本文件里给默认值——
# 那等于把凭据写进版本库。改为：
#   ① 显式设了 `DSH_IT_MYSQL_PASSWORD` 就用它；
#   ② 否则回落到 `AICORE_MYSQL_PASSWORD`（本机开发凭据只存在于**已被 gitignore 的 `.env`**）；
#   ③ 两者都没有 → 留空，集成用例的连通性探测会**显式 skip** 并说明缺哪个变量。
# 只回落到"口令"一项而不整体复用 `AICORE_MYSQL_*`：host/user/database 仍取演练库的专用缺省值，
# 否则又会退回上面①那个"假凭据导致假 skip"的坑。
# ---------------------------------------------------------------------------
_INTEGRATION_ENV_DEFAULTS: dict[str, str] = {
    "DSH_IT_MYSQL_HOST": "127.0.0.1",
    "DSH_IT_MYSQL_PORT": "3306",
    "DSH_IT_MYSQL_USER": "aicore_dev",
    "DSH_IT_MYSQL_DATABASE": "aicore_test",
}

for _key, _value in _INTEGRATION_ENV_DEFAULTS.items():
    os.environ.setdefault(_key, _value)

# 口令只认两个来源，**MUST NOT 有硬编码默认值**（那是把凭据写进版本库；commit-check 清单 B 红线）：
#   ① 环境里显式设了 `DSH_IT_MYSQL_PASSWORD`；
#   ② 否则读 **`.env` 文件本身**（本机开发凭据只存在于该文件，它已被 gitignore）。
#
# **为什么是"读文件"而不是 `os.environ["AICORE_MYSQL_PASSWORD"]`**（这里踩过一次，记录现场）：
# 本文件顶层那块 `_TEST_ENV_DEFAULTS` 已经把 `AICORE_MYSQL_PASSWORD=test_password` 注入了进程环境，
# 而 pydantic / os.environ **环境变量优先于 `.env`** —— 于是从环境读永远只能拿到 13 字符的
# `test_password`，连库被拒 1045，用例走 skip。实测两边的长度差异：
#     文件里那一行 = 15 字符（真实开发口令）
#     进程环境里 AICORE_MYSQL_PASSWORD = 13 字符（test_password 占位值）
# **本注释刻意不写口令原文**：凭据扫描器不区分"代码里的凭据"与"注释里的取证记录"，
# 写原文会被自己的门禁拦下（实测确实被拦）。
# 故这里用 `dotenv_values()` 直读文件（它**不合并**进程环境），绕开那个优先级陷阱。
if not os.environ.get("DSH_IT_MYSQL_PASSWORD"):
    _env_file = Path(__file__).resolve().parents[1] / ".env"
    if _env_file.is_file():
        _file_password = dotenv_values(_env_file).get("AICORE_MYSQL_PASSWORD")
        if _file_password:
            os.environ["DSH_IT_MYSQL_PASSWORD"] = _file_password

# 都取不到时保持为空：各集成用例自己的连通性探测会 skip 并说明缺哪个变量（不静默通过）。

# ---------------------------------------------------------------------------
# 真实 Redis 的集成测试**专用变量**（Task 4.7）
#
# 与上面 `DSH_IT_MYSQL_*` **完全同形、同一理由**（那段注释里的两个坑对 Redis 一字不差）：
# ① 不能复用 `AICORE_REDIS_*`——本文件顶部已把 `AICORE_REDIS_HOST` 注入成 `127.0.0.1`
#    占位值，集成用例读它只会拿到那个占位值，连不上就 `pytest.skip`，
#    于是「真实 Redis 上的租约语义」这道门禁**静默失效**；
# ② 不能叫 `AICORE_TEST_REDIS_*`——`core/config.py` 的 `_UnknownEnvVarSource` 会拒绝任何
#    未声明的 `AICORE_*` 变量（Task 2.1 的防线），用它会让每次应用启动都撞
#    "Extra inputs are not permitted" → `ConfigRejected`。
#
# **Redis 没有口令**（本机演练实例），故这里不需要 MySQL 那套 `.env` 回填逻辑；
# 若将来 CI 上的 Redis 要密码，届时按同一形状加 `DSH_IT_REDIS_PASSWORD`（**不给默认值**）。
# ---------------------------------------------------------------------------
_INTEGRATION_REDIS_DEFAULTS: dict[str, str] = {
    "DSH_IT_REDIS_HOST": "127.0.0.1",
    "DSH_IT_REDIS_PORT": "6379",
    "DSH_IT_REDIS_DB": "0",
}

for _key, _value in _INTEGRATION_REDIS_DEFAULTS.items():
    os.environ.setdefault(_key, _value)

# 必须在上面注入之后导入：pytest 导入本模块时即完成注入，测试模块随后才 import aicore。
from aicore.main import create_app  # noqa: E402

if TYPE_CHECKING:
    from fastapi.testclient import TestClient


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def app() -> FastAPI:
    return create_app()


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    # TestClient 的导入**必须延后到夹具内部**：它在导入时会触发 starlette 的
    # StarletteDeprecationWarning（httpx/httpx2 迁移提示），而 pytest 应用
    # filterwarnings 的时机在 conftest 导入之后——在模块顶层导入会让该警告绕过过滤器。
    from fastapi.testclient import TestClient

    # 用 with 语句进入上下文，才会真正触发 lifespan（启动钩子）；直接构造不会触发。
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# 会话级「零 socket 建连」守卫（控制者新增，P 阶段评审 B3 的修复）
#
# ## 它补的是哪个洞
#
# 原守卫装在 `tests/unit/test_provider_mock.py` 里（autouse，文件级）。评审用变异测试
# 证明：往 `src/aicore/provider/mock.py` 注入一次真实的 `socket.connect(("192.0.2.1", 9))` 后，
# **mock / real / selector 三个套件 48+51+35 全绿**——因为守卫只在 mock 那个文件里生效，
# 而 `mock.py` 在别的套件运行时**没有任何守卫在听**。
# 「某实现无网络依赖」是**实现的性质**，不是「某一个测试文件的性质」，
# 故守卫的必要作用域是**整个测试会话**，不是单个文件。
#
# ## 为什么必须按调用栈归因，而不是「一律拦下 connect」
#
# Windows 上 `asyncio.new_event_loop()` 会真的发起**一次回环 connect**
# （ProactorEventLoop 的 self-pipe：`_make_self_pipe` → `socketpair` →
# `_fallback_socketpair` → `csock.connect(("127.0.0.1", <随机端口>))`）。
# 控制者实测：`new_event_loop` 期间恰好 1 次 connect。
# pytest-asyncio 在**夹具阶段**就建循环，早于测试体，故「一律拦下」会让全部 async 用例 ERROR。
#
# ## 判据：目标地址 + 调用栈，**两者都要看**（控制者实测后定稿）
#
# 只看调用栈会误判：Windows 上 `asyncio.new_event_loop()` 会真的发起一次回环 connect
# （ProactorEventLoop 的 self-pipe：`_make_self_pipe` → `socketpair` →
# `_fallback_socketpair` → `csock.connect(("127.0.0.1", <随机端口>))`）。
# 控制者实测：`new_event_loop` 期间恰好 1 次 connect，目标是回环。
# 而**归因到帧**时，这次 connect 的最内层「本项目帧」可能落在测试自己的守卫上
# （`test_provider_real.py` 的 `_SocketGuard.connect` 就是一个项目帧）——
# 于是纯栈判据会把它误判成违规。实测证据：会话级守卫上线的第一次全量跑，
# 在 `test_health_stays_bare_and_still_echoes_trace_id` 的 teardown 报出
# **32 次违规，栈全部指向 `test_provider_real.py:269:connect`**（即守卫自己的转发帧）。
#
# 故判据取**合取**：
#   ① 目标**不是**环回 → 才可能是问题（回环流量既出不了本机，也产生不了计费调用）；
#   ② 栈里**出现过**本项目帧 → 才归咎于我们（纯 stdlib 发起的对外连接不是本层的责任）。
# 这条与 `test_provider_real.py` 的 `_SocketGuard` 口径一致（它按目标地址放行环回），
# 但更严一档：它放行一切环回，本守卫在「非环回 + 项目帧」时才判违规。
#
# ## 能力边界（如实登记，MUST NOT 被当作"已验证清白"）
#
# - 环回地址一律放行，故**抓不到**「本机另一个服务被误连」（如误连本机 Redis）——
#   那属于集成测试的正确性问题，不是本守卫的目标；
# - 抓不到「栈内既无本项目帧、也无 stdlib socket 帧」的连接（例如某个 C 扩展直接发起）。
# 后一条缺口在本项目被 `tests/structural/test_source_guards.py` 的规则 5 补上：
# 非 `provider/` 的文件**不得 import** `httpx`/`requests`/`aiohttp`。
# 两条守卫方向互补：项目代码要么在 `provider/` 内（栈内必有项目帧 → 被抓），
# 要么根本不 import 网络库（源码级拦住）。
#
# ### ⚠ 第三条边界：**asyncio 的非环回建连对本守卫不可见**（A6，独立评审实测）
#
# 本守卫 patch 的是 `socket.socket.connect`，而 Windows 上 `ProactorEventLoop` 的
# `create_connection` / `open_connection` 走的是 **C 层 `ConnectEx`**——**根本不经过**
# 被 patch 的那个方法。评审在真机上实测：
#
# ```
# event loop policy: _WindowsProactorEventLoopPolicy
# [A] 异步非环回建连 asyncio.open_connection('192.0.2.1', 9) -> TimeoutError
#     违规记录数 = 0        ← 看不见
# [B] 同步非环回建连 socket.connect('192.0.2.1', 9)          -> TimeoutError
#     违规记录数 = 1        ← 看得见（对照组）
# ```
#
# **这条比上面登记的两条更容易被误信**：项目代码里所有出向调用都是 `async` 的
# （`provider/` 的通道实现、将来任何 `httpx.AsyncClient` 调用），它们**恰好全在这条盲区里**。
# 故本守卫今天能给的保证**比它的名字弱**：它实际覆盖的是**同步**建连路径，
# 异步路径的"无外部模型调用"目前**只**由源码级规则 5（非 `provider/` 不得 import
# `httpx`/`requests`/`aiohttp`）兜住——那条是静态的，看不见"动态拼出来的 URL"之类。
#
# **控制者裁定（Task 4.7 修复轮 A6）**：本轮只**如实登记**这条边界，不要求真修
# （真修要 patch `loop.create_connection` 或挂审计钩子，且必须可判定）。
# 登记它的价值在于：后来者不会因为"守卫是绿的"就以为异步路径已经被证明清白。
# ---------------------------------------------------------------------------

_GUARD_SRC_DIR = Path(__file__).resolve().parents[1] / "src"
_GUARD_PROJECT_TOKENS = (str(_GUARD_SRC_DIR), str(Path(__file__).resolve().parent))


def _guard_is_loopback(address: object) -> bool:
    """目标是否落在环回地址上（self-pipe 与本地测试服务都走这里）。"""
    if not isinstance(address, tuple) or not address:
        return False
    host = str(address[0])
    return host.startswith("127.") or host in {"::1", "localhost", "0.0.0.0", "::"}


def _guard_has_project_frame() -> tuple[bool, tuple[str, ...]]:
    """栈里是否出现过本项目自己的帧（`tests/` 或 `src/aicore/`）。"""
    for frame in inspect.stack()[2:]:
        if any(token in frame.filename for token in _GUARD_PROJECT_TOKENS):
            return True, (f"{Path(frame.filename).name}:{frame.lineno}:{frame.function}",)
    return False, ()


#: 会话级违规账本。**跨文件累积**，故某实现被某个套件触发的问题会被记下来，
#: 而不是随该文件结束一起消失。
_SOCKET_VIOLATIONS: list[tuple[str, tuple[str, ...]]] = []


@pytest.fixture(scope="session", autouse=True)
def _session_socket_guard() -> Iterator[None]:
    """整个测试会话内，**本项目代码 MUST NOT 向环回之外发起 socket 建连**。

    建连一律**透传给真实实现**（不做「拦截即抛错」）：被记录的是事实，
    而不是被截断的行为——于是「有没有发生」与「谁发起的」成为两件可分别复核的事。
    """
    global _SOCKET_VIOLATIONS
    _SOCKET_VIOLATIONS = []
    real_connect = socket.socket.connect

    def _guard_spy(self: socket.socket, address: object) -> object:
        if not _guard_is_loopback(address):
            has_project_frame, frames = _guard_has_project_frame()
            if has_project_frame:
                _SOCKET_VIOLATIONS.append((str(address), frames))
        return real_connect(self, address)

    socket.socket.connect = _guard_spy  # type: ignore[method-assign]
    try:
        yield
    finally:
        socket.socket.connect = real_connect  # type: ignore[method-assign]

    assert _SOCKET_VIOLATIONS == [], (
        f"本项目代码在测试期间向环回之外发起了 {len(_SOCKET_VIOLATIONS)} 次 socket 建连"
        f"（provider 层要求全程无网络依赖）：\n"
        + "\n".join(f"  目标={target} 栈={frames}" for target, frames in _SOCKET_VIOLATIONS)
    )


@pytest.fixture(scope="session")
def socket_violations() -> list[tuple[str, tuple[str, ...]]]:
    """交出会话级违规账本，供「判别力自证」用例自己控制推进节奏。"""
    return _SOCKET_VIOLATIONS


# ---------------------------------------------------------------------------
# 经真组合根 + sqlite 沙盒的 API 夹具（Task 4.5 T1，控制者提供）
#
# ## 它解决什么
#
# `POST /aicore/ocr` 与 `GET /aicore/tasks/{taskId}` 是本服务**第一批需要数据库的真实路由**。
# 测它们要三件事同时成立：
#   ① 经**真组合根**（`create_app()` + 真 lifespan），否则又会绕开装配环节
#      —— L2（`app.state.settings` 未装配）正是靠"桩请求"躲过了一整轮；
#   ② 有**可写的库**，且要能验「写后立即读」；
#   ③ 不依赖外部 MySQL（默认段必须离线可跑，见 `design.md:282` 的离线保证）。
#
# ## 为什么用 sqlite 沙盒 + 替身，而不是真 MySQL
#
# 真 MySQL 路径由 `@pytest.mark.integration` 段覆盖（第 3 组的两段式约定）。
# 默认段用 `tests/support/db_sandbox.py` 的 sqlite 内存库——它按**物理表名**建表，
# 故分片路由这条路是真的在跑；三处"缩水"逐条记在该模块的 docstring 里。
#
# ## 替身的注入点
#
# 注入 `app.state.engine_factory`（**组合根约定的装配点**），而不是 patch 某个函数：
# 装配点是公开契约的一部分，替换它等价于替换部署形态；而 patch 函数会掩盖
# "路由到底从哪里取会话"这件事。
#
# **MUST NOT** 为测试给 `repository.session.EngineFactory` 加"可替换引擎"的入口
# ——那会把测试关切泄进生产类，且让"组合根注入"这条契约失去意义。
# ---------------------------------------------------------------------------


class _SandboxSessionFactory:
    """满足 `api/deps.py` 的 `SessionFactory` 形状的沙盒替身（**只实现被用到的方法**）。

    `write_session` 与 `primary_read_session` 都映射到**同一个** sqlite 引擎：
    沙盒只有一个库，"主/从"之分在这里没有对应物。这一点**不影响**被测行为——
    路由要的语义是"写后立即读能读到刚写的行"，用同一个引擎恰好给出该语义；
    而"轮询 MUST NOT 走从库"这条约束由 `.importlinter`/源码断言与真 MySQL 集成用例覆盖，
    不由本替身覆盖（**如实登记这个边界**，MUST NOT 把它当成"读写分离已验证"）。
    """

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @contextmanager
    def write_session(self) -> Iterator[Session]:
        with Session(self._engine) as session:
            yield session
            session.commit()

    @contextmanager
    def primary_read_session(self) -> Iterator[Session]:
        with Session(self._engine) as session:
            yield session


@pytest.fixture
def sandbox_engine() -> Iterator[Engine]:
    """沙盒引擎（每用例一个内存库，用例间零共享）。"""
    engine = build_sqlite_engine()
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def api_client(sandbox_engine: Engine) -> Iterator[TestClient]:
    """**经真组合根** + sqlite 沙盒的 API 客户端。

    顺序是硬要求：先 `with TestClient(app)` 触发 lifespan（装配 `app.state.settings`），
    **再**覆盖 `app.state.engine_factory` 为沙盒替身。
    反过来（先注入）会在 lifespan 里被真装配覆盖掉，而真装配指向 MySQL。
    """
    from fastapi.testclient import TestClient

    app = create_app()
    with TestClient(app) as client:
        app.state.engine_factory = _SandboxSessionFactory(sandbox_engine)
        yield client


# ---------------------------------------------------------------------------
# 真实 Redis 的集成夹具（Task 4.7）
#
# ## 三条纪律（工单 §3.6）
#
# ① **每个用例换一个 key 前缀**（`aicore:test:<uuid>:`）：聚合门禁里同一台 Redis 上
#    可能同时跑着别的用例/别人手工起的键，固定前缀会让"A 的用例清掉了 B 的键"，
#    表现为随机的偶发失败；
# ② **用例结束清理自己的键**，且 **MUST NOT `FLUSHDB`**——那会清掉同机其它测试的状态
#    （与 MySQL 侧"只 DROP 自己建的演练月分片表，MUST NOT DROP DATABASE"逐字同款）；
# ③ **连不上时显式 skip 并说明**（缺哪个变量、连哪个地址），MUST NOT 静默通过
#    ——静默通过等于让"真实 Redis 上的租约语义"这道门禁在 CI 里永远不生效。
#
# ## 为什么 v1 兼容（`decode_responses` 与二进制前缀的取舍）
#
# 夹具只用 `decode_responses=False` 的裸客户端做三件事：`PING` 探测、`SET`/`PTTL` 这类
# 原始断言、以及按前缀 `SCAN` 清理。**不使用 `FLUSHDB`、不使用 `KEYS`**：
# `SCAN` 是指针式遍历，不会像 `KEYS` 那样在大 keyspace 上阻塞整个 Redis。
# ---------------------------------------------------------------------------

#: 集成用例的 key 前缀根。用例自造的键 MUST 以它开头，夹具的清理也**只**扫它。
REDIS_TEST_PREFIX_ROOT = "aicore:test:"


def redis_integration_target() -> tuple[str, int, int]:
    """`DSH_IT_REDIS_*` → `(host, port, db)`；默认值已由本文件顶部注入。"""
    return (
        os.environ.get("DSH_IT_REDIS_HOST", "127.0.0.1"),
        int(os.environ.get("DSH_IT_REDIS_PORT", "6379")),
        int(os.environ.get("DSH_IT_REDIS_DB", "0")),
    )


def redis_is_available() -> str | None:
    """探测本机 Redis 是否可用：可用返回 `None`，不可用返回**说明原因**的字符串。

    返回"原因"而不是布尔值：调用方（夹具）要把它直接交给 `pytest.skip`，
    让跳过原因在报告里能读出"连的是哪个地址、报的是什么错"。

    用**同步** `redis.Redis` 做探测（而夹具里的客户端是 `redis.asyncio`）：
    探测函数是普通函数、会被夹具与用例在任意位置调用；若它内部要 `await`，
    每个调用点都得改写成协程，而"探活"这件事本身不值得那个复杂度。
    """
    host, port, db = redis_integration_target()
    try:
        import redis as redis_sync

        client = redis_sync.Redis(host=host, port=port, db=db, socket_connect_timeout=1.0)
        try:
            client.ping()
        finally:
            client.close()
    except Exception as exc:
        return (
            f"需要真实 Redis（{host}:{port}/{db}）才能验证租约的原子性与过期语义："
            f"{type(exc).__name__}: {exc}"
        )
    return None


async def _drop_prefixed_keys(client: Any, prefix: str) -> None:
    """按前缀清掉本用例造的全部键（**只 SCAN 自己的前缀**，MUST NOT `KEYS` / `FLUSHDB`）。

    `SCAN` 是指针式遍历：不像 `KEYS` 那样在大 keyspace 上阻塞整个 Redis；
    `FLUSHDB` 会清掉同机其它测试的状态，故被工单 §3.6 明确禁止。
    """
    cursor = 0
    doomed: list[str] = []
    while True:
        cursor, keys = await client.scan(cursor=cursor, match=f"{prefix}*", count=100)
        doomed.extend(keys)
        if cursor == 0:
            break
    if doomed:
        await client.delete(*doomed)


@pytest.fixture
def redis_prefix() -> str:
    """本用例专属的 key 前缀（`aicore:test:<uuid>:`，**每个用例都不同**）。"""
    return f"{REDIS_TEST_PREFIX_ROOT}{uuid.uuid4().hex}:"


@pytest.fixture
async def redis_client(redis_prefix: str) -> AsyncIterator[Any]:
    """真实 Redis 的**原始**客户端（供 `PTTL` / `EXISTS` 这类原始事实断言）。

    连不上时显式 skip（理由见本段开头的纪律 ③）。用例结束按前缀清掉自己造的键。

    写成 `async` 夹具（`pytest-asyncio` 的 `asyncio_mode = "auto"`，见 pyproject）：
    `redis.asyncio` 的 `scan` / `delete` / `aclose` 都必须 `await`，
    而"清理"正是本夹具存在的主要理由——它不是可选的收尾，而是纪律 ② 的落点。
    """
    reason = redis_is_available()
    if reason is not None:
        pytest.skip(reason)
    from redis.asyncio import Redis as AsyncRedis

    host, port, db = redis_integration_target()
    # `decode_responses=True`：集成用例要断言键名/键值这类**文本**事实，
    # 拿到 bytes 会让每条断言都多一次 `.decode()`（漏一次就是"看起来不相等"的假红）。
    client = AsyncRedis(host=host, port=port, db=db, decode_responses=True)
    try:
        yield client
    finally:
        await _drop_prefixed_keys(client, redis_prefix)
        await client.aclose()


@pytest.fixture
async def redis_store(redis_prefix: str) -> AsyncIterator[Any]:
    """`RedisLockStore` 的实例（**用本用例专属的 key 前缀**，用例间零共享）。

    ## 清理写在本夹具里，**不依赖** `redis_client`

    实测踩过一次：清理逻辑原先只在 `redis_client` 的终结器里，而**只有同时请求
    `redis_client` 的用例**才会实例化那个夹具——只请求 `redis_store` 的用例跑完后，
    键**全部留在 Redis 上**（实测：`tests/integration/test_lease_redis.py` 跑完留下
    `:lease` / `:attempts` 残留键）。靠"记得也要请求 `redis_client`"来保证清理迟早会漏，
    故本夹具自带清理。`redis_client` 仍保留自己的清理（用它的用例同样需要兜底），
    两者都只扫**同一个前缀**，重复清理是幂等的。

    `RedisLockStore` 构造**不连接**（`redis.asyncio.Redis` 是惰性的），
    故这里额外做一次 `redis_is_available()` 探测：不探测的话，"Redis 没起"
    会以「用例运行到一半抛 ConnectionError」的形态出现，而不是一条清晰的 skip。
    """
    reason = redis_is_available()
    if reason is not None:
        pytest.skip(reason)
    from aicore.core.lease import RedisLockStore

    host, port, db = redis_integration_target()
    store = RedisLockStore(host=host, port=port, db=db, prefix=redis_prefix)
    try:
        yield store
    finally:
        # 关连接**之前**先把键清掉（关掉就没法发了）；清理只扫自己的前缀。
        await _drop_prefixed_keys(store.client, redis_prefix)
        await store.close()


# ---------------------------------------------------------------------------
# 真实 MySQL 的集成夹具（Task 4.7，供 `tests/integration/test_runner_redis.py` 用）
#
# 与 `tests/repository/test_repos.py::_require_mysql` 同一口径（`DSH_IT_MYSQL_*` + 显式 skip），
# 但抽到共享层：Task 4.7 的集成用例需要的是 `EngineFactory`（生产形状），
# 而不是那三个文件各自复制的裸 `Engine` 构造器。
# ---------------------------------------------------------------------------


def integration_settings(*, env: str = "test") -> Any:
    """集成用例的 `Settings`：MySQL 取 `DSH_IT_MYSQL_*`，Redis 取 `DSH_IT_REDIS_*`。

    `env` 默认 `"test"` 是**刻意的**：多数集成用例**自己要显式构造并驱动 `TaskRunner`**，
    不走 lifespan，故不需要让 `env` 变成别的值。

    **`env="dev"` 的用途**（本轮新增的形参）：`tests/integration/test_main_assembly.py`
    要覆盖**组合根的装配线**——而 `main.py` 的判据是 `settings.env != "test"` 才装配执行器。
    故那条用例必须能拿到一份**非 test**的 `Settings`。用 `"dev"` 而不是 `"prod"`：
    `core/config.py:86` 的 `_NON_PROD_ENVS = {"dev", "test"}` 允许 dev 配 mock 通道
    （`:23` 只有 `prod` + mock 才被拒），故 dev 是"能触发装配、又不触发布局校验"的那一档。

    **默认值不变** ⇒ 既有调用方的行为逐字不变。
    """
    from aicore.core.config import Settings

    host, port, db = redis_integration_target()
    mysql_host = os.environ.get("DSH_IT_MYSQL_HOST", "127.0.0.1")
    mysql_port = int(os.environ.get("DSH_IT_MYSQL_PORT", "3306"))
    return Settings(
        env=env,
        mysql_host=mysql_host,
        mysql_port=mysql_port,
        mysql_user=os.environ.get("DSH_IT_MYSQL_USER", "aicore_dev"),
        mysql_password=os.environ["DSH_IT_MYSQL_PASSWORD"],
        mysql_database=os.environ.get("DSH_IT_MYSQL_DATABASE", "aicore_test"),
        mysql_pool_size=5,
        mysql_max_overflow=10,
        mysql_readonly_host=mysql_host,
        mysql_readonly_port=mysql_port,
        redis_host=host,
        redis_port=port,
        redis_db=db,
        provider="mock",
        internal_token="test_internal_token",
        daily_quota_per_account=1000,
        daily_budget_total=100000,
    )


@pytest.fixture
def integration_engine_factory() -> Iterator[Any]:
    """真实 MySQL 的 `EngineFactory`（**生产形状**：写 / 只读 / 主库只读三个会话入口）。

    连不上时显式 skip 并说明缺哪个凭据 / 哪个地址（纪律 ③ 的 MySQL 版）。
    """
    if not os.environ.get("DSH_IT_MYSQL_PASSWORD"):
        pytest.skip(
            "未配置 DSH_IT_MYSQL_PASSWORD（或 .env 里的 AICORE_MYSQL_PASSWORD）："
            "集成用例需要真实演练库凭据；凭据 MUST NOT 硬编码进仓库"
        )
    from aicore.repository.session import EngineFactory

    try:
        factory = EngineFactory(integration_settings())
        with factory.write_session() as session:
            session.execute(text("SELECT 1"))
    except Exception as exc:
        pytest.skip(
            f"需要真实 MySQL（{os.environ.get('DSH_IT_MYSQL_DATABASE', 'aicore_test')}）"
            f"才能验证执行器的 SQL 落地：{type(exc).__name__}: {exc}"
        )
    try:
        yield factory
    finally:
        factory.dispose()
