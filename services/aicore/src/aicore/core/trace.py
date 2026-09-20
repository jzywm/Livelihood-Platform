"""traceId 上下文与传播（Task 2.5）。

链路：GATEWAY 在入口注入 `X-Request-Id`（PDD L1750）→ 本模块解析并写入 ContextVar
→ 日志（Task 2.6）与出向调用取用 → 响应头按原值回显。

三条不可退让的约束：

1. 请求头固定是 **`X-Request-Id`**（不是 `X-Trace-Id`）；
2. 头缺失或非法时**自行生成** 16 位小写 hex，并在日志字段 `traceIdSource` 中标记
   `generated`（网关注入的标 `propagated`）。少了这个标记，「网关没注入」会被本地
   生成的 traceId 掩盖，排障时反而查不出网关故障；
3. 跨线程池（`run_in_executor`）**必须显式传递**上下文：新线程的 Context 是空的，
   traceId 会静默丢失（表现为「部分日志串不起来」），故提供 copy_context_for_thread()。
"""

from __future__ import annotations

import secrets
from collections.abc import Iterable
from contextvars import Context, ContextVar, Token, copy_context
from dataclasses import dataclass
from typing import Final

from starlette.types import ASGIApp, Message, Receive, Scope, Send

#: 网关注入 traceId 用的请求头。**不是** `X-Trace-Id`（该写成缺陷）。
TRACE_ID_HEADER: Final = "X-Request-Id"

#: 日志标记字段名：区分「网关注入」与「本服务自行生成」。
TRACE_SOURCE_FIELD: Final = "traceIdSource"

#: 来源标记取值：来自上游（网关注入的请求头）。
TRACE_SOURCE_PROPAGATED: Final = "propagated"

#: 来源标记取值：本服务自行生成（头缺失或非法）。
TRACE_SOURCE_GENERATED: Final = "generated"

#: 16 位小写 hex（对齐 `_common` 示例 `3f2a1b9c8d7e6f50`）。
TRACE_ID_HEX_LENGTH: Final = 16

#: 外来 traceId 的长度上限：与平台 `X-Request-Id` 口径一致（网关侧同为 64）。
MAX_TRACE_ID_LENGTH: Final = 64

_TRACE_ID_BYTES: Final = TRACE_ID_HEX_LENGTH // 2
_PRINTABLE_MIN: Final = 0x20
_PRINTABLE_MAX: Final = 0x7E
_TRACE_HEADER_BYTES: Final = TRACE_ID_HEADER.encode("ascii").lower()


@dataclass(frozen=True, slots=True)
class TraceContext:
    """当前上下文绑定的 traceId 及其来源标记。

    值存放在**同一个** ContextVar 里：这样一次 `set` 只产生一个 token，
    回滚 `reset_trace_id(token)` 时 traceId 与来源标记原子恢复，不会出现
    「值回滚了、标记留在原地」的半截状态。
    """

    trace_id: str
    source: str


_TRACE_VAR: ContextVar[TraceContext | None] = ContextVar("aicore_trace_context", default=None)


def new_trace_id() -> str:
    """生成新的 traceId：16 位小写 hex。

    用 `secrets` 而不是 `random`：traceId 会进日志与响应头，可预测的 id 便于
    攻击者伪造/碰撞，而代价只是一个 CSPRNG 调用。
    """
    return secrets.token_hex(_TRACE_ID_BYTES)


def _current() -> TraceContext:
    """取当前上下文绑定；未绑定时先生成并按 `generated` 标记。

    生成后**写回上下文**：同一上下文内多次取到同一个 id，
    否则每个请求内每行日志都会换一个 traceId，串链失效。
    """
    context = _TRACE_VAR.get()
    if context is None:
        context = TraceContext(trace_id=new_trace_id(), source=TRACE_SOURCE_GENERATED)
        _TRACE_VAR.set(context)
    return context


def get_trace_id() -> str:
    """当前 traceId；未设置时生成一个存入当前上下文。

    请求外的上下文（后台任务、CLI、线程池漏传上下文后的兜底）同样拿到一个
    可串链的 id，而不是空串。
    """
    return _current().trace_id


def get_trace_source() -> str:
    """当前 traceId 的来源标记（`propagated` / `generated`）。

    与 get_trace_id() 同源：未绑定时同样先生成、按 `generated` 标记，
    故日志处理器先取 id 还是先取来源，结果一致。
    """
    return _current().source


def set_trace_id(
    value: str, *, source: str = TRACE_SOURCE_PROPAGATED
) -> Token[TraceContext | None]:
    """显式绑定 traceId，返回可交给 reset_trace_id() 回滚的 token。

    `source` 默认 `propagated`：显式设置的值都来自上游（网关请求头、上游任务负载）。
    本服务自行生成的值走 get_trace_id()，或显式传 `source=TRACE_SOURCE_GENERATED`。

    签名说明：任务简报写的是 `-> None`。但 reset_trace_id(token) 需要 token，
    否则「绑定 → 回滚」这一对无法成对使用，而回滚是防同 worker 串号的唯一手段；
    返回 token 是 `-> None` 的严格超集——忽略返回值即等同 `-> None` 用法。
    """
    return _TRACE_VAR.set(TraceContext(trace_id=value, source=source))


def reset_trace_id(token: Token[TraceContext | None] | None = None) -> None:
    """回滚上下文：请求结束（含异常路径）必须调用。

    worker 进程/线程会被复用，不回滚则上一个请求的 traceId 会粘到下一个请求上
    ——串号比「没有 traceId」更难查。token 只能在创建它的上下文里回滚（ContextVar 语义）。

    token 省略时直接清空当前上下文（后台任务收尾、用例隔离）。
    """
    if token is None:
        _TRACE_VAR.set(None)
        return
    _TRACE_VAR.reset(token)


