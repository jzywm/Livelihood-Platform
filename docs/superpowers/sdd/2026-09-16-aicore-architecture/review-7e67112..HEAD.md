# Review package 7e67112..HEAD

## Commits

50b36ed build(aicore): 显式声明被直接导入的 starlette 依赖
83f3a66 feat(aicore): 实现 traceId 上下文传播与响应头回显

## Stat

 services/aicore/pyproject.toml           |   3 +
 services/aicore/src/aicore/core/trace.py | 254 ++++++++++++++++-
 services/aicore/src/aicore/main.py       |  31 ++-
 services/aicore/tests/unit/__init__.py   |   0
 services/aicore/tests/unit/test_trace.py | 456 +++++++++++++++++++++++++++++++
 5 files changed, 741 insertions(+), 3 deletions(-)

## Diff

```diff
diff --git a/services/aicore/pyproject.toml b/services/aicore/pyproject.toml
index ce3ad84..7ba1a94 100644
--- a/services/aicore/pyproject.toml
+++ b/services/aicore/pyproject.toml
@@ -2,20 +2,23 @@
 requires = ["setuptools>=69"]
 build-backend = "setuptools.build_meta"

 [project]
 name = "aicore"
 version = "0.1.0"
 description = "AI 能力中心服务（AICORE）· 民生甄选平台"
 requires-python = ">=3.12"
 dependencies = [
     "fastapi>=0.141",
+    # starlette 是被直接 import 的（main.py 的中间件基类、core/trace.py 的 ASGI 类型），
+    # 不能只靠 fastapi 的传递依赖：一旦上游更换实现或调整依赖，本服务会在部署时才炸。
+    "starlette>=1.6",
     "uvicorn[standard]>=0.53",
     "pydantic>=2.13",
     "pydantic-settings>=2.15",
     "sqlalchemy>=2.0.54",
     "pymysql>=1.2",
     "redis>=8.1",
     "httpx>=0.28",
     "alembic>=1.20",
     "structlog>=24.0",
     "cryptography>=50.0",
diff --git a/services/aicore/src/aicore/core/trace.py b/services/aicore/src/aicore/core/trace.py
index 84da332..c40e17e 100644
--- a/services/aicore/src/aicore/core/trace.py
+++ b/services/aicore/src/aicore/core/trace.py
@@ -1 +1,253 @@
-"""traceId 上下文变量与传播（请求头 X-Request-Id）。Task 2.5 实现。"""
+"""traceId 上下文与传播（Task 2.5）。
+
+链路：GATEWAY 在入口注入 `X-Request-Id`（PDD L1750）→ 本模块解析并写入 ContextVar
+→ 日志（Task 2.6）与出向调用取用 → 响应头按原值回显。
+
+三条不可退让的约束：
+
+1. 请求头固定是 **`X-Request-Id`**（不是 `X-Trace-Id`）；
+2. 头缺失或非法时**自行生成** 16 位小写 hex，并在日志字段 `traceIdSource` 中标记
+   `generated`（网关注入的标 `propagated`）。少了这个标记，「网关没注入」会被本地
+   生成的 traceId 掩盖，排障时反而查不出网关故障；
+3. 跨线程池（`run_in_executor`）**必须显式传递**上下文：新线程的 Context 是空的，
+   traceId 会静默丢失（表现为「部分日志串不起来」），故提供 copy_context_for_thread()。
+"""
+
+from __future__ import annotations
+
+import secrets
+from collections.abc import Iterable
+from contextvars import Context, ContextVar, Token, copy_context
+from dataclasses import dataclass
+from typing import Final
+
+from starlette.types import ASGIApp, Message, Receive, Scope, Send
+
+#: 网关注入 traceId 用的请求头。**不是** `X-Trace-Id`（该写成缺陷）。
+TRACE_ID_HEADER: Final = "X-Request-Id"
+
+#: 日志标记字段名：区分「网关注入」与「本服务自行生成」。
+TRACE_SOURCE_FIELD: Final = "traceIdSource"
+
+#: 来源标记取值：来自上游（网关注入的请求头）。
+TRACE_SOURCE_PROPAGATED: Final = "propagated"
+
+#: 来源标记取值：本服务自行生成（头缺失或非法）。
+TRACE_SOURCE_GENERATED: Final = "generated"
+
+#: 16 位小写 hex（对齐 `_common` 示例 `3f2a1b9c8d7e6f50`）。
+TRACE_ID_HEX_LENGTH: Final = 16
+
+#: 外来 traceId 的长度上限：与平台 `X-Request-Id` 口径一致（网关侧同为 64）。
+MAX_TRACE_ID_LENGTH: Final = 64
+
+_TRACE_ID_BYTES: Final = TRACE_ID_HEX_LENGTH // 2
+_PRINTABLE_MIN: Final = 0x20
+_PRINTABLE_MAX: Final = 0x7E
+_TRACE_HEADER_BYTES: Final = TRACE_ID_HEADER.encode("ascii").lower()
+
+
+@dataclass(frozen=True, slots=True)
+class TraceContext:
+    """当前上下文绑定的 traceId 及其来源标记。
+
+    值存放在**同一个** ContextVar 里：这样一次 `set` 只产生一个 token，
+    回滚 `reset_trace_id(token)` 时 traceId 与来源标记原子恢复，不会出现
+    「值回滚了、标记留在原地」的半截状态。
+    """
+
+    trace_id: str
+    source: str
+
+
+_TRACE_VAR: ContextVar[TraceContext | None] = ContextVar("aicore_trace_context", default=None)
+
+
+def new_trace_id() -> str:
+    """生成新的 traceId：16 位小写 hex。
+
+    用 `secrets` 而不是 `random`：traceId 会进日志与响应头，可预测的 id 便于
+    攻击者伪造/碰撞，而代价只是一个 CSPRNG 调用。
+    """
+    return secrets.token_hex(_TRACE_ID_BYTES)
+
+
+def _current() -> TraceContext:
+    """取当前上下文绑定；未绑定时先生成并按 `generated` 标记。
+
+    生成后**写回上下文**：同一上下文内多次取到同一个 id，
+    否则每个请求内每行日志都会换一个 traceId，串链失效。
+    """
+    context = _TRACE_VAR.get()
+    if context is None:
+        context = TraceContext(trace_id=new_trace_id(), source=TRACE_SOURCE_GENERATED)
+        _TRACE_VAR.set(context)
+    return context
+
+
+def get_trace_id() -> str:
+    """当前 traceId；未设置时生成一个存入当前上下文。
+
+    请求外的上下文（后台任务、CLI、线程池漏传上下文后的兜底）同样拿到一个
+    可串链的 id，而不是空串。
+    """
+    return _current().trace_id
+
+
+def get_trace_source() -> str:
+    """当前 traceId 的来源标记（`propagated` / `generated`）。
+
+    与 get_trace_id() 同源：未绑定时同样先生成、按 `generated` 标记，
+    故日志处理器先取 id 还是先取来源，结果一致。
+    """
+    return _current().source
+
+
+def set_trace_id(
+    value: str, *, source: str = TRACE_SOURCE_PROPAGATED
+) -> Token[TraceContext | None]:
+    """显式绑定 traceId，返回可交给 reset_trace_id() 回滚的 token。
+
+    `source` 默认 `propagated`：显式设置的值都来自上游（网关请求头、上游任务负载）。
+    本服务自行生成的值走 get_trace_id()，或显式传 `source=TRACE_SOURCE_GENERATED`。
+
+    签名说明：任务简报写的是 `-> None`。但 reset_trace_id(token) 需要 token，
+    否则「绑定 → 回滚」这一对无法成对使用，而回滚是防同 worker 串号的唯一手段；
+    返回 token 是 `-> None` 的严格超集——忽略返回值即等同 `-> None` 用法。
+    """
+    return _TRACE_VAR.set(TraceContext(trace_id=value, source=source))
+
+
+def reset_trace_id(token: Token[TraceContext | None] | None = None) -> None:
+    """回滚上下文：请求结束（含异常路径）必须调用。
+
+    worker 进程/线程会被复用，不回滚则上一个请求的 traceId 会粘到下一个请求上
+    ——串号比「没有 traceId」更难查。token 只能在创建它的上下文里回滚（ContextVar 语义）。
+
+    token 省略时直接清空当前上下文（后台任务收尾、用例隔离）。
+    """
+    if token is None:
+        _TRACE_VAR.set(None)
+        return
+    _TRACE_VAR.reset(token)
+
+
+def copy_context_for_thread() -> Context:
+    """复制当前上下文，用于把 traceId 显式带进线程池。
+
+    用法（`ctx.run` 必须作为**被调用的可调用对象**交给 run_in_executor）::
+
+        ctx = copy_context_for_thread()
+        result = await asyncio.get_running_loop().run_in_executor(pool, ctx.run, fn)
+
+    需要给 `fn` 传参时继续往后排位置参数，`run_in_executor` 会原样转给 `ctx.run`::
+
+        await loop.run_in_executor(pool, ctx.run, fn, arg1, arg2)   # 等价 ctx.run(fn, arg1, arg2)
+
+    为什么必须这么写：`run_in_executor(pool, fn)` 在线程池线程里执行 `fn`，新线程的
+    Context 是空的，`fn` 里的 `get_trace_id()` 只会再生成一个新 id——traceId 静默丢失，
+    正是「部分日志串不起来」的成因。`ctx.run(fn)` 把复制出来的上下文带进该线程，
+    `fn` 内读到的 traceId 与请求内一致。
+
+    两个使用要点：
+
+    - 同一个 `Context` 不能被重入（同一时刻只允许一个 `ctx.run` 在跑），
+      故每个任务 / 每次提交都要重新调用本函数复制一份；
+    - 当前上下文若还没有 traceId，本函数会先生成一个（标记 `generated`）再复制，
+      保证线程池里的日志同样可串链。
+    """
+    get_trace_id()
+    return copy_context()
+
+
+class TraceIdMiddleware:
+    """纯 ASGI 中间件：`X-Request-Id` → ContextVar（同任务）→ 响应头回显。
+
+    **为什么不用 `BaseHTTPMiddleware`**：它把下游应用丢进独立的 anyio 任务，
+    ContextVar 与请求不再处于同一个任务（本模块的用例以「处理器内的
+    `asyncio.current_task()` 必须等于调用方任务」正面守住这一点），
+    异常还会被改写成 `ExceptionGroup`。故这里直接实现 ASGI 协议。
+
+    **为什么由组合根包在最外层**（见 `aicore/main.py` 的 `_TracedFastAPI`）：
+    Starlette 固定把用户中间件放在 ServerErrorMiddleware 之内，未捕获异常由后者
+    在最外层渲染 500；只有包在最外层，「异常逃逸 → 500」这条路径才带得上回显头。
+    """
+
+    def __init__(self, app: ASGIApp) -> None:
+        self.app = app
+
+    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
+        if scope["type"] != "http":
+            # lifespan / websocket 不参与 HTTP traceId 传播，原样放行。
+            await self.app(scope, receive, send)
+            return
+
+        trace_id, source = _resolve_trace_id(scope.get("headers") or ())
+        token = set_trace_id(trace_id, source=source)
+        try:
+            await self.app(scope, receive, _send_with_trace_id(send, trace_id))
+        finally:
+            reset_trace_id(token)
+
+
+def _send_with_trace_id(send: Send, trace_id: str) -> Send:
+    """包装 send：在响应起始消息上回显 `X-Request-Id`。
+
+    先剔除应用自己写的同名头，保证回显值唯一且可信（应用写错也不会出现两个）。
+    不改原列表、而是换一个新列表：`http.response.start` 里的 headers 很可能就是
+    响应对象自身的 `raw_headers`，原地 append 会污染该响应对象。
+    """
+    echoed: tuple[bytes, bytes] = (TRACE_ID_HEADER.encode("ascii"), trace_id.encode("ascii"))
+
+    async def send_with_trace_id(message: Message) -> None:
+        if message["type"] == "http.response.start":
+            kept = [
+                (name, value)
+                for name, value in message.get("headers") or []
+                if name.lower() != _TRACE_HEADER_BYTES
+            ]
+            message["headers"] = [*kept, echoed]
+        await send(message)
+
+    return send_with_trace_id
+
+
+def _resolve_trace_id(headers: Iterable[tuple[bytes, bytes]]) -> tuple[str, str]:
+    """解析待绑定的 traceId 与来源标记：能用的头按 `propagated`，否则生成。"""
+    accepted = _sanitize_trace_id(_incoming_trace_id(headers))
+    if accepted is None:
+        return new_trace_id(), TRACE_SOURCE_GENERATED
+    return accepted, TRACE_SOURCE_PROPAGATED
+
+
+def _incoming_trace_id(headers: Iterable[tuple[bytes, bytes]]) -> str | None:
+    """取第一个 `X-Request-Id`（ASGI 头名一律小写；重名取首个，与网关口径一致）。"""
+    for name, value in headers:
+        if name.lower() == _TRACE_HEADER_BYTES:
+            # 用 latin-1 解码：头是任意字节，latin-1 不会抛异常；非 ASCII 字节会解成
+            # > 0x7E 的字符，随后被 _sanitize_trace_id 判为非法（等价于头缺失）。
+            return value.decode("latin-1")
+    return None
+
+
+def _sanitize_trace_id(raw: str | None) -> str | None:
+    """校验外来 traceId，非法返回 None（调用方按「头缺失」处理：生成 + 标 generated）。
+
+    接受条件（全部满足）：
+
+    - 非空且长度 ≤ MAX_TRACE_ID_LENGTH；
+    - 每个字符都是可打印 ASCII（0x20~0x7E）——控制字符（含 CR/LF）、DEL、
+      非 ASCII（含中文、emoji）一律拒绝。这既防日志伪造（换行注假日志行），
+      也防响应头注入（CRLF 拆头）；
+    - 至少含一个非空格字符：全空格是无意义值，按缺失处理。
+
+    拒绝即丢弃原值，绝不把攻击者可控的原始串写进日志或响应头；
+    `traceIdSource=generated` 让这次「丢弃 + 重生成」在日志里可见。
+    """
+    if raw is None or raw == "" or len(raw) > MAX_TRACE_ID_LENGTH:
+        return None
+    if any(not (_PRINTABLE_MIN <= ord(char) <= _PRINTABLE_MAX) for char in raw):
+        return None
+    if not raw.strip():
+        return None
+    return raw
diff --git a/services/aicore/src/aicore/main.py b/services/aicore/src/aicore/main.py
index e0e6b23..33e5760 100644
--- a/services/aicore/src/aicore/main.py
+++ b/services/aicore/src/aicore/main.py
@@ -6,38 +6,65 @@
 路由路径不含 `/api/v1` 前缀：GATEWAY 已用 RewritePath 去前缀，
 故本服务路由与 openapi.yaml 一致，为 `/aicore/**` 与 `/health`。
 """

 from __future__ import annotations

 from collections.abc import AsyncIterator
 from contextlib import asynccontextmanager

 from fastapi import FastAPI
+from starlette.types import ASGIApp

 from aicore import __version__
 from aicore.api import health
+from aicore.core.trace import TraceIdMiddleware


 @asynccontextmanager
 async def lifespan(app: FastAPI) -> AsyncIterator[None]:
     """启动与关闭钩子。

     启动即校验配置（Task 2.2）、装配依赖（Task 3.4 起）、
     启动任务执行器（第 4 组）都将挂在这里。
     """
     yield


+class _TracedFastAPI(FastAPI):
+    """把 traceId 中间件包在**整条 ASGI 栈之外**的应用类。
+
+    为什么不用 `app.add_middleware(TraceIdMiddleware)`：Starlette 固定把用户中间件
+    插在 ServerErrorMiddleware **之内**（starlette/applications.py 的
+    build_middleware_stack：`[ServerErrorMiddleware] + user_middleware + [ExceptionMiddleware]`）。
+    未捕获异常由 ServerErrorMiddleware 在最外层渲染成 500，那条路径会失守两处：
+
+    1. 响应头缺 `X-Request-Id`——500 响应的 send 不经过用户中间件；
+    2. 注册在 `Exception` 上的处理器（Starlette 会把它提升为 ServerErrorMiddleware 的
+       handler）执行时，中间件的 `finally` 已按 token 回滚上下文，信封只能拿到一个
+       **新生成**的 traceId，与网关注入值不符（实测：内层路径下响应头缺失、
+       信封 traceId = 新生成的 743a…）。
+
+    故在组合根把中间件包在应用之外：异常处理链仍在它的 `try` 之内。
+    其余中间件照旧走标准 add_middleware 通道（在 ServerErrorMiddleware 之内）。
+    """
+
+    def build_middleware_stack(self) -> ASGIApp:
+        return TraceIdMiddleware(super().build_middleware_stack())
+
+
 def create_app() -> FastAPI:
-    """应用工厂。测试与部署共用，保证装配路径唯一。"""
-    app = FastAPI(
+    """应用工厂。测试与部署共用，保证装配路径唯一。
+
+    纯装配函数：**不读配置**（必填项的拒绝在 lifespan 启动钩子里，见 Task 2.2）。
+    """
+    app = _TracedFastAPI(
         title="AI 能力中心服务（AICORE）",
         version=__version__,
         lifespan=lifespan,
         docs_url="/docs",
         openapi_url="/openapi.json",
     )
     app.include_router(health.router)
     return app


diff --git a/services/aicore/tests/unit/__init__.py b/services/aicore/tests/unit/__init__.py
new file mode 100644
index 0000000..e69de29
diff --git a/services/aicore/tests/unit/test_trace.py b/services/aicore/tests/unit/test_trace.py
new file mode 100644
index 0000000..3f4762d
--- /dev/null
+++ b/services/aicore/tests/unit/test_trace.py
@@ -0,0 +1,456 @@
+"""traceId 上下文传播用例（Task 2.5）。
+
+覆盖点（全部跑真实链路，不用桩）：
+
+1. 网关注入 → 处理器内取到同一值、响应头原值回显、来源标记 propagated；
+2. 头缺失 → 自行生成 16 位 hex、响应头回显、来源标记 generated（网关故障不被掩盖）；
+3. 头非法（超长 / 控制字符 / 非 ASCII / 全空格）→ 按缺失处理，敌意串既不进上下文也不进响应头；
+4. 跨线程池：copy_context_for_thread() + run_in_executor(pool, ctx.run, fn) 在线程内取到同一
+   traceId，并给出「不传上下文就丢」的阴性对照，证明这条用例确有判别力；
+5. 防串号：连续两次请求互不影响，且请求结束后同一上下文里的值已按 token 回滚；
+6. 异常逃逸出应用时 500 响应仍带回显头，且框架的异常处理器仍能读到同一个 traceId
+   （Task 2.4 的 500 信封要用）；/health 仍是裸响应。
+
+探针路由由 fixtures 挂到**全新的** create_app() 上，生产代码不含任何调试端点。
+非法请求头用 ASGI 直调注入：httpx 会拒收含 CR/LF 的头，经 TestClient 根本送不进去。
+"""
+
+from __future__ import annotations
+
+import asyncio
+import re
+import threading
+from collections.abc import Iterator
+from concurrent.futures import ThreadPoolExecutor
+from dataclasses import dataclass, field
+from typing import Any
+
+import httpx
+import pytest
+from fastapi import APIRouter, FastAPI, Request
+from fastapi.responses import JSONResponse
+from fastapi.testclient import TestClient
+from starlette.types import Message, Scope
+
+from aicore.core.trace import (
+    MAX_TRACE_ID_LENGTH,
+    TRACE_ID_HEADER,
+    TRACE_SOURCE_FIELD,
+    TRACE_SOURCE_GENERATED,
+    TRACE_SOURCE_PROPAGATED,
+    copy_context_for_thread,
+    get_trace_id,
+    get_trace_source,
+    new_trace_id,
+    reset_trace_id,
+    set_trace_id,
+)
+from aicore.main import create_app
+
+TRACE_ID_PATTERN = re.compile(r"^[0-9a-f]{16}$")
+
+# `_common` 的示例值，同时也是合法的 16 位 hex 注入值。
+INJECTED_TRACE_ID = "3f2a1b9c8d7e6f50"
+
+# 网关 TraceIdFilter 在头缺失时兜底生成的是 UUID（36 字符），必须原样透传。
+GATEWAY_UUID_TRACE_ID = "5f0e6a1d-2c3b-4a59-8d7e-1f2a3b4c5d6e"
+
+
+@dataclass(slots=True)
+class Observation:
+    """某个线程内读到的上下文快照。"""
+
+    trace_id: str
+    thread_ident: int
+
+
+@dataclass(slots=True)
+class Snapshot:
+    """一次请求的处理器内观测结果。"""
+
+    trace_id: str
+    source: str
+    thread_ident: int
+    task: asyncio.Task[Any] | None
+    traced_worker: Observation | None = None
+    untraced_worker: Observation | None = None
+
+
+@dataclass(slots=True)
+class Probe:
+    """测试专用探针：全新应用 + 处理器内观测记录。"""
+
+    app: FastAPI
+    snapshots: list[Snapshot] = field(default_factory=list)
+
+    @property
+    def last(self) -> Snapshot:
+        assert self.snapshots, "探针路由未被调用：用例没有真正打到 /__probe__/*"
+        return self.snapshots[-1]
+
+
+def _observe_in_thread() -> Observation:
+    """在线程池线程里读上下文（无参，便于直接交给 ctx.run）。"""
+    return Observation(trace_id=get_trace_id(), thread_ident=threading.get_ident())
+
+
+def _record(snapshots: list[Snapshot], **extra: Any) -> Snapshot:
+    """记录处理器内观测值。"""
+    snapshot = Snapshot(
+        trace_id=get_trace_id(),
+        source=get_trace_source(),
+        thread_ident=threading.get_ident(),
+        task=asyncio.current_task(),
+        **extra,
+    )
+    snapshots.append(snapshot)
+    return snapshot
+
+
+def _build_probe_router(snapshots: list[Snapshot]) -> APIRouter:
+    """测试专用探针路由（include_in_schema=False，不进生产代码）。"""
+    router = APIRouter(include_in_schema=False)
+
+    @router.get("/__probe__/context")
+    async def context() -> dict[str, str]:
+        snapshot = _record(snapshots)
+        return {"traceId": snapshot.trace_id, "source": snapshot.source}
+
+    @router.get("/__probe__/thread-pool")
+    async def thread_pool() -> dict[str, str]:
+        loop = asyncio.get_running_loop()
+        context_copy = copy_context_for_thread()
+        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="aicore-trace-probe") as pool:
+            # 正例：把复制出来的上下文交给线程池线程
+            traced = await loop.run_in_executor(pool, context_copy.run, _observe_in_thread)
+            # 阴性对照：照原样直接提交，上下文不会被带过去
+            untraced = await loop.run_in_executor(pool, _observe_in_thread)
+        _record(snapshots, traced_worker=traced, untraced_worker=untraced)
+        return {"traced": traced.trace_id, "untraced": untraced.trace_id}
+
+    @router.get("/__probe__/boom")
+    async def boom() -> dict[str, str]:
+        raise RuntimeError("探针：模拟逃逸出应用的未捕获异常")
+
+    return router
+
+
+@pytest.fixture
+def probe() -> Probe:
+    """挂上探针路由的全新应用（每次装配互不污染，也不改动生产代码）。"""
+    harness = Probe(app=create_app())
+    harness.app.include_router(_build_probe_router(harness.snapshots))
+    return harness
+
+
+@pytest.fixture
+def probe_client(probe: Probe) -> Iterator[TestClient]:
+    with TestClient(probe.app) as client:
+        yield client
+
+
+@pytest.fixture(autouse=True)
+def _isolated_trace_context() -> Iterator[None]:
+    """用例隔离：ContextVar 在 pytest 主线程里跨用例存活，进入与退出时都清空。"""
+    reset_trace_id()
+    yield
+    reset_trace_id()
+
+
+def _trace_header_bytes() -> bytes:
+    """ASGI 头名一律小写。"""
+    return TRACE_ID_HEADER.encode("ascii").lower()
+
+
+def _echoed_trace_id(response: httpx.Response) -> str:
+    """取响应上的回显头；缺失即用例失败（KeyError 说不清缺的是什么）。"""
+    assert TRACE_ID_HEADER in response.headers, f"响应缺少 {TRACE_ID_HEADER} 回显头"
+    return response.headers[TRACE_ID_HEADER]
+
+
+async def _call_asgi(
+    app: FastAPI,
+    path: str = "/__probe__/context",
+    headers: list[tuple[bytes, bytes]] | None = None,
+) -> list[Message]:
+    """按 ASGI 协议直接驱动应用，返回 send 收到的全部消息。
+
+    httpx 会拒收含 CR/LF 的请求头，敌意头只能在这一层注入；
+    顺带让用例与请求处理跑在**同一个 asyncio 任务**里（见 test_request_runs_in_callers_task）。
+    """
+    scope: Scope = {
+        "type": "http",
+        "asgi": {"version": "3.0", "spec_version": "2.3"},
+        "http_version": "1.1",
+        "method": "GET",
+        "scheme": "http",
+        "path": path,
+        "raw_path": path.encode("ascii"),
+        "query_string": b"",
+        "root_path": "",
+        "headers": [(b"host", b"testserver"), *(headers or [])],
+        "client": ("127.0.0.1", 51234),
+        "server": ("testserver", 80),
+        "state": {},
+    }
+    sent: list[Message] = []
+    delivered = False
+
+    async def receive() -> Message:
+        nonlocal delivered
+        if delivered:
+            return {"type": "http.disconnect"}
+        delivered = True
+        return {"type": "http.request", "body": b"", "more_body": False}
+
+    async def send(message: Message) -> None:
+        sent.append(message)
+
+    await app(scope, receive, send)
+    return sent
+
+
+def _start_message(messages: list[Message]) -> Message:
+    starts = [message for message in messages if message["type"] == "http.response.start"]
+    assert len(starts) == 1, f"http.response.start 应恰好一条，实际 {len(starts)} 条"
+    return starts[0]
+
+
+def _started_status(messages: list[Message]) -> int:
+    return int(_start_message(messages)["status"])
+
+
+def _started_header(messages: list[Message], name: str) -> str | None:
+    wanted = name.lower()
+    for header_name, value in _start_message(messages).get("headers") or []:
+        if header_name.decode("latin-1").lower() == wanted:
+            return value.decode("latin-1")
+    return None
+
+
+def test_exposed_contract_names_match_the_platform() -> None:
+    """信封（Task 2.4）与日志（Task 2.6）按字面量依赖这两个名字，改名即变红。"""
+    assert TRACE_ID_HEADER == "X-Request-Id"
+    assert TRACE_SOURCE_FIELD == "traceIdSource"
+
+
+def test_new_trace_id_is_16_lowercase_hex() -> None:
+    values = {new_trace_id() for _ in range(200)}
+    assert all(TRACE_ID_PATTERN.fullmatch(value) for value in values)
+    assert len(values) == 200, "200 次生成出现重复：traceId 不满足唯一性"
+
+
+def test_get_trace_id_is_stable_within_one_context() -> None:
+    first = get_trace_id()
+    assert TRACE_ID_PATTERN.fullmatch(first)
+    # 同上下文内必须稳定：否则请求内每行日志都换 id，串链失效
+    assert get_trace_id() == first
+    assert get_trace_source() == TRACE_SOURCE_GENERATED
+
+
+def test_explicit_set_and_token_reset() -> None:
+    token = set_trace_id(GATEWAY_UUID_TRACE_ID)
+    assert get_trace_id() == GATEWAY_UUID_TRACE_ID
+    assert get_trace_source() == TRACE_SOURCE_PROPAGATED
+    reset_trace_id(token)
+    assert get_trace_id() != GATEWAY_UUID_TRACE_ID
+    assert get_trace_source() == TRACE_SOURCE_GENERATED
+
+
+def test_copy_context_for_thread_carries_one_id_and_does_not_bleed_back() -> None:
+    context_copy = copy_context_for_thread()
+    outer = get_trace_id()
+    assert context_copy.run(get_trace_id) == outer, "副本里读不到同一个 traceId"
+    context_copy.run(set_trace_id, INJECTED_TRACE_ID)
+    assert context_copy.run(get_trace_id) == INJECTED_TRACE_ID
+    assert get_trace_id() == outer, "副本内的改动回灌到了外层上下文：说明没真的复制"
+
+
+def test_injected_header_is_used_and_echoed(probe: Probe, probe_client: TestClient) -> None:
+    """注入路径：处理器内同值 + 响应头回显 + 来源标记 propagated。"""
+    response = probe_client.get("/__probe__/context", headers={TRACE_ID_HEADER: INJECTED_TRACE_ID})
+    assert response.status_code == 200
+    assert probe.last.trace_id == INJECTED_TRACE_ID
+    assert probe.last.source == TRACE_SOURCE_PROPAGATED
+    assert response.json()["traceId"] == INJECTED_TRACE_ID
+    assert _echoed_trace_id(response) == INJECTED_TRACE_ID
+
+
+def test_gateway_uuid_value_is_propagated_verbatim(probe: Probe, probe_client: TestClient) -> None:
+    """网关兜底生成的是 UUID：本服务不做「只认 16 位 hex」的额外收紧。"""
+    response = probe_client.get(
+        "/__probe__/context", headers={TRACE_ID_HEADER: GATEWAY_UUID_TRACE_ID}
+    )
+    assert probe.last.trace_id == GATEWAY_UUID_TRACE_ID
+    assert probe.last.source == TRACE_SOURCE_PROPAGATED
+    assert _echoed_trace_id(response) == GATEWAY_UUID_TRACE_ID
+
+
+def test_absent_header_generates_and_marks_generated(
+    probe: Probe, probe_client: TestClient
+) -> None:
+    """缺失路径：自行生成 16 位 hex + 响应头回显 + 来源标记 generated。"""
+    response = probe_client.get("/__probe__/context")
+    generated = probe.last.trace_id
+    assert TRACE_ID_PATTERN.fullmatch(generated), f"生成值不是 16 位 hex：{generated!r}"
+    assert probe.last.source == TRACE_SOURCE_GENERATED
+    assert _echoed_trace_id(response) == generated
+
+
+def test_header_at_length_limit_is_still_accepted(
+    probe: Probe, probe_client: TestClient
+) -> None:
+    """长度边界：恰好 64 位放行（65 位起按缺失处理，见下一条）。"""
+    value = "a" * MAX_TRACE_ID_LENGTH
+    probe_client.get("/__probe__/context", headers={TRACE_ID_HEADER: value})
+    assert probe.last.trace_id == value
+    assert probe.last.source == TRACE_SOURCE_PROPAGATED
+
+
+@pytest.mark.parametrize("length", [MAX_TRACE_ID_LENGTH + 1, 200])
+def test_overlong_header_is_treated_as_absent(
+    probe: Probe, probe_client: TestClient, length: int
+) -> None:
+    hostile = "a" * length
+    response = probe_client.get("/__probe__/context", headers={TRACE_ID_HEADER: hostile})
+    assert probe.last.source == TRACE_SOURCE_GENERATED, "超长头必须按缺失处理（重新生成）"
+    assert TRACE_ID_PATTERN.fullmatch(probe.last.trace_id)
+    echoed = _echoed_trace_id(response)
+    assert echoed == probe.last.trace_id
+    assert hostile not in echoed, "敌意串被回显到了响应头"
+
+
+@pytest.mark.parametrize(
+    "raw_value",
+    [
+        pytest.param(b"trace\nid", id="含换行"),
+        pytest.param(b"trace\r\nX-Injected: 1", id="CRLF-拆头"),
+        pytest.param(b"trace\tid", id="含制表符"),
+        pytest.param(b"trace\x00id", id="含-NUL"),
+        pytest.param(b"trace\x7fid", id="含-DEL"),
+        pytest.param("追踪标识".encode(), id="非-ASCII"),
+        pytest.param(b"   ", id="全空格"),
+    ],
+)
+async def test_hostile_header_bytes_are_treated_as_absent(probe: Probe, raw_value: bytes) -> None:
+    """非法字节一律按缺失处理：重新生成 + 标 generated，原串绝不外泄。"""
+    messages = await _call_asgi(probe.app, headers=[(_trace_header_bytes(), raw_value)])
+    echoed = _started_header(messages, TRACE_ID_HEADER)
+    assert _started_status(messages) == 200
+    assert probe.last.source == TRACE_SOURCE_GENERATED
+    assert echoed == probe.last.trace_id
+    assert echoed is not None and TRACE_ID_PATTERN.fullmatch(echoed)
+    assert raw_value not in echoed.encode("latin-1")
+
+
+async def test_request_runs_in_callers_task(probe: Probe) -> None:
+    """纯 ASGI 的直接证据：处理器与调用方在同一个 asyncio 任务里。
+
+    BaseHTTPMiddleware 会把下游应用丢进新的 anyio 任务（ContextVar 随之隔离），
+    这条断言就是「MUST NOT 用 BaseHTTPMiddleware」的行为判别式：换成它以后
+    处理器内的 current_task() 不再是调用方任务，本用例立刻变红。
+    """
+    caller_task = asyncio.current_task()
+    await _call_asgi(probe.app)
+    assert probe.last.task is caller_task
+
+
+def test_thread_pool_keeps_trace_id_only_when_context_is_passed(
+    probe: Probe, probe_client: TestClient
+) -> None:
+    """跨线程池：ctx.run 带上下文 → 同 id；直接提交 → 丢（阴性对照）。"""
+    response = probe_client.get(
+        "/__probe__/thread-pool", headers={TRACE_ID_HEADER: INJECTED_TRACE_ID}
+    )
+    snapshot = probe.last
+    traced = snapshot.traced_worker
+    untraced = snapshot.untraced_worker
+    assert traced is not None and untraced is not None
+    assert _echoed_trace_id(response) == INJECTED_TRACE_ID
+    # 真的换了线程：否则「跨线程」用例是假的
+    assert traced.thread_ident != snapshot.thread_ident
+    assert untraced.thread_ident != snapshot.thread_ident
+    # 正例：显式传递后线程内读到请求的 traceId
+    assert traced.trace_id == INJECTED_TRACE_ID
+    # 阴性对照：不传上下文就静默丢——正是本任务要防的故障形态
+    assert untraced.trace_id != INJECTED_TRACE_ID
+    assert TRACE_ID_PATTERN.fullmatch(untraced.trace_id)
+
+
+def test_sequential_requests_do_not_share_trace_id(
+    probe: Probe, probe_client: TestClient
+) -> None:
+    first = "1111111111111111"
+    second = "2222222222222222"
+    probe_client.get("/__probe__/context", headers={TRACE_ID_HEADER: first})
+    probe_client.get("/__probe__/context", headers={TRACE_ID_HEADER: second})
+    assert [snapshot.trace_id for snapshot in probe.snapshots] == [first, second]
+    # 第三次不带请求头：必须是全新生成的值，不能粘上前两次中的任何一个
+    response = probe_client.get("/__probe__/context")
+    assert probe.last.trace_id not in {first, second}
+    assert probe.last.source == TRACE_SOURCE_GENERATED
+    assert _echoed_trace_id(response) == probe.last.trace_id
+
+
+async def test_token_reset_clears_context_after_request(probe: Probe) -> None:
+    """ASGI 直调发生在用例自己的上下文里，故能直接验证「按 token 回滚」。"""
+    await _call_asgi(probe.app, headers=[(_trace_header_bytes(), b"deadbeefcafe0000")])
+    assert probe.last.trace_id == "deadbeefcafe0000"
+    assert get_trace_id() != "deadbeefcafe0000", "请求结束后上下文未回滚：同 worker 会串号"
+
+
+def test_escaping_error_still_echoes_injected_trace_id(probe: Probe) -> None:
+    """异常逃逸出应用时，ServerErrorMiddleware 渲染的 500 也要带回显头。"""
+    with TestClient(probe.app, raise_server_exceptions=False) as client:
+        response = client.get("/__probe__/boom", headers={TRACE_ID_HEADER: INJECTED_TRACE_ID})
+    assert response.status_code == 500
+    assert _echoed_trace_id(response) == INJECTED_TRACE_ID
+
+
+def test_escaping_error_without_header_still_echoes_generated_trace_id(probe: Probe) -> None:
+    with TestClient(probe.app, raise_server_exceptions=False) as client:
+        response = client.get("/__probe__/boom")
+    assert response.status_code == 500
+    assert TRACE_ID_PATTERN.fullmatch(_echoed_trace_id(response))
+
+
+def test_unhandled_error_handler_reads_the_same_trace_id() -> None:
+    """逃逸异常的处理链仍能读到同一个 traceId（Task 2.4 的 500 信封要用）。
+
+    注册在 `Exception` 上的处理器会被 Starlette 提升到 ServerErrorMiddleware——只有在
+    traceId 中间件位于 ServerErrorMiddleware **之外**时，处理器执行时上下文才尚未回滚。
+    顺带证明：换成 `add_middleware`（内层）后，信封里的 traceId 会变成另一个新生成的值
+    （实测 `add_middleware` 路径下响应头缺失、信封 traceId = 新生成的 743a…，与网关值不符）。
+    """
+    app = create_app()
+
+    @app.get("/__probe__/error-envelope")
+    async def boom() -> dict[str, str]:
+        raise RuntimeError("探针：模拟逃逸出应用的未捕获异常")
+
+    @app.exception_handler(Exception)
+    async def handle(request: Request, exc: Exception) -> JSONResponse:
+        # 信封（Task 2.4）在生产代码里就是这么取 traceId 的
+        return JSONResponse({"traceId": get_trace_id()}, status_code=500)
+
+    with TestClient(app, raise_server_exceptions=False) as client:
+        response = client.get(
+            "/__probe__/error-envelope", headers={TRACE_ID_HEADER: INJECTED_TRACE_ID}
+        )
+    assert response.status_code == 500
+    assert _echoed_trace_id(response) == INJECTED_TRACE_ID
+    assert response.json()["traceId"] == INJECTED_TRACE_ID
+
+
+def test_not_found_response_also_echoes_trace_id(client: TestClient) -> None:
+    """回显覆盖到框架自己产生的响应（404 等），不只是路由返回的响应。"""
+    response = client.get("/no-such-route")
+    assert response.status_code == 404
+    assert TRACE_ID_PATTERN.fullmatch(_echoed_trace_id(response))
+
+
+def test_health_stays_bare_and_still_echoes_trace_id(client: TestClient) -> None:
+    """/health 仍是裸响应（不回包信封），同时照常带回显头。"""
+    response = client.get("/health", headers={TRACE_ID_HEADER: INJECTED_TRACE_ID})
+    assert response.json() == {"status": "ok"}
+    assert _echoed_trace_id(response) == INJECTED_TRACE_ID

```
