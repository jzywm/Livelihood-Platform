"""AICORE 组合根。

**唯一允许把具体 Provider / repository 实现注入 service 的位置。**
其余各层 MUST NOT 自行构造具体实现（由 `.importlinter` 的 import-linter 契约强制）。

路由路径不含 `/api/v1` 前缀：GATEWAY 已用 RewritePath 去前缀，
故本服务路由与 openapi.yaml 一致，为 `/aicore/**` 与 `/health`。
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from pydantic import ValidationError
from starlette.types import ASGIApp

from aicore import __version__
from aicore.api import health, ocr, tasks
from aicore.core.config import ConfigRejected, get_settings
from aicore.core.errors import register_exception_handlers
from aicore.core.logging import bootstrap_logging, configure_logging, flush_logging
from aicore.core.trace import TraceIdMiddleware
from aicore.repository.session import EngineFactory

# stdlib 日志器（与 `core/config.py` / `core/errors.py` 同一写法）：本模块的日志少而关键，
# 且 stdlib 记录会被 root 上的 JSON 处理器收编，schema 与业务日志逐字一致。
_logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """启动与关闭钩子（第 2 组的收口位置）。

    顺序是硬要求：

    1. **先装引导日志配置**（`bootstrap_logging()`，Task 2.6 修复轮 1）——它不读配置，故能在
       读配置**之前**跑；没有这一步，第 2 步构造 `Settings` 时发出的规则 3 告警会缺少 JSON
       处理器，落成纯文本（进程的第一行日志不合 schema）；
    2. 读配置（`get_settings()`，进程内只解析一次）。失败即**拒绝启动**——先把阻断项清单写进
       一条结构化 ERROR 日志（此刻引导配置已就位，故这一行同样是 JSON），再抛
       `ConfigRejected`，进程起不来本身就是「拒绝启动」。为什么在抛出前还写一条日志：
       uvicorn 的启动失败栈是**框架的** stderr 明文输出，不进本服务的 JSON 管线；拒绝启动
       恰恰是最该被日志采集器看见的事件（否则它只在运维翻 stderr 时才存在）。记录的内容
       `str(exc)` 只含字段名 / 环境变量名 / 阈值数字，**不含任何配置取值**（见 `core/config.py`）；
    3. 按配置装配结构化 JSON 日志（Task 2.6）——配置里的 `log_level` / `app_name` 在此覆盖
       引导配置的默认值（两者共用同一套 schema 与同一份处理器装卸逻辑，故不重复输出）；
    4. `yield`：进程存活期；
    5. 关闭时刷日志处理器（只刷本服务的，不做别的生命周期工作）。

    **必须 `raise ... from None`**：`from exc` 会把 `__cause__` 设成原始 `ValidationError`，
    而 uvicorn 记录 lifespan 启动失败时带 `exc_info`，`str(ValidationError)` 会回显
    （截断后的）`input_value`——那里面含 `mysql_password` 等原始值。异常链因此会成为一条绕过
    「只用 loc/msg」的泄漏通道。完整推理见 `core/config.py` 模块 docstring。
    （引导配置不改变这一点：它只装日志处理器，不碰异常链。）
    上面那条 ERROR 日志同样只记 `str(ConfigRejected)`——它与异常消息同源，故同一份保证覆盖它。

    依赖装配（Task 3.4 起）与任务执行器（第 4 组）仍将挂在这里；本任务只做配置与日志。

    **第 4 组 T1 补的一道断链（L2，如实登记）**：本钩子此前**从未写 `app.state.settings`**，
    而 `api/deps.py` 的 `get_settings` 正是从 `request.app.state.settings` 取的。
    在此之前本服务没有任何走 `Depends(get_settings)` 的路由，故该断链一直不可见；
    Task 4.5 一加真实路由就会 `AttributeError`（Starlette `State.__getattr__` 缺属性即抛）。
    修法就是把配置挂上去——**位置紧随校验之后、`yield` 之前**，理由有两条：

    1. 校验失败时**不装配**：一个已被拒绝的配置不该出现在 `app.state` 上，
       否则任何拿到 `app` 的代码都能读到一个"看起来可用"的配置对象；
    2. `configure_logging` 之后装配：日志一旦可用，这条装配事实本身就可被观测。
    """
    bootstrap_logging()
    try:
        settings = get_settings()
    except ValidationError as exc:
        rejected = ConfigRejected.from_validation_error(exc)
        # 阻断项清单已是「可直接打印、不含取值」的多行摘要；JSON 渲染会把换行转义，仍是一行。
        _logger.error("%s", rejected)
        raise rejected from None
    configure_logging(settings)
    # L2 修复：`api/deps.py::get_settings` 的取值来源就在这里。MUST 在 yield 之前。
    app.state.settings = settings
    # Task 4.5：本服务第一批需要数据库的路由（`POST /aicore/ocr`、`GET /aicore/tasks/{taskId}`）
    # 经 `api/deps.py::get_engine_factory` 从 `app.state.engine_factory` 取会话工厂。
    # 与 L2 是同一类断链（装配点缺失 → 首个真实路由 AttributeError），故同一批补上。
    #
    # 构造**不连接**数据库（`create_engine` 惰性，见 repository/session.py），
    # 故这一步不会把「配置错」变成启动期的一次网络等待。
    engine_factory = EngineFactory(settings)
    app.state.engine_factory = engine_factory
    yield
    # 关闭时释放连接池。**释放的是本钩子自己装配的那个对象（局部引用）**，而不是重新从
    # `app.state` 取：`app.state.engine_factory` 是**可被替换**的装配点（测试夹具就按约定
    # 把 sqlite 沙盒替身注入到同一位置，见 tests/conftest.py::api_client），
    # 而「释放自己创建的资源」是本钩子唯一能保证的事。
    # 实测（starlette 1.6.0）：lifespan 关闭期抛出的异常会被
    # `TestClient` 的 `portal.call(self.wait_shutdown)` 原样抛回 `with` 块之外，
    # 把每个用例变成 ERROR；沙盒替身没有 `dispose()`，若写成
    # `app.state.engine_factory.dispose()` 会 AttributeError —— 那等于用一个测试替身的形状
    # 去决定生产装配点怎么写。替身自己的引擎由它自己的夹具释放（tests/conftest.py）。
    engine_factory.dispose()
    flush_logging()


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
    # Task 4.5：任务提交与轮询回执（`openapi.yaml` 的 `/aicore/ocr` 与 `/aicore/tasks/{taskId}`）。
    # 两个 router 各自带 `prefix="/aicore"`（与 openapi 路径逐字一致，网关已去掉 /api/v1 前缀）。
    app.include_router(ocr.router)
    app.include_router(tasks.router)
    # 全局异常处理器（Task 2.3）：业务异常 / 框架 HTTPException（路由 404、405 等）/
    # 框架 422 / 未预期异常，四条路径统一映射为平台信封（无体状态按框架契约回无体响应）。
    # 注册只改 app.exception_handlers，不读配置，create_app() 仍是纯装配函数。
    register_exception_handlers(app)
    return app


app = create_app()