def copy_context_for_thread() -> Context:
    """复制当前上下文，用于把 traceId 显式带进线程池。

    用法（`ctx.run` 必须作为**被调用的可调用对象**交给 run_in_executor）::

        ctx = copy_context_for_thread()
        result = await asyncio.get_running_loop().run_in_executor(pool, ctx.run, fn)

    需要给 `fn` 传参时继续往后排位置参数，`run_in_executor` 会原样转给 `ctx.run`::

        await loop.run_in_executor(pool, ctx.run, fn, arg1, arg2)   # 等价 ctx.run(fn, arg1, arg2)

    为什么必须这么写：`run_in_executor(pool, fn)` 在线程池线程里执行 `fn`，新线程的
    Context 是空的，`fn` 里的 `get_trace_id()` 只会再生成一个新 id——traceId 静默丢失，
    正是「部分日志串不起来」的成因。`ctx.run(fn)` 把复制出来的上下文带进该线程，
    `fn` 内读到的 traceId 与请求内一致。

    两个使用要点：

    - 同一个 `Context` 不能被重入（同一时刻只允许一个 `ctx.run` 在跑），
      故每个任务 / 每次提交都要重新调用本函数复制一份；
    - 当前上下文若还没有 traceId，本函数会先生成一个（标记 `generated`）再复制，
      保证线程池里的日志同样可串链。
    """
    get_trace_id()
    return copy_context()


class TraceIdMiddleware:
    """纯 ASGI 中间件：`X-Request-Id` → ContextVar（同任务）→ 响应头回显。

    **为什么不用 `BaseHTTPMiddleware`**：它把下游应用丢进独立的 anyio 任务，
    ContextVar 与请求不再处于同一个任务（本模块的用例以「处理器内的
    `asyncio.current_task()` 必须等于调用方任务」正面守住这一点），
    异常还会被改写成 `ExceptionGroup`。故这里直接实现 ASGI 协议。

    **为什么由组合根包在最外层**（见 `aicore/main.py` 的 `_TracedFastAPI`）：
    Starlette 固定把用户中间件放在 ServerErrorMiddleware 之内，未捕获异常由后者
    在最外层渲染 500；只有包在最外层，「异常逃逸 → 500」这条路径才带得上回显头。
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            # lifespan / websocket 不参与 HTTP traceId 传播，原样放行。
            await self.app(scope, receive, send)
            return

        trace_id, source = _resolve_trace_id(scope.get("headers") or ())
        token = set_trace_id(trace_id, source=source)
        try:
            await self.app(scope, receive, _send_with_trace_id(send, trace_id))
        finally:
            reset_trace_id(token)


def _send_with_trace_id(send: Send, trace_id: str) -> Send:
    """包装 send：在响应起始消息上回显 `X-Request-Id`。

    先剔除应用自己写的同名头，保证回显值唯一且可信（应用写错也不会出现两个）。
    不改原列表、而是换一个新列表：`http.response.start` 里的 headers 很可能就是
    响应对象自身的 `raw_headers`，原地 append 会污染该响应对象。
    """
    echoed: tuple[bytes, bytes] = (TRACE_ID_HEADER.encode("ascii"), trace_id.encode("ascii"))

    async def send_with_trace_id(message: Message) -> None:
        if message["type"] == "http.response.start":
            kept = [
                (name, value)
                for name, value in message.get("headers") or []
                if name.lower() != _TRACE_HEADER_BYTES
            ]
            message["headers"] = [*kept, echoed]
        await send(message)

    return send_with_trace_id


def _resolve_trace_id(headers: Iterable[tuple[bytes, bytes]]) -> tuple[str, str]:
    """解析待绑定的 traceId 与来源标记：能用的头按 `propagated`，否则生成。"""
    accepted = _sanitize_trace_id(_incoming_trace_id(headers))
    if accepted is None:
        return new_trace_id(), TRACE_SOURCE_GENERATED
    return accepted, TRACE_SOURCE_PROPAGATED


def _incoming_trace_id(headers: Iterable[tuple[bytes, bytes]]) -> str | None:
    """取第一个 `X-Request-Id`（ASGI 头名一律小写；重名取首个，与网关口径一致）。"""
    for name, value in headers:
        if name.lower() == _TRACE_HEADER_BYTES:
            # 用 latin-1 解码：头是任意字节，latin-1 不会抛异常；非 ASCII 字节会解成
            # > 0x7E 的字符，随后被 _sanitize_trace_id 判为非法（等价于头缺失）。
            return value.decode("latin-1")
    return None


def _sanitize_trace_id(raw: str | None) -> str | None:
    """校验外来 traceId，非法返回 None（调用方按「头缺失」处理：生成 + 标 generated）。

    接受条件（全部满足）：

    - 非空且长度 ≤ MAX_TRACE_ID_LENGTH；
    - 每个字符都是可打印 ASCII（0x20~0x7E）——控制字符（含 CR/LF）、DEL、
      非 ASCII（含中文、emoji）一律拒绝。这既防日志伪造（换行注假日志行），
      也防响应头注入（CRLF 拆头）；
    - 至少含一个非空格字符：全空格是无意义值，按缺失处理。

    拒绝即丢弃原值，绝不把攻击者可控的原始串写进日志或响应头；
    `traceIdSource=generated` 让这次「丢弃 + 重生成」在日志里可见。
    """
    if raw is None or raw == "" or len(raw) > MAX_TRACE_ID_LENGTH:
        return None
    if any(not (_PRINTABLE_MIN <= ord(char) <= _PRINTABLE_MAX) for char in raw):
        return None
    if not raw.strip():
        return None
    return raw
