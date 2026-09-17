"""全局测试夹具。

约定：测试内 MUST NOT 出现任意 sleep；等待一律走轮询断言或注入的时钟。
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING

import pytest
from fastapi import FastAPI

from aicore.main import create_app

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
