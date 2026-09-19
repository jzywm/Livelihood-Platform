"""AICORE 组合根。

**唯一允许把具体 Provider / repository 实现注入 service 的位置。**
其余各层 MUST NOT 自行构造具体实现（由 `.importlinter` 的 import-linter 契约强制）。

路由路径不含 `/api/v1` 前缀：GATEWAY 已用 RewritePath 去前缀，
故本服务路由与 openapi.yaml 一致，为 `/aicore/**` 与 `/health`。
"""

from __future__ import annotations

import asyncio
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
from aicore.core.lease import RedisLockStore
from aicore.core.logging import bootstrap_logging, configure_logging, flush_logging
from aicore.core.task_runner import RunnerConfig, TaskRunner
from aicore.core.trace import TraceIdMiddleware
from aicore.repository.session import EngineFactory
from aicore.repository.task_lease_store import SqlTaskLeaseStore
from aicore.service.task.registry import REGISTRY

# stdlib 日志器（与 `core/config.py` / `core/errors.py` 同一写法）：本模块的日志少而关键，
# 且 stdlib 记录会被 root 上的 JSON 处理器收编，schema 与业务日志逐字一致。
_logger = logging.getLogger(__name__)


def _log_runner_death(task: asyncio.Task[None]) -> None:
    """执行器协程结束时的回调：**异常死亡当场记 ERROR**（A2）。

    为什么需要它：`asyncio.create_task` 的异常在没人 retrieve 之前是"沉默"的，
    而 `runner_task` 正常情况下要到关停才被 `await` —— 于是"执行器已死、进程还活着"
    这件事在整个进程存续期间**没有任何日志**（`/health` 也不查依赖）。
    这是最坏的形态：**看起来一切正常，实际一个任务都不会被领**。

    取消（关停）不算死亡，故 `cancelled()` 与无异常两种都直接返回。
    """
    if task.cancelled():
        return
    failure = task.exception()
    if failure is not None:
        _logger.error(
            "任务执行器协程异常退出：进程仍然存活，但**不会再领取任何任务**"
            "（需要重启；请按上方堆栈定位根因）：%s",
            type(failure).__name__,
            exc_info=failure,
        )


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
    # ------------------------------------------------------------------
    # Task 4.7：任务执行器的装配（领取 → 执行 → 终态 / 退避）
    #
    # **`env == "test" 时 MUST NOT 启动执行器**（工单 §2.7 逐字）：本钩子被每个用
    # `TestClient` 的用例触发，启动执行器等于让每个用例都去连一次 Redis；而默认段
    # （离线）MUST NOT 连 Redis（`design.md:282` 的离线保证）。真实 Redis 只在
    # `@pytest.mark.integration` 段用。
    #
    # 判据用 `settings.env != "test"`（而不是「有没有配 redis_host」那类推断）：
    # `env` 是**显式的部署形态声明**，推断出来的判据会在「本机恰好有个 Redis」时静默失效。
    # ------------------------------------------------------------------
    runner: TaskRunner | None = None
    runner_stop: asyncio.Event | None = None
    runner_task: asyncio.Task[None] | None = None
    locks: RedisLockStore | None = None
    if settings.env != "test":
        locks = RedisLockStore(
            host=settings.redis_host,
            port=settings.redis_port,
            db=settings.redis_db,
        )
        runner = TaskRunner(
            store=SqlTaskLeaseStore(engine_factory),
            locks=locks,
            # **空 mapping 是 M1 的事实，MUST NOT 用假处理器填满它**（工单 §2.8）：
            # `service/ocr_service.py` 此刻仍是空壳，注册表的 `handler_ref` 只是**字符串位置**。
            # 执行器遇到「没有对应处理器」的任务会**显式失败**（ERROR + `5000`），
            # 而不是静默跳过——故空映射是**可观测的现状**，不是被藏起来的缺口。
            handlers={},
            # 策略映射由**组合根**注入（这是唯一允许跨层装配的位置）：
            # `core/task_runner.py` MUST NOT import `aicore.service`（契约 4），
            # 故它把 `TaskPolicy` 声明成只含 `retryable` / `task_type` 的结构化 Protocol，
            # 注册表的 dataclass 实例**结构上**就满足它，无需适配器。
            # `dict(REGISTRY)`：`REGISTRY` 是 `MappingProxyType`（运行期只读），
            # 注入一份普通 dict 副本即可——只读性由注册表侧保证，组合根无需再包一层。
            policies=dict(REGISTRY),
            config=RunnerConfig(
                lease_ms=settings.lease_ms,
                max_retries=settings.max_retries,
                concurrency_limit=settings.concurrency_limit,
            ),
        )
        # 执行器协程与停止事件都挂在 `app.state` 上：关停时要能 set 并 await 它。
        runner_stop = asyncio.Event()
        runner_task = asyncio.create_task(runner.run_forever(stop=runner_stop))
        # **执行器异常死亡必须有日志（A2）**：`create_task` 的异常只在有人 retrieve 它时才出现，
        # 而 `run_forever` 正常情况下要到关停才被 await——于是"执行器死了"这件事在进程存活期间
        # **一行日志都没有**（`/health` 也不查依赖）。加一个 done-callback，把死亡
        # **当场**记成 ERROR。与 `TaskRunner._track._settle` 同一取向。
        runner_task.add_done_callback(_log_runner_death)
        app.state.task_runner = runner
        # 如实记一条：M1 的处理器数量是 0。这不是"启动成功"的装饰性日志——
        # 运维看到它就知道「此刻领到的任务都会因装配缺失而 FAILED（5000）」。
        _logger.info(
            "任务执行器已启动，已注册处理器 %d 个（并发上限 %d、租约 %dms、任务级重试上限 %d）",
            len(runner.registered_handlers),
            settings.concurrency_limit,
            settings.lease_ms,
            settings.max_retries,
        )
    yield
    # ------------------------------------------------------------------
    # 关闭（**顺序是硬要求**：工单 §2.7）——先 set stop、await 执行器退出，**再**关 Redis。
    # 反过来的话，在跑任务的续期会失败——那会被执行器判成「租约已失去」而**主动放弃**
    # （`design.md:208` 的语义），表现为一串"无故放弃"的告警，而真正的原因是我们先拔了 Redis。
    #
    # **每一步都必须执行到（A2）**：第一版是裸 `await runner_task`，一旦执行器已经异常死亡，
    # 那句会把死亡原因抛出去，于是 `runner.stop()` / `locks.close()` / `dispose()` /
    # `flush_logging()` **全部被跳过**（实测：关停块里执行到的清理步骤 = []）。
    # 故这里把 `await` 包起来：死亡原因记 ERROR 后**继续**关停流程。
    # 资源清理不该因为"另一个组件死过"而整体不做。
    # ------------------------------------------------------------------
    if runner_task is not None and runner_stop is not None:
        runner_stop.set()
        try:
            await runner_task
        except asyncio.CancelledError:
            raise
        except Exception:
            # 死亡本身已由 done-callback 记过一条；这里是"关停时又看到一次"，
            # 仍然记下来（两条日志的上下文不同：一条是死亡当场、一条是关停收尾）。
            _logger.error("任务执行器在关停前已异常退出：继续执行关停清理", exc_info=True)
    if runner is not None:
        # 释放自建的 CPU 池（外部注入的池不归执行器管，见 TaskRunner.stop 的 docstring）。
        await runner.stop()
    if locks is not None:
        await locks.close()
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
