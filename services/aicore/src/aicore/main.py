"""AICORE 组合根。

**唯一允许把具体 Provider / repository 实现注入 service 的位置。**
其余各层 MUST NOT 自行构造具体实现（由 `.importlinter` 的 import-linter 契约强制）。

路由路径不含 `/api/v1` 前缀：GATEWAY 已用 RewritePath 去前缀，
故本服务路由与 openapi.yaml 一致，为 `/aicore/**` 与 `/health`。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from aicore import __version__
from aicore.api import health


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """启动与关闭钩子。

    启动即校验配置（Task 2.2）、装配依赖（Task 3.4 起）、
    启动任务执行器（第 4 组）都将挂在这里。
    """
    yield


def create_app() -> FastAPI:
    """应用工厂。测试与部署共用，保证装配路径唯一。"""
    app = FastAPI(
        title="AI 能力中心服务（AICORE）",
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs",
        openapi_url="/openapi.json",
    )
    app.include_router(health.router)
    return app


app = create_app()
