"""全局测试夹具。

约定：测试内 MUST NOT 出现任意 sleep；等待一律走轮询断言或注入的时钟。
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from typing import TYPE_CHECKING

import pytest
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
    "AICORE_REDIS_HOST": "127.0.0.1",
    "AICORE_PROVIDER": "mock",
    "AICORE_INTERNAL_TOKEN": "test_internal_token",
    "AICORE_DAILY_QUOTA_PER_ACCOUNT": "1000",
    "AICORE_DAILY_BUDGET_TOTAL": "100000",
}

for _key, _value in _TEST_ENV_DEFAULTS.items():
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
