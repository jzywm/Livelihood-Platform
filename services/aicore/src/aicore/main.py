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
from starlette.types import ASGIApp

from aicore import __version__
from aicore.api import health
from aicore.core.trace import TraceIdMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """启动与关闭钩子。

    启动即校验配置（Task 2.2）、装配依赖（Task 3.4 起）、
    启动任务执行器（第 4 组）都将挂在这里。
    """
    yield


class _TracedFastAPI(FastAPI):
    """把 traceId 中间件包在**整条 ASGI 栈之外**的应用类。

    为什么不用 `app.add_middleware(TraceIdMiddleware)`：Starlette 固定把用户中间件
    插在 ServerErrorMiddleware **之内**（starlette/applications.py 的
    build_middleware_stack：`[ServerErrorMiddleware] + user_middleware + [ExceptionMiddleware]`）。
    未捕获异常由 ServerErrorMiddleware 在最外层渲染成 500，那条路径会失守两处：

    1. 响应头缺 `X-Request-Id`——500 响应的 send 不经过用户中间件；
    2. 注册在 `Exception` 上的处理器（Starlette 会把它提升为 ServerErrorMiddleware 的
       handler）执行时，中间件的 `finally` 已按 token 回滚上下文，信封只能拿到一个
       **新生成**的 traceId，与网关注入值不符（实测：内层路径下响应头缺失、
       信封 traceId = 新生成的 743a…）。

    故在组合根把中间件包在应用之外：异常处理链仍在它的 `try` 之内。
    其余中间件照旧走标准 add_middleware 通道（在 ServerErrorMiddleware 之内）。
    """

    def build_middleware_stack(self) -> ASGIApp:
        return TraceIdMiddleware(super().build_middleware_stack())


def create_app() -> FastAPI:
    """应用工厂。测试与部署共用，保证装配路径唯一。

    纯装配函数：**不读配置**（必填项的拒绝在 lifespan 启动钩子里，见 Task 2.2）。
    """
    app = _TracedFastAPI(
        title="AI 能力中心服务（AICORE）",
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs",
        openapi_url="/openapi.json",
    )
    app.include_router(health.router)
    return app


app = create_app()
