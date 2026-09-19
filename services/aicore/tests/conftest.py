"""全局测试夹具。

约定：测试内 MUST NOT 出现任意 sleep；等待一律走轮询断言或注入的时钟。
"""

from __future__ import annotations

import inspect
import os
import socket
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from dotenv import dotenv_values
from fastapi import FastAPI

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
