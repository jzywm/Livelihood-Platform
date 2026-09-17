"""全局测试夹具。

约定：测试内 MUST NOT 出现任意 sleep；等待一律走轮询断言或注入的时钟。
"""

from __future__ import annotations

import pytest


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"
