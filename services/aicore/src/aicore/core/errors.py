"""异常层次与错误码映射（Task 2.3）。

本模块是**业务码 → HTTP 响应**的唯一出口：业务代码只抛异常，不自行拼装信封
（design.md：业务代码只抛业务异常，不自行拼装信封，否则错误码口径会散落）。
三条路径全部归口在这里注册：

1. 业务异常 `AiCoreError` → 下表对应的 HTTP 状态 + 平台信封；
2. 框架的 `RequestValidationError`（FastAPI 默认 HTTP 422 + `{"detail": [...]}`）→ 收编成
   同一个信封，业务码按 pydantic 的 error `type` 归入 `1xxx`；
3. 未预期异常 → HTTP 500 + `code=5000`，**堆栈只进日志、不进响应体**。

**业务码与 HTTP 状态严格分离**：下表的 HTTP 状态只是「送达方式」，`code` 字段永远只放
业务码（口径来源：`services/_common/openapi.yaml` 的 `ErrorCode` 枚举与各 response 示例）。

| 业务码 | HTTP | 含义 | 本服务的承载者 |
| --- | --- | --- | --- |
| `1001` | 400（框架校验为 422） | 参数缺失 | `ParamError(code=1001)` / 校验缺参 |
| `1002` | 400（框架校验为 422） | 参数格式错误 | `ParamError()`（默认码）/ 校验类型或解析失败 |
| `1003` | 400（框架校验为 422） | 枚举或范围非法 | `ParamError(code=1003)` / 校验枚举或范围失败 |
| `2001` | 401 | 未登录 / Token 失效 | `UnauthorizedError` |
| `2002` | 403 | 无权限 / 越权 | `ForbiddenError` |
| `2004` | 429 | 请求过于频繁 | `RateLimitedError` |
| `3006` | 404 | 对象不存在 | `NotFoundError` |
| `4003` | 502 | 大模型 / 视觉 API 失败 | `ChannelFailureError` |
| `5000` | 500 | 内部错误 | 未预期异常的兜底处理器 |
| `5002` | 504 | 依赖超时 / 熔断 | `DependencyTimeoutError` |

**`429` 是 HTTP 状态，业务码是 `2004`**：`code` 字段 MUST NOT 出现 `429`。前端按
`code === 0` 判断成功，故限流响应必须同时带 429 与 `code=2004`（`_common` 的
`RateLimited` 明写这一点）。同理 `code` 也不放 `400`/`404`/`500` 这类 HTTP 状态。

框架校验路径保留 HTTP 422：`400` 与 `422` 都是「参数类失败」的送达方式，业务码同为
`1xxx`；保留框架原生状态可让既有客户端与监控按原有语义继续识别，前端要认的是**响应体**。

参数校验的 error `type` → 业务码（pydantic v2 的 type 字符串，`RequestValidationError.errors()`
里的 `type` 字段）：

| 业务码 | 判定依据 |
| --- | --- |
| `1001` | `missing` —— 必填项没送到 |
| `1003` | 枚举或字面量（`enum` / `literal_error`）、数值范围（`greater_than*` / `less_than*` /
`multiple_of` / `finite_number`）、长度范围（`too_short` / `too_long` / `string_too_short` /
`string_too_long` / `bytes_too_short` / `bytes_too_long`） |
| `1002` | 其余全部（类型不符、解析失败、pattern 不匹配、多余字段等）—— 兜底档 |

同一请求里多个错误同时命中时**只回一个码**，优先级 `1001` > `1003` > `1002`：
缺参是最该先补齐的问题，枚举/范围比格式更具体，`1002` 才是兜底。

响应的 `message` 只取平台固定文案（`DEFAULT_MESSAGES`），**不回显 pydantic 的 `msg`/`loc`**：
`msg` 是英文框架文案，且自定义校验器抛 `ValueError` 时会把用户输入带进 msg（PII 泄漏通道）；
字段名与 type 只进日志（且只取 `type`/`loc`，不取 pydantic error dict 里的 `input`/`ctx`）。
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, Final, cast

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from aicore.core.trace import get_trace_id

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 业务码常量
#
# 取值只能来自 `_common/openapi.yaml` 的 ErrorCode 枚举；本服务只用到其中 10 个。
# 常量名一律以 `_CODE` 结尾且带 `CODE` 字样：**它们是业务码，不是 HTTP 状态码**，
# 两者读写时 MUST NOT 互相代入（例如 `RATE_LIMITED_CODE` 是 2004，不是 429）。
# ---------------------------------------------------------------------------

#: 参数缺失。
PARAM_MISSING_CODE: Final = 1001
#: 参数格式错误。
PARAM_FORMAT_CODE: Final = 1002
#: 枚举或范围非法。
PARAM_VALUE_CODE: Final = 1003
#: 未登录 / Token 失效。
UNAUTHORIZED_CODE: Final = 2001
#: 无权限 / 越权。
FORBIDDEN_CODE: Final = 2002
#: 请求过于频繁（网关级限流与服务域成本护栏共用）。
RATE_LIMITED_CODE: Final = 2004
#: 对象不存在。
NOT_FOUND_CODE: Final = 3006
#: 大模型 / 视觉 API 失败。
CHANNEL_FAILURE_CODE: Final = 4003
#: 内部错误（未预期异常的兜底码）。
INTERNAL_ERROR_CODE: Final = 5000
#: 依赖超时 / 熔断。
DEPENDENCY_TIMEOUT_CODE: Final = 5002

#: 参数类业务码三档（缺失 / 格式 / 枚举或范围）。
PARAM_ERROR_CODES: Final[frozenset[int]] = frozenset(
    {PARAM_MISSING_CODE, PARAM_FORMAT_CODE, PARAM_VALUE_CODE}
)

#: 本服务**可能发出**的全部业务码，供 test_errors.py 与 Task 2.4 比对使用。
#: 成功码 `0` 不在内（它不是错误码）；HTTP 状态码（400/422/429/500…）也不在内。
AICORE_ERROR_CODES: Final[frozenset[int]] = frozenset(
    {
        *PARAM_ERROR_CODES,
        UNAUTHORIZED_CODE,
        FORBIDDEN_CODE,
        RATE_LIMITED_CODE,
        NOT_FOUND_CODE,
        CHANNEL_FAILURE_CODE,
        INTERNAL_ERROR_CODE,
        DEPENDENCY_TIMEOUT_CODE,
    }
)

#: 业务码 → HTTP 状态。**只在本模块内部用于渲染响应**，业务码本身不含状态语义。
#: 1xxx 三档对应 400（业务侧参数异常）；框架校验路径另用 VALIDATION_HTTP_STATUS=422。
HTTP_STATUS_BY_ERROR_CODE: Final[Mapping[int, int]] = {
    PARAM_MISSING_CODE: 400,
    PARAM_FORMAT_CODE: 400,
    PARAM_VALUE_CODE: 400,
    UNAUTHORIZED_CODE: 401,
    FORBIDDEN_CODE: 403,
    RATE_LIMITED_CODE: 429,
    NOT_FOUND_CODE: 404,
    CHANNEL_FAILURE_CODE: 502,
    INTERNAL_ERROR_CODE: 500,
    DEPENDENCY_TIMEOUT_CODE: 504,
}

#: 框架参数校验失败的 HTTP 状态：保留 FastAPI 原生的 422，只把响应体换成平台信封。
VALIDATION_HTTP_STATUS: Final = 422

#: 每个业务码的默认提示文案：取自 `_common/openapi.yaml` 各 response 示例的 message，
#: 面向用户、可直接展示 —— 故 MUST NOT 拼接内部细节（异常消息、文件路径、模块名、字段名）。
#: test_errors.py 钉住「键集恰好等于 AICORE_ERROR_CODES」，新增码值时必须同时补文案。
DEFAULT_MESSAGES: Final[Mapping[int, str]] = {
    PARAM_MISSING_CODE: "参数缺失",
    PARAM_FORMAT_CODE: "参数格式错误",
    PARAM_VALUE_CODE: "枚举或范围非法",
    UNAUTHORIZED_CODE: "未登录或 Token 已失效",
    FORBIDDEN_CODE: "无权限访问该资源",
    RATE_LIMITED_CODE: "请求过于频繁，请稍后重试",
    NOT_FOUND_CODE: "对象不存在",
    CHANNEL_FAILURE_CODE: "大模型或视觉 API 失败",
    INTERNAL_ERROR_CODE: "服务内部错误",
    DEPENDENCY_TIMEOUT_CODE: "依赖超时或熔断",
}

#: 校验错误 type → `1xxx`。见模块 docstring 的映射表；未列出的 type 一律落 1002（兜底）。
_MISSING_ERROR_TYPES: Final[frozenset[str]] = frozenset({"missing"})

_RANGE_ERROR_TYPES: Final[frozenset[str]] = frozenset(
    {
        "enum",
        "literal_error",
        "greater_than",
        "greater_than_equal",
        "less_than",
        "less_than_equal",
        "multiple_of",
        "finite_number",
        "too_short",
        "too_long",
        "string_too_short",
        "string_too_long",
        "bytes_too_short",
        "bytes_too_long",
    }
)


class AiCoreError(Exception):
    """业务异常基类：所有**可预期**的业务失败都从这里派生。

    两个字段的语义（MUST NOT 混用）：

    - `code`：**业务码**，取值只能是 `AICORE_ERROR_CODES` 内的值，构造期强校验；
    - `message`：面向用户的提示文案，缺省时取平台文案 `DEFAULT_MESSAGES[code]`。

    `code` 是类属性、`message` 是实例属性：子类只声明「我是哪一类失败」，调用方按需覆盖文案。
    非法码在**构造期**抛 `ValueError`（fail fast）：写错码值应当立刻炸在开发/测试期，
    而不是把一个平台表里不存在的码送到前端。
    """

    #: 缺省码：未声明码值的派生类按「内部错误」处理（不猜业务语义）。
    code: int = INTERNAL_ERROR_CODE

    def __init__(self, message: str | None = None) -> None:
        if self.code not in AICORE_ERROR_CODES:
            raise ValueError(
                f"业务码 {self.code} 不在本服务的错误码集合 {sorted(AICORE_ERROR_CODES)} 内："
                f"码值只能取 _common/openapi.yaml 的 ErrorCode 枚举"
            )
        self.message: str = DEFAULT_MESSAGES[self.code] if message is None else message
        super().__init__(self.message)


class ParamError(AiCoreError):
    """参数类错误：`1001` 缺失 / `1002` 格式 / `1003` 枚举或范围。

    **形状选择（本模块的口径）**：三档共用一个类，具体档位由构造参数 `code` 指定，
    缺省 `1002`（参数格式错误）。理由：

    - 平台把 1xxx 三档放在同一段，彼此的差别只有「缺失 / 格式 / 枚举或范围」这一个维度，
      拆成三个类会让调用方在「这算格式还是算范围」上多做一次类选择；
    - 缺省 1002 与框架校验路径的兜底码一致（`_validation_error_code`）：两条路径对
      「归不了类的参数错误」给出同一个码，前端只需要记一个兜底值；
    - `code` 只接受 `PARAM_ERROR_CODES` 内的值，传 `2001` 之类跨段的码直接抛 `ValueError`。
    """

    code: int = PARAM_FORMAT_CODE

    def __init__(self, message: str | None = None, *, code: int | None = None) -> None:
        if code is not None:
            if code not in PARAM_ERROR_CODES:
                raise ValueError(
                    f"ParamError 的 code 只能是 {sorted(PARAM_ERROR_CODES)}，收到 {code}"
                )
            self.code = code
        super().__init__(message)


class UnauthorizedError(AiCoreError):
    """未登录 / Token 失效（`2001`，HTTP 401）。

    本服务语境下指**内部凭据无效**（网关凭据、内部 Token 校验不通过），
    面向调用方不区分「没带」与「带了但无效」——两种情况的处置动作相同。
    """

    code: int = UNAUTHORIZED_CODE


class ForbiddenError(AiCoreError):
    """无权限 / 越权（`2002`，HTTP 403）。"""

    code: int = FORBIDDEN_CODE


class RateLimitedError(AiCoreError):
    """请求过于频繁（`2004`，HTTP 429）。

    网关级限流与服务域成本护栏（日配额 / 日预算）共用本码：两者对调用方都是
    「稍后重试」，差别只在服务端计数口径。
    """

    code: int = RATE_LIMITED_CODE


class NotFoundError(AiCoreError):
    """对象不存在（`3006`，HTTP 404）。"""

    code: int = NOT_FOUND_CODE


class ChannelFailureError(AiCoreError):
    """大模型 / 视觉 API 失败（`4003`，HTTP 502）：**等到响应但响应是失败**。

    与 `DependencyTimeoutError` 严格区分：两者计数与告警口径不同。
    """

    code: int = CHANNEL_FAILURE_CODE


class DependencyTimeoutError(AiCoreError):
    """依赖超时 / 熔断（`5002`，HTTP 504）：**没等到响应**。"""

    code: int = DEPENDENCY_TIMEOUT_CODE


def register_exception_handlers(app: FastAPI) -> None:
    """把三条错误路径收编到平台信封。由组合根 `main.create_app()` 调用。

    - `AiCoreError` → 业务码对应的 HTTP 状态 + 信封；
    - `RequestValidationError` → HTTP 422 + `1xxx` 信封（收编框架默认的 `{"detail": [...]}`，
      否则前端会同时收到两种响应形状）；
    - `Exception` → HTTP 500 + `code=5000` 信封（Starlette 会把它提升为 ServerErrorMiddleware
      的 error_handler，故「逃逸出应用的未预期异常」也走信封；组合根把 traceId 中间件包在
      ServerErrorMiddleware 之外，处理器执行时上下文尚未回滚，信封里的 traceId 与请求一致）。

    幂等：同一应用上重复调用只是覆盖同名处理器，`create_app()` 可被多次调用。
    """
    app.add_exception_handler(AiCoreError, _handle_ai_core_error)
    app.add_exception_handler(RequestValidationError, _handle_request_validation_error)
    app.add_exception_handler(Exception, _handle_unexpected_error)


async def _handle_ai_core_error(request: Request, exc: Exception) -> JSONResponse:
    """业务异常 → 信封。

    `exc` 的注解是 `Exception` 而非 `AiCoreError`：Starlette 的 `ExceptionHandler` 把第二
    个参数声明为基类，写窄类型过不了 mypy strict；类型由注册契约保证，故此处 `cast`。
    """
    error = cast(AiCoreError, exc)
    status_code = HTTP_STATUS_BY_ERROR_CODE[error.code]
    body = _error_body(error.code, error.message)
    logger.info(
        "业务异常 code=%s http=%s method=%s path=%s traceId=%s",
        error.code,
        status_code,
        request.method,
        request.url.path,
        body["traceId"],
    )
    return JSONResponse(status_code=status_code, content=body)


async def _handle_request_validation_error(request: Request, exc: Exception) -> JSONResponse:
    """FastAPI 默认 422 → 平台信封（HTTP 状态保留 422，响应体换成信封）。"""
    errors = cast(RequestValidationError, exc).errors()
    code = _validation_error_code(errors)
    logger.info(
        "请求参数校验未通过 code=%s path=%s errors=%s",
        code,
        request.url.path,
        _loggable_errors(errors),
    )
    return JSONResponse(
        status_code=VALIDATION_HTTP_STATUS,
        content=_error_body(code, DEFAULT_MESSAGES[code]),
    )


async def _handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    """未预期异常 → HTTP 500 + `code=5000`，堆栈只进日志。

    响应体**只**放平台固定文案：`str(exc)`、traceback、文件路径、模块名一律不进响应
    （test_errors.py 正面钉住「响应体里没有这些串」）。

    显式传 `exc_info=exc` 而不用 `logger.exception()`：本处理器是 Starlette 在 `except`
    块里 await 的，`logger.exception()` 依赖 `sys.exc_info()`，把异常对象本身交给日志
    才与「一定记下这条异常的堆栈」等价。
    """
    logger.error(
        "未预期异常 code=%s method=%s path=%s traceId=%s",
        INTERNAL_ERROR_CODE,
        request.method,
        request.url.path,
        get_trace_id(),
        exc_info=exc,
    )
    return JSONResponse(
        status_code=HTTP_STATUS_BY_ERROR_CODE[INTERNAL_ERROR_CODE],
        content=_error_body(INTERNAL_ERROR_CODE, DEFAULT_MESSAGES[INTERNAL_ERROR_CODE]),
    )


def _validation_error_code(errors: Sequence[Mapping[str, Any]]) -> int:
    """按「缺失 > 枚举或范围 > 格式」的优先级，把校验错误归到 `1xxx`。

    只回一个码：信封只承载一个业务码，多个字段同时失败时按优先级取最该先修的那个。
    无法归类的 type 落 `1002`（兜底），故新增 pydantic 错误类型不会漏成 5000。
    """
    types = {str(item.get("type", "")) for item in errors}
    if types & _MISSING_ERROR_TYPES:
        return PARAM_MISSING_CODE
    if types & _RANGE_ERROR_TYPES:
        return PARAM_VALUE_CODE
    return PARAM_FORMAT_CODE


def _loggable_errors(errors: Sequence[Mapping[str, Any]]) -> list[tuple[str, tuple[Any, ...]]]:
    """只取 `type` 与 `loc` 供日志：pydantic 的 error dict 还含 `input`（用户原值）与
    `ctx`（可能是带值的异常消息），整体序列化会把用户输入写进日志（PII 泄漏通道）。
    """
    return [(str(item.get("type", "")), tuple(item.get("loc", ()))) for item in errors]


def _error_body(code: int, message: str) -> dict[str, Any]:
    """失败信封：`code` / `message` / `traceId` / `timestamp` 四必填字段 + `data: null`。

    **这里的形状是刻意的**：它就是 `_common/openapi.yaml` 的 `Envelope` 形状，与 Task 2.4
    的 `core/envelope.py` 模型同形，不是重复定义 —— Task 2.3 先于 Task 2.4 落地，异常处理器
    不能等模型就位才能返回错误响应，故此处用等价 dict 承载；`Envelope` 模型（及
    `Envelope.ok/fail`）由 **Task 2.4 拥有**，届时以「本处理器的输出能通过该模型校验」
    反向对齐，MUST NOT 在 core/envelope.py 之外再造一个模型类。

    `timestamp` 为 UTC ISO 8601（`Z` 结尾，与 `_common` 示例 `2026-01-15T10:30:00Z` 同形）；
    `traceId` 一律取自 `core/trace.py` 的 `get_trace_id()`，不另造来源。
    """
    return {
        "code": code,
        "message": message,
        "data": None,
        "traceId": get_trace_id(),
        "timestamp": _utc_timestamp(),
    }


def _utc_timestamp() -> str:
    """当前时刻的 UTC ISO 8601 字符串，例：`2026-01-15T10:30:00.123456Z`。"""
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
