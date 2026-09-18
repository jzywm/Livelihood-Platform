"""异常层次与错误码映射（Task 2.3）。

本模块是**业务码 → HTTP 响应**的唯一出口：业务代码只抛异常，不自行拼装信封
（design.md：业务代码只抛业务异常，不自行拼装信封，否则错误码口径会散落）。
四条路径全部归口在这里注册：

1. 业务异常 `AiCoreError` → 下表对应的 HTTP 状态 + 平台信封；
2. 框架的 `RequestValidationError`（FastAPI 默认 HTTP 422 + `{"detail": [...]}`）→ 收编成
   同一个信封，业务码按 pydantic 的 error `type` 归入 `1xxx`；
3. 框架的 `HTTPException`（Starlette 基类，FastAPI 的 `HTTPException` 由它派生）→ 收编成
   同一个信封，业务码按 HTTP 状态映射（见下「框架 HTTPException」一节）。
   **必须显式注册**：FastAPI 构造时就为 `starlette.exceptions.HTTPException` 这个键预注册了
   它的 `http_exception_handler`（回 `{"detail": …}` 的 JSON），本模块的注册是**覆盖**它
   （不是并存）；Starlette 的路由层在**匹配不到路径**（404）与**方法不允许**（405）时抛的
   正是这个基类实例，不注册就没有 `code` 字段——前端要多认一种形状。同理，`HTTPBearer`
   之类的框架依赖在内部抛 `HTTPException(401/403)`，调用点无法拦截；
4. 未预期异常 → HTTP 500 + `code=5000`，**堆栈只进日志、不进响应体**。

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
`string_too_long` / `bytes_too_short` / `bytes_too_long`）、Decimal 位数范围
（`decimal_max_digits` / `decimal_max_places` / `decimal_whole_digits`） |
| `1002` | 其余全部（类型不符、解析失败、pattern 不匹配、多余字段等）—— 兜底档 |

同一请求里多个错误同时命中时**只回一个码**，优先级 `1001` > `1003` > `1002`：
缺参是最该先补齐的问题，枚举/范围比格式更具体，`1002` 才是兜底。

响应的 `message` 只取平台固定文案（`DEFAULT_MESSAGES`），**不回显 pydantic 的 `msg`/`loc`**：
`msg` 是英文框架文案，且自定义校验器抛 `ValueError` 时会把用户输入带进 msg（PII 泄漏通道）；
字段名与 type 只进日志（且只取 `type`/`loc`，不取 pydantic error dict 里的 `input`/`ctx`）。

框架 `HTTPException` 的**状态 → 业务码**映射（`HTTP_STATUS_BY_HTTP_EXCEPTION_STATUS`，
HTTP 状态原样保留，只换响应体）：

| HTTP | 业务码 | 依据 |
| --- | --- | --- |
| 401 | `2001` | 锁定对（`_common` 的 Unauthorized 示例即 2001） |
| 403 | `2002` | 锁定对（Forbidden） |
| 404 | `3006` | 锁定对（NotFound），但文案用「接口不存在」以便与业务 `NotFoundError` 区分 |
| 429 | `2004` | 锁定对（RateLimited） |
| 502 | `4003` | 锁定对（大模型 / 视觉 API 失败） |
| 504 | `5002` | 锁定对（依赖超时 / 熔断） |
| 500 | `5000` | 锁定对（内部错误） |
| 其余 < 500（4xx 与 sub-400） | `1001` | 兜底：见 `HTTP_EXCEPTION_SUB_5XX_FALLBACK_CODE` 的注释 |
| 其余 5xx | `5000` | 兜底：5xx 对本服务都是「内部错误」这一档 |

**无体状态（与框架契约对齐）**：`1xx` / `204` / `205` / `304` 按 HTTP 契约**不允许响应体**，
FastAPI 默认处理器对这些状态回的就是无体 `Response`（`fastapi/exception_handlers.py` 用
`is_body_allowed_for_status_code` 判定）。收编响应体 MUST NOT 改变这一点，故本模块复用**同一个**
判定函数（`fastapi.utils.is_body_allowed_for_status_code`，不自行重推 1xx/204/304 规则），
无体状态返回无体 `Response` 并同样透传 `exc.headers`。当前不可达（路由层只抛 404/405，
业务代码抛 `AiCoreError`），是刻意镜像框架契约。

**文案策略**：框架的 `exc.detail` 是给开发者看的（`HTTPBearer` 抛的就是
`"Not authenticated"` / `"Not enough permissions"`），故一律换成平台面向用户的文案，
MUST NOT 把 `detail` 回显进响应体；`detail` 也不进日志（它可能带上游传入的内容）。
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, Final, NamedTuple, cast

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.utils import is_body_allowed_for_status_code
from starlette.exceptions import HTTPException as StarletteHTTPException

from aicore.core.trace import get_trace_id

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 业务码常量
#
# 取值只能来自 `_common/openapi.yaml` 的 ErrorCode 枚举；本服务只用到其中 10 个。
# 常量名一律以 `_CODE` 结尾且带 `CODE` 字样：**它们是业务码，不是 HTTP 状态码**，
# 两者读写时 MUST NOT 互相代入（例如 `RATE_LIMITED_CODE` 是 2004，不是 429）。
#
# ===========================================================================
# 【新增一个业务码的完整清单：四处，缺一处就会静默出错】
#
#   1. 本文件顶部的码值常量（`XXX_CODE`）——并把它加进下面的 `AICORE_ERROR_CODES`。
#      ⚠ 漏掉这一处最危险：raise 侧会在**构造期**抛 ValueError，
#        于是业务失败被 500 处理器接走，前端拿到 5000（而不是新码）。
#   2. 本文件的 `DEFAULT_MESSAGES`——缺文案会在渲染信封时 KeyError（等于 500）。
#   3. 本文件的 `HTTP_STATUS_BY_ERROR_CODE`——缺状态会在渲染信封时 KeyError。
#   4. `tests/unit/test_errors.py` 里**用字面量钉住的两张表**：
#      `test_aicore_error_codes_is_exactly_the_emittable_set`（码集合）
#      与 `test_http_status_table_matches_the_locked_platform_mapping`（码 → 状态）。
#      另：框架校验路径若新增判定依据，`_RANGE_ERROR_TYPES` / `_MISSING_ERROR_TYPES`
#      与 `test_validation_error_type_mapping` 同步。
#
#   前提：该码必须先在 `_common/openapi.yaml` 的 `ErrorCode` 枚举里存在
#   （比对用例 `test_aicore_error_codes_all_exist_in_the_platform_enum` 强制此红线）。
#   把四处写在一起，是为了「加码」这件事在评审里有唯一可核对的落点。
# ===========================================================================
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

#: 框架 `HTTPException` 的 **HTTP 状态 → 业务码**：只能取控制者锁定的那几对。
#: 键是 HTTP 状态、值是业务码，方向与 `HTTP_STATUS_BY_ERROR_CODE` 相反但同样不许混用。
#: 用途：Starlette 路由未匹配（404）与方法不允许（405）抛的是基类 `HTTPException`，
#: 以及 `HTTPBearer` 等框架依赖内部抛的 401/403——这些都不经过业务代码，只能在此收编。
HTTP_STATUS_BY_HTTP_EXCEPTION_STATUS: Final[Mapping[int, int]] = {
    401: UNAUTHORIZED_CODE,
    403: FORBIDDEN_CODE,
    404: NOT_FOUND_CODE,
    429: RATE_LIMITED_CODE,
    500: INTERNAL_ERROR_CODE,
    502: CHANNEL_FAILURE_CODE,
    504: DEPENDENCY_TIMEOUT_CODE,
}

#: 未匹配到的 **< 500** 状态的兜底业务码：**只能取平台表里真实存在的码，不为 405 之类的状态
#: 发明新码**。
#: 取 `1001`（参数缺失）的理由：平台表的 `1xxx` 段是「参数校验」，而未匹配的路由
#: （404）与不被允许的方法（405）**就是**「请求的这一路参数不对」——请求打错了地方；
#: 普通业务 400 走 `AiCoreError` / `ParamError` 两档，不经过本兜底，
#: 故此处不会遮住任何业务规则，代价只是 message 用 1001 的平台文案（不暴露路由细节）。
#: 判据按 **500** 而不是 400 分段：`1xx`/`2xx`/`3xx` 这类 sub-400 状态**不是服务端故障**
#: （框架理论上也可能经 `HTTPException` 抛出），落到 5xx 兜底会送出 `5000` 这一「内部错误」
#: 假信号、惊动告警；它们与 4xx 同属「请求这一路不对」，故共用本兜底。
HTTP_EXCEPTION_SUB_5XX_FALLBACK_CODE: Final = PARAM_MISSING_CODE

#: 未匹配到的 5xx 的兜底业务码：对本服务而言 5xx 都是「内部错误」这一档。
HTTP_EXCEPTION_5XX_FALLBACK_CODE: Final = INTERNAL_ERROR_CODE

#: 框架路由 404 的专用文案：业务码与业务 `NotFoundError` 同为 `3006`（锁定对），
#: 但**不存在的是接口而不是对象**，文案必须能区分，否则排障时分不清「路径写错」与「查无此对象」。
#: 它是平台文案表之外唯一新增的文案，理由即是这一条区分需求。
ROUTE_NOT_FOUND_MESSAGE: Final = "接口不存在"

#: 框架 `HTTPException` 专用的文案覆盖：键是 **HTTP 状态**。
#: 只放 `404`（见 `ROUTE_NOT_FOUND_MESSAGE`）；其余状态一律取 `DEFAULT_MESSAGES[业务码]`
#: ——平台文案已按「面向用户、可直接展示」评审过，框架的 `detail` 不在其列。
HTTP_ERROR_MESSAGES: Final[Mapping[int, str]] = {404: ROUTE_NOT_FOUND_MESSAGE}

#: HTTP 状态分段边界（`_http_exception_info` 的兜底档判据）：它们是 HTTP 状态，不是业务码。
#: 只需下界 500：「服务端故障」与「其余全部（含 sub-400）」就是这两档的分界。
_SERVER_ERROR_MIN: Final = 500

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
        # Decimal 的位数约束（pydantic 的 `decimal_max_digits` / `decimal_places` 三型）：
        # 与上面的数值/长度范围同类，属「枚举或范围非法」（1003），故不落 1002 兜底。
        # 实测（pydantic 2.13.5）：`Field(max_digits=…)` 触发 `decimal_max_digits`、
        # `Field(decimal_places=…)` 触发 `decimal_max_places`；`decimal_whole_digits`
        # 用常规 Field 约束触发不到（pydantic-core 报的是 max_digits），但仍按范围类收列，
        # 以免它一旦出现就落到 1002 兜底。
        "decimal_max_digits",
        "decimal_max_places",
        "decimal_whole_digits",
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


class _HTTPExceptionInfo(NamedTuple):
    """框架 `HTTPException` 的映射结果：HTTP 状态原样保留，业务码与文案由本模块决定。"""

    status_code: int
    code: int
    message: str


def register_exception_handlers(app: FastAPI) -> None:
    """把四条错误路径收编到平台信封。由组合根 `main.create_app()` 调用。

    - `AiCoreError` → 业务码对应的 HTTP 状态 + 信封；
    - `RequestValidationError` → HTTP 422 + `1xxx` 信封（收编框架默认的 `{"detail": [...]}`，
      否则前端会同时收到两种响应形状）；
    - `StarletteHTTPException` → 原 HTTP 状态 + 映射业务码的信封（覆盖 FastAPI 预注册的
      `http_exception_handler`，它回的是 `{"detail": …}`）；状态不允许响应体时（`1xx` / `204` /
      `205` / `304`）回无体 `Response`，与该默认处理器一致（判据复用 `fastapi.utils`）。
      **必须用 Starlette 的基类注册**：
      FastAPI 预注册的键就是 `starlette.exceptions.HTTPException`，而路由层「未匹配路径」（404）
      与「方法不允许」（405）抛的正是这个基类实例，二者是同一个键；
      `HTTPBearer` 等依赖抛的 401/403 同理由此收编（详见模块 docstring）；
    - `Exception` → HTTP 500 + `code=5000` 信封（Starlette 会把它提升为 ServerErrorMiddleware
      的 error_handler，故「逃逸出应用的未预期异常」也走信封；组合根把 traceId 中间件包在
      ServerErrorMiddleware 之外，处理器执行时上下文尚未回滚，信封里的 traceId 与请求一致）。

    幂等：同一应用上重复调用只是覆盖同名处理器，`create_app()` 可被多次调用。
    """
    app.add_exception_handler(AiCoreError, _handle_ai_core_error)
    app.add_exception_handler(RequestValidationError, _handle_request_validation_error)
    app.add_exception_handler(StarletteHTTPException, _handle_http_exception)
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


async def _handle_http_exception(request: Request, exc: Exception) -> Response:
    """框架 `HTTPException` → 原 HTTP 状态 + 映射业务码的信封。

    收编对象（都在业务代码之外，调用点无法拦截）：

    - Starlette 路由层抛的 404（路径未匹配）与 405（方法不允许）——FastAPI 预注册的
      `http_exception_handler` 回的是 `{"detail": …}`（无 `code` 的第三种形状），本处理器覆盖它；
    - `HTTPBearer` 等框架依赖内部抛的 401 / 403；
    - 任何 `raise HTTPException(...)` 的历史代码（本服务的新代码 MUST NOT 这么写）。

    四条口径（**MUST NOT 自行发挥**）：

    1. `exc.status_code` 原样作为响应的 HTTP 状态；
    2. 业务码取 `_http_exception_info()` 的映射结果：锁定对优先，其余 < 500 → 1001、≥ 500 → 5000；
    3. 文案只取平台文案表（404 用 `ROUTE_NOT_FOUND_MESSAGE`），**MUST NOT 回显 `exc.detail`**
       —— 框架的 detail 是给开发者看的（`HTTPBearer` 抛的是 `"Not authenticated"`），
       平台文案才是面向用户评审过的那一份；
    4. **状态不允许响应体时回无体响应**（见下）。

    `exc.headers` 原样透传：FastAPI 的默认处理器就是这么做，也是 HTTP 协议的要求
    （`HTTPBearer` 的 401 会带 `WWW-Authenticate: Bearer`）。收编响应体 MUST NOT 顺手丢掉它，
    否则 `WWW-Authenticate` 之类对客户端有协议意义的头会静默消失。

    **无体状态**：`1xx` / `204` / `205` / `304` 不允许带响应体，故这里与 FastAPI 的默认
    `http_exception_handler` 保持**同构**——复用框架自己的判定
    （`fastapi.utils.is_body_allowed_for_status_code`，不重推 1xx/204/304 规则），命中即回
    `Response(status_code=…)`（同样透传 `exc.headers`）。否则收编会造出「204 带
    `application/json` 与一个信封体」这种违反 HTTP 契约的畸形响应，比不收编更糟。
    本分支当前**不可达**：路由层只会抛 404/405，业务代码抛 `AiCoreError`；显式实现它是为了
    镜像框架契约，而不是因为今天有调用方。
    """
    http_exc = cast(StarletteHTTPException, exc)
    info = _http_exception_info(http_exc.status_code)
    if not is_body_allowed_for_status_code(info.status_code):
        logger.info(
            "框架 HTTP 异常 code=%s http=%s method=%s path=%s traceId=%s"
            "（该状态不允许响应体，按框架契约回无体响应）",
            info.code,
            info.status_code,
            request.method,
            request.url.path,
            get_trace_id(),
        )
        return Response(status_code=info.status_code, headers=http_exc.headers)
    body = _error_body(info.code, info.message)
    logger.info(
        "框架 HTTP 异常 code=%s http=%s method=%s path=%s traceId=%s",
        info.code,
        info.status_code,
        request.method,
        request.url.path,
        body["traceId"],
    )
    return JSONResponse(status_code=info.status_code, content=body, headers=http_exc.headers)


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


def _http_exception_info(status_code: int) -> _HTTPExceptionInfo:
    """HTTP 状态 → `(状态, 业务码, 文案)`：锁定对优先，未列出的按段兜底。

    - `< 500` 兜底 `1001`、`>= 500` 兜底 `5000`（理由见两个兜底常量的注释）；
    - 文案优先取 `HTTP_ERROR_MESSAGES[状态]`（目前只有 404 的专用文案），否则取该业务码的
      平台文案——两条路都**不碰** `exc.detail`；
    - 兜底判据是「是否 >= 500」而不是「是否落在 4xx 段」：`1xx`/`2xx`/`3xx` 这类 sub-400 状态
      （框架理论上会抛，见模块 docstring）**不是服务端故障**，塞进 5xx 兜底会送出 `code=5000`
      这个「内部错误」假信号；它们与 4xx 同属「请求这一路不对」，故共用客户端侧兜底 `1001`。
      **sub-400 MUST NOT 落 `5000`**（用例
      `test_sub_400_status_never_maps_to_the_internal_error_code` 正面钉住）。
    """
    code = HTTP_STATUS_BY_HTTP_EXCEPTION_STATUS.get(status_code)
    if code is None:
        # 500 是 HTTP 段边界字面量，不是业务码；此处刻意不引业务码常量，避免误读。
        code = (
            HTTP_EXCEPTION_5XX_FALLBACK_CODE
            if status_code >= _SERVER_ERROR_MIN
            else HTTP_EXCEPTION_SUB_5XX_FALLBACK_CODE
        )
    message = HTTP_ERROR_MESSAGES.get(status_code, DEFAULT_MESSAGES[code])
    return _HTTPExceptionInfo(status_code=status_code, code=code, message=message)


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
