"""全局测试夹具。

约定：测试内 MUST NOT 出现任意 sleep；等待一律走轮询断言或注入的时钟。
"""

from __future__ import annotations

import os
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
