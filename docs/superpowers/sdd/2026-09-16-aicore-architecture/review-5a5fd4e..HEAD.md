# Review package 5a5fd4e..HEAD

## Commits

5d861b2 build(aicore): 显式声明测试直接导入的 pyyaml
1e86f0e feat(aicore): 实现异常层次与错误码映射

## Stat

 services/aicore/pyproject.toml            |   4 +
 services/aicore/src/aicore/core/errors.py | 395 +++++++++++++++++++-
 services/aicore/src/aicore/main.py        |   4 +
 services/aicore/tests/unit/test_errors.py | 587 ++++++++++++++++++++++++++++++
 4 files changed, 989 insertions(+), 1 deletion(-)

## Diff

```diff
diff --git a/services/aicore/pyproject.toml b/services/aicore/pyproject.toml
index ef752d2..16dcdec 100644
--- a/services/aicore/pyproject.toml
+++ b/services/aicore/pyproject.toml
@@ -32,20 +32,24 @@ dependencies = [
 dev = [
     "pytest>=9.1",
     "pytest-asyncio>=1.4",
     "pytest-cov>=7.1",
     "import-linter>=2.15",
     "ruff>=0.16",
     "mypy>=2.3",
     # tests/conftest.py 的 anyio_backend 夹具是 brief 强制项；
     # anyio 此前只是 pytest-asyncio 的传递依赖，显式声明后夹具才有直接的依赖归属（Task 1.4 继续扩展该文件）。
     "anyio>=4.15",
+    # tests/unit/test_errors.py 直接 import yaml 解析 services/_common/openapi.yaml 的码表
+    # （「错误码必须落在平台表内」的比对用例）。此前只作为 uvicorn[standard] 的传递依赖存在，
+    # 与 prod 依赖同一原则：直接 import 就必须显式声明。
+    "pyyaml>=6.0",
 ]

 [tool.setuptools.packages.find]
 where = ["src"]

 [tool.ruff]
 line-length = 100
 target-version = "py312"

 [tool.ruff.lint]
diff --git a/services/aicore/src/aicore/core/errors.py b/services/aicore/src/aicore/core/errors.py
index 3a1542c..5a329ca 100644
--- a/services/aicore/src/aicore/core/errors.py
+++ b/services/aicore/src/aicore/core/errors.py
@@ -1 +1,394 @@
-"""异常层次与错误码常量。Task 2.3 实现。"""
+"""异常层次与错误码映射（Task 2.3）。
+
+本模块是**业务码 → HTTP 响应**的唯一出口：业务代码只抛异常，不自行拼装信封
+（design.md：业务代码只抛业务异常，不自行拼装信封，否则错误码口径会散落）。
+三条路径全部归口在这里注册：
+
+1. 业务异常 `AiCoreError` → 下表对应的 HTTP 状态 + 平台信封；
+2. 框架的 `RequestValidationError`（FastAPI 默认 HTTP 422 + `{"detail": [...]}`）→ 收编成
+   同一个信封，业务码按 pydantic 的 error `type` 归入 `1xxx`；
+3. 未预期异常 → HTTP 500 + `code=5000`，**堆栈只进日志、不进响应体**。
+
+**业务码与 HTTP 状态严格分离**：下表的 HTTP 状态只是「送达方式」，`code` 字段永远只放
+业务码（口径来源：`services/_common/openapi.yaml` 的 `ErrorCode` 枚举与各 response 示例）。
+
+| 业务码 | HTTP | 含义 | 本服务的承载者 |
+| --- | --- | --- | --- |
+| `1001` | 400（框架校验为 422） | 参数缺失 | `ParamError(code=1001)` / 校验缺参 |
+| `1002` | 400（框架校验为 422） | 参数格式错误 | `ParamError()`（默认码）/ 校验类型或解析失败 |
+| `1003` | 400（框架校验为 422） | 枚举或范围非法 | `ParamError(code=1003)` / 校验枚举或范围失败 |
+| `2001` | 401 | 未登录 / Token 失效 | `UnauthorizedError` |
+| `2002` | 403 | 无权限 / 越权 | `ForbiddenError` |
+| `2004` | 429 | 请求过于频繁 | `RateLimitedError` |
+| `3006` | 404 | 对象不存在 | `NotFoundError` |
+| `4003` | 502 | 大模型 / 视觉 API 失败 | `ChannelFailureError` |
+| `5000` | 500 | 内部错误 | 未预期异常的兜底处理器 |
+| `5002` | 504 | 依赖超时 / 熔断 | `DependencyTimeoutError` |
+
+**`429` 是 HTTP 状态，业务码是 `2004`**：`code` 字段 MUST NOT 出现 `429`。前端按
+`code === 0` 判断成功，故限流响应必须同时带 429 与 `code=2004`（`_common` 的
+`RateLimited` 明写这一点）。同理 `code` 也不放 `400`/`404`/`500` 这类 HTTP 状态。
+
+框架校验路径保留 HTTP 422：`400` 与 `422` 都是「参数类失败」的送达方式，业务码同为
+`1xxx`；保留框架原生状态可让既有客户端与监控按原有语义继续识别，前端要认的是**响应体**。
+
+参数校验的 error `type` → 业务码（pydantic v2 的 type 字符串，`RequestValidationError.errors()`
+里的 `type` 字段）：
+
+| 业务码 | 判定依据 |
+| --- | --- |
+| `1001` | `missing` —— 必填项没送到 |
+| `1003` | 枚举或字面量（`enum` / `literal_error`）、数值范围（`greater_than*` / `less_than*` /
+`multiple_of` / `finite_number`）、长度范围（`too_short` / `too_long` / `string_too_short` /
+`string_too_long` / `bytes_too_short` / `bytes_too_long`） |
+| `1002` | 其余全部（类型不符、解析失败、pattern 不匹配、多余字段等）—— 兜底档 |
+
+同一请求里多个错误同时命中时**只回一个码**，优先级 `1001` > `1003` > `1002`：
+缺参是最该先补齐的问题，枚举/范围比格式更具体，`1002` 才是兜底。
+
+响应的 `message` 只取平台固定文案（`DEFAULT_MESSAGES`），**不回显 pydantic 的 `msg`/`loc`**：
+`msg` 是英文框架文案，且自定义校验器抛 `ValueError` 时会把用户输入带进 msg（PII 泄漏通道）；
+字段名与 type 只进日志（且只取 `type`/`loc`，不取 pydantic error dict 里的 `input`/`ctx`）。
+"""
+
+from __future__ import annotations
+
+import logging
+from collections.abc import Mapping, Sequence
+from datetime import UTC, datetime
+from typing import Any, Final, cast
+
+from fastapi import FastAPI, Request
+from fastapi.exceptions import RequestValidationError
+from fastapi.responses import JSONResponse
+
+from aicore.core.trace import get_trace_id
+
+logger = logging.getLogger(__name__)
+
+# ---------------------------------------------------------------------------
+# 业务码常量
+#
+# 取值只能来自 `_common/openapi.yaml` 的 ErrorCode 枚举；本服务只用到其中 10 个。
+# 常量名一律以 `_CODE` 结尾且带 `CODE` 字样：**它们是业务码，不是 HTTP 状态码**，
+# 两者读写时 MUST NOT 互相代入（例如 `RATE_LIMITED_CODE` 是 2004，不是 429）。
+# ---------------------------------------------------------------------------
+
+#: 参数缺失。
+PARAM_MISSING_CODE: Final = 1001
+#: 参数格式错误。
+PARAM_FORMAT_CODE: Final = 1002
+#: 枚举或范围非法。
+PARAM_VALUE_CODE: Final = 1003
+#: 未登录 / Token 失效。
+UNAUTHORIZED_CODE: Final = 2001
+#: 无权限 / 越权。
+FORBIDDEN_CODE: Final = 2002
+#: 请求过于频繁（网关级限流与服务域成本护栏共用）。
+RATE_LIMITED_CODE: Final = 2004
+#: 对象不存在。
+NOT_FOUND_CODE: Final = 3006
+#: 大模型 / 视觉 API 失败。
+CHANNEL_FAILURE_CODE: Final = 4003
+#: 内部错误（未预期异常的兜底码）。
+INTERNAL_ERROR_CODE: Final = 5000
+#: 依赖超时 / 熔断。
+DEPENDENCY_TIMEOUT_CODE: Final = 5002
+
+#: 参数类业务码三档（缺失 / 格式 / 枚举或范围）。
+PARAM_ERROR_CODES: Final[frozenset[int]] = frozenset(
+    {PARAM_MISSING_CODE, PARAM_FORMAT_CODE, PARAM_VALUE_CODE}
+)
+
+#: 本服务**可能发出**的全部业务码，供 test_errors.py 与 Task 2.4 比对使用。
+#: 成功码 `0` 不在内（它不是错误码）；HTTP 状态码（400/422/429/500…）也不在内。
+AICORE_ERROR_CODES: Final[frozenset[int]] = frozenset(
+    {
+        *PARAM_ERROR_CODES,
+        UNAUTHORIZED_CODE,
+        FORBIDDEN_CODE,
+        RATE_LIMITED_CODE,
+        NOT_FOUND_CODE,
+        CHANNEL_FAILURE_CODE,
+        INTERNAL_ERROR_CODE,
+        DEPENDENCY_TIMEOUT_CODE,
+    }
+)
+
+#: 业务码 → HTTP 状态。**只在本模块内部用于渲染响应**，业务码本身不含状态语义。
+#: 1xxx 三档对应 400（业务侧参数异常）；框架校验路径另用 VALIDATION_HTTP_STATUS=422。
+HTTP_STATUS_BY_ERROR_CODE: Final[Mapping[int, int]] = {
+    PARAM_MISSING_CODE: 400,
+    PARAM_FORMAT_CODE: 400,
+    PARAM_VALUE_CODE: 400,
+    UNAUTHORIZED_CODE: 401,
+    FORBIDDEN_CODE: 403,
+    RATE_LIMITED_CODE: 429,
+    NOT_FOUND_CODE: 404,
+    CHANNEL_FAILURE_CODE: 502,
+    INTERNAL_ERROR_CODE: 500,
+    DEPENDENCY_TIMEOUT_CODE: 504,
+}
+
+#: 框架参数校验失败的 HTTP 状态：保留 FastAPI 原生的 422，只把响应体换成平台信封。
+VALIDATION_HTTP_STATUS: Final = 422
+
+#: 每个业务码的默认提示文案：取自 `_common/openapi.yaml` 各 response 示例的 message，
+#: 面向用户、可直接展示 —— 故 MUST NOT 拼接内部细节（异常消息、文件路径、模块名、字段名）。
+#: test_errors.py 钉住「键集恰好等于 AICORE_ERROR_CODES」，新增码值时必须同时补文案。
+DEFAULT_MESSAGES: Final[Mapping[int, str]] = {
+    PARAM_MISSING_CODE: "参数缺失",
+    PARAM_FORMAT_CODE: "参数格式错误",
+    PARAM_VALUE_CODE: "枚举或范围非法",
+    UNAUTHORIZED_CODE: "未登录或 Token 已失效",
+    FORBIDDEN_CODE: "无权限访问该资源",
+    RATE_LIMITED_CODE: "请求过于频繁，请稍后重试",
+    NOT_FOUND_CODE: "对象不存在",
+    CHANNEL_FAILURE_CODE: "大模型或视觉 API 失败",
+    INTERNAL_ERROR_CODE: "服务内部错误",
+    DEPENDENCY_TIMEOUT_CODE: "依赖超时或熔断",
+}
+
+#: 校验错误 type → `1xxx`。见模块 docstring 的映射表；未列出的 type 一律落 1002（兜底）。
+_MISSING_ERROR_TYPES: Final[frozenset[str]] = frozenset({"missing"})
+
+_RANGE_ERROR_TYPES: Final[frozenset[str]] = frozenset(
+    {
+        "enum",
+        "literal_error",
+        "greater_than",
+        "greater_than_equal",
+        "less_than",
+        "less_than_equal",
+        "multiple_of",
+        "finite_number",
+        "too_short",
+        "too_long",
+        "string_too_short",
+        "string_too_long",
+        "bytes_too_short",
+        "bytes_too_long",
+    }
+)
+
+
+class AiCoreError(Exception):
+    """业务异常基类：所有**可预期**的业务失败都从这里派生。
+
+    两个字段的语义（MUST NOT 混用）：
+
+    - `code`：**业务码**，取值只能是 `AICORE_ERROR_CODES` 内的值，构造期强校验；
+    - `message`：面向用户的提示文案，缺省时取平台文案 `DEFAULT_MESSAGES[code]`。
+
+    `code` 是类属性、`message` 是实例属性：子类只声明「我是哪一类失败」，调用方按需覆盖文案。
+    非法码在**构造期**抛 `ValueError`（fail fast）：写错码值应当立刻炸在开发/测试期，
+    而不是把一个平台表里不存在的码送到前端。
+    """
+
+    #: 缺省码：未声明码值的派生类按「内部错误」处理（不猜业务语义）。
+    code: int = INTERNAL_ERROR_CODE
+
+    def __init__(self, message: str | None = None) -> None:
+        if self.code not in AICORE_ERROR_CODES:
+            raise ValueError(
+                f"业务码 {self.code} 不在本服务的错误码集合 {sorted(AICORE_ERROR_CODES)} 内："
+                f"码值只能取 _common/openapi.yaml 的 ErrorCode 枚举"
+            )
+        self.message: str = DEFAULT_MESSAGES[self.code] if message is None else message
+        super().__init__(self.message)
+
+
+class ParamError(AiCoreError):
+    """参数类错误：`1001` 缺失 / `1002` 格式 / `1003` 枚举或范围。
+
+    **形状选择（本模块的口径）**：三档共用一个类，具体档位由构造参数 `code` 指定，
+    缺省 `1002`（参数格式错误）。理由：
+
+    - 平台把 1xxx 三档放在同一段，彼此的差别只有「缺失 / 格式 / 枚举或范围」这一个维度，
+      拆成三个类会让调用方在「这算格式还是算范围」上多做一次类选择；
+    - 缺省 1002 与框架校验路径的兜底码一致（`_validation_error_code`）：两条路径对
+      「归不了类的参数错误」给出同一个码，前端只需要记一个兜底值；
+    - `code` 只接受 `PARAM_ERROR_CODES` 内的值，传 `2001` 之类跨段的码直接抛 `ValueError`。
+    """
+
+    code: int = PARAM_FORMAT_CODE
+
+    def __init__(self, message: str | None = None, *, code: int | None = None) -> None:
+        if code is not None:
+            if code not in PARAM_ERROR_CODES:
+                raise ValueError(
+                    f"ParamError 的 code 只能是 {sorted(PARAM_ERROR_CODES)}，收到 {code}"
+                )
+            self.code = code
+        super().__init__(message)
+
+
+class UnauthorizedError(AiCoreError):
+    """未登录 / Token 失效（`2001`，HTTP 401）。
+
+    本服务语境下指**内部凭据无效**（网关凭据、内部 Token 校验不通过），
+    面向调用方不区分「没带」与「带了但无效」——两种情况的处置动作相同。
+    """
+
+    code: int = UNAUTHORIZED_CODE
+
+
+class ForbiddenError(AiCoreError):
+    """无权限 / 越权（`2002`，HTTP 403）。"""
+
+    code: int = FORBIDDEN_CODE
+
+
+class RateLimitedError(AiCoreError):
+    """请求过于频繁（`2004`，HTTP 429）。
+
+    网关级限流与服务域成本护栏（日配额 / 日预算）共用本码：两者对调用方都是
+    「稍后重试」，差别只在服务端计数口径。
+    """
+
+    code: int = RATE_LIMITED_CODE
+
+
+class NotFoundError(AiCoreError):
+    """对象不存在（`3006`，HTTP 404）。"""
+
+    code: int = NOT_FOUND_CODE
+
+
+class ChannelFailureError(AiCoreError):
+    """大模型 / 视觉 API 失败（`4003`，HTTP 502）：**等到响应但响应是失败**。
+
+    与 `DependencyTimeoutError` 严格区分：两者计数与告警口径不同。
+    """
+
+    code: int = CHANNEL_FAILURE_CODE
+
+
+class DependencyTimeoutError(AiCoreError):
+    """依赖超时 / 熔断（`5002`，HTTP 504）：**没等到响应**。"""
+
+    code: int = DEPENDENCY_TIMEOUT_CODE
+
+
+def register_exception_handlers(app: FastAPI) -> None:
+    """把三条错误路径收编到平台信封。由组合根 `main.create_app()` 调用。
+
+    - `AiCoreError` → 业务码对应的 HTTP 状态 + 信封；
+    - `RequestValidationError` → HTTP 422 + `1xxx` 信封（收编框架默认的 `{"detail": [...]}`，
+      否则前端会同时收到两种响应形状）；
+    - `Exception` → HTTP 500 + `code=5000` 信封（Starlette 会把它提升为 ServerErrorMiddleware
+      的 error_handler，故「逃逸出应用的未预期异常」也走信封；组合根把 traceId 中间件包在
+      ServerErrorMiddleware 之外，处理器执行时上下文尚未回滚，信封里的 traceId 与请求一致）。
+
+    幂等：同一应用上重复调用只是覆盖同名处理器，`create_app()` 可被多次调用。
+    """
+    app.add_exception_handler(AiCoreError, _handle_ai_core_error)
+    app.add_exception_handler(RequestValidationError, _handle_request_validation_error)
+    app.add_exception_handler(Exception, _handle_unexpected_error)
+
+
+async def _handle_ai_core_error(request: Request, exc: Exception) -> JSONResponse:
+    """业务异常 → 信封。
+
+    `exc` 的注解是 `Exception` 而非 `AiCoreError`：Starlette 的 `ExceptionHandler` 把第二
+    个参数声明为基类，写窄类型过不了 mypy strict；类型由注册契约保证，故此处 `cast`。
+    """
+    error = cast(AiCoreError, exc)
+    status_code = HTTP_STATUS_BY_ERROR_CODE[error.code]
+    body = _error_body(error.code, error.message)
+    logger.info(
+        "业务异常 code=%s http=%s method=%s path=%s traceId=%s",
+        error.code,
+        status_code,
+        request.method,
+        request.url.path,
+        body["traceId"],
+    )
+    return JSONResponse(status_code=status_code, content=body)
+
+
+async def _handle_request_validation_error(request: Request, exc: Exception) -> JSONResponse:
+    """FastAPI 默认 422 → 平台信封（HTTP 状态保留 422，响应体换成信封）。"""
+    errors = cast(RequestValidationError, exc).errors()
+    code = _validation_error_code(errors)
+    logger.info(
+        "请求参数校验未通过 code=%s path=%s errors=%s",
+        code,
+        request.url.path,
+        _loggable_errors(errors),
+    )
+    return JSONResponse(
+        status_code=VALIDATION_HTTP_STATUS,
+        content=_error_body(code, DEFAULT_MESSAGES[code]),
+    )
+
+
+async def _handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
+    """未预期异常 → HTTP 500 + `code=5000`，堆栈只进日志。
+
+    响应体**只**放平台固定文案：`str(exc)`、traceback、文件路径、模块名一律不进响应
+    （test_errors.py 正面钉住「响应体里没有这些串」）。
+
+    显式传 `exc_info=exc` 而不用 `logger.exception()`：本处理器是 Starlette 在 `except`
+    块里 await 的，`logger.exception()` 依赖 `sys.exc_info()`，把异常对象本身交给日志
+    才与「一定记下这条异常的堆栈」等价。
+    """
+    logger.error(
+        "未预期异常 code=%s method=%s path=%s traceId=%s",
+        INTERNAL_ERROR_CODE,
+        request.method,
+        request.url.path,
+        get_trace_id(),
+        exc_info=exc,
+    )
+    return JSONResponse(
+        status_code=HTTP_STATUS_BY_ERROR_CODE[INTERNAL_ERROR_CODE],
+        content=_error_body(INTERNAL_ERROR_CODE, DEFAULT_MESSAGES[INTERNAL_ERROR_CODE]),
+    )
+
+
+def _validation_error_code(errors: Sequence[Mapping[str, Any]]) -> int:
+    """按「缺失 > 枚举或范围 > 格式」的优先级，把校验错误归到 `1xxx`。
+
+    只回一个码：信封只承载一个业务码，多个字段同时失败时按优先级取最该先修的那个。
+    无法归类的 type 落 `1002`（兜底），故新增 pydantic 错误类型不会漏成 5000。
+    """
+    types = {str(item.get("type", "")) for item in errors}
+    if types & _MISSING_ERROR_TYPES:
+        return PARAM_MISSING_CODE
+    if types & _RANGE_ERROR_TYPES:
+        return PARAM_VALUE_CODE
+    return PARAM_FORMAT_CODE
+
+
+def _loggable_errors(errors: Sequence[Mapping[str, Any]]) -> list[tuple[str, tuple[Any, ...]]]:
+    """只取 `type` 与 `loc` 供日志：pydantic 的 error dict 还含 `input`（用户原值）与
+    `ctx`（可能是带值的异常消息），整体序列化会把用户输入写进日志（PII 泄漏通道）。
+    """
+    return [(str(item.get("type", "")), tuple(item.get("loc", ()))) for item in errors]
+
+
+def _error_body(code: int, message: str) -> dict[str, Any]:
+    """失败信封：`code` / `message` / `traceId` / `timestamp` 四必填字段 + `data: null`。
+
+    **这里的形状是刻意的**：它就是 `_common/openapi.yaml` 的 `Envelope` 形状，与 Task 2.4
+    的 `core/envelope.py` 模型同形，不是重复定义 —— Task 2.3 先于 Task 2.4 落地，异常处理器
+    不能等模型就位才能返回错误响应，故此处用等价 dict 承载；`Envelope` 模型（及
+    `Envelope.ok/fail`）由 **Task 2.4 拥有**，届时以「本处理器的输出能通过该模型校验」
+    反向对齐，MUST NOT 在 core/envelope.py 之外再造一个模型类。
+
+    `timestamp` 为 UTC ISO 8601（`Z` 结尾，与 `_common` 示例 `2026-01-15T10:30:00Z` 同形）；
+    `traceId` 一律取自 `core/trace.py` 的 `get_trace_id()`，不另造来源。
+    """
+    return {
+        "code": code,
+        "message": message,
+        "data": None,
+        "traceId": get_trace_id(),
+        "timestamp": _utc_timestamp(),
+    }
+
+
+def _utc_timestamp() -> str:
+    """当前时刻的 UTC ISO 8601 字符串，例：`2026-01-15T10:30:00.123456Z`。"""
+    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
diff --git a/services/aicore/src/aicore/main.py b/services/aicore/src/aicore/main.py
index 33e5760..2d10236 100644
--- a/services/aicore/src/aicore/main.py
+++ b/services/aicore/src/aicore/main.py
@@ -10,20 +10,21 @@
 from __future__ import annotations

 from collections.abc import AsyncIterator
 from contextlib import asynccontextmanager

 from fastapi import FastAPI
 from starlette.types import ASGIApp

 from aicore import __version__
 from aicore.api import health
+from aicore.core.errors import register_exception_handlers
 from aicore.core.trace import TraceIdMiddleware


 @asynccontextmanager
 async def lifespan(app: FastAPI) -> AsyncIterator[None]:
     """启动与关闭钩子。

     启动即校验配置（Task 2.2）、装配依赖（Task 3.4 起）、
     启动任务执行器（第 4 组）都将挂在这里。
     """
@@ -58,14 +59,17 @@ def create_app() -> FastAPI:
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
+    # 全局异常处理器（Task 2.3）：业务异常 / 框架 422 / 未预期异常统一映射为平台信封。
+    # 注册只改 app.exception_handlers，不读配置，create_app() 仍是纯装配函数。
+    register_exception_handlers(app)
     return app


 app = create_app()
diff --git a/services/aicore/tests/unit/test_errors.py b/services/aicore/tests/unit/test_errors.py
new file mode 100644
index 0000000..bc69720
--- /dev/null
+++ b/services/aicore/tests/unit/test_errors.py
@@ -0,0 +1,587 @@
+"""异常层次与错误码映射用例（Task 2.3）。
+
+覆盖点（全部跑真实 HTTP 链路，只有校验分类器是直接调函数）：
+
+1. 每个异常类 → 业务码 + HTTP 状态（含 `ParamError` 三档与缺省档）；
+2. 信封形状：四必填字段 `code` / `message` / `traceId` / `timestamp` 加可选的 `data`，
+   失败时 `data=null`；`timestamp` 为 UTC ISO 8601；`traceId` 取自请求头 `X-Request-Id`
+   （缺失时生成 16 位小写 hex）；
+3. FastAPI 默认 422 + `{"detail": [...]}` 被收编成信封（1xxx），响应体里不留框架结构；
+4. 未预期异常 → HTTP 500 + `code=5000`，响应体不含堆栈 / 文件路径 / 模块名 / 原始异常消息，
+   而**堆栈确实进了日志**（caplog 里取到带 traceback 的 ERROR 记录）；
+5. `AICORE_ERROR_CODES` 与平台单一事实源 `services/_common/openapi.yaml` 的 `ErrorCode`
+   枚举逐项比对，且**阴性方向**有判别力：凭空加一个枚举外的码（含把 HTTP 429 当业务码）
+   必须被判定器抓出来；
+6. 业务码与 HTTP 状态不混用：集合不含 HTTP 状态，限流是 `(HTTP 429, code 2004)`；
+7. `/health` 仍是裸响应（Task 1.4 验收项，注册处理器后 MUST NOT 回归）。
+
+探针路由由夹具挂到用例自己的 `create_app()` 实例上，生产代码不含任何调试端点。
+"""
+
+from __future__ import annotations
+
+import itertools
+import logging
+import re
+import traceback
+from collections.abc import Callable, Collection, Iterable, Iterator
+from datetime import UTC, datetime, timedelta
+from pathlib import Path
+from typing import Annotated, Literal
+
+import pytest
+import yaml
+from fastapi import FastAPI, Query
+from fastapi.exceptions import RequestValidationError
+from fastapi.testclient import TestClient
+
+from aicore.core.errors import (
+    AICORE_ERROR_CODES,
+    DEFAULT_MESSAGES,
+    HTTP_STATUS_BY_ERROR_CODE,
+    PARAM_ERROR_CODES,
+    AiCoreError,
+    ChannelFailureError,
+    DependencyTimeoutError,
+    ForbiddenError,
+    NotFoundError,
+    ParamError,
+    RateLimitedError,
+    UnauthorizedError,
+    _validation_error_code,
+)
+from aicore.core.trace import TRACE_ID_HEADER
+from aicore.main import create_app
+
+SERVICE_ROOT = Path(__file__).resolve().parents[2]
+#: 平台错误码单一事实源：`services/_common/openapi.yaml`（各服务文档 $ref 引用它，勿内联）。
+PLATFORM_OPENAPI = SERVICE_ROOT.parent / "_common" / "openapi.yaml"
+
+#: 信封的四个必填字段 + 可选的 `data`（失败时为 null）。
+REQUIRED_ENVELOPE_KEYS = frozenset({"code", "message", "traceId", "timestamp"})
+ENVELOPE_KEYS = REQUIRED_ENVELOPE_KEYS | {"data"}
+
+#: `_common` 的示例值，同时也是合法的 16 位 hex 注入值。
+INJECTED_TRACE_ID = "3f2a1b9c8d7e6f50"
+TRACE_ID_PATTERN = re.compile(r"^[0-9a-f]{16}$")
+ISO8601_UTC_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")
+
+#: 未预期异常的原始消息：故意长得像内部细节（模块路径 + 类名），
+#: 一旦被写进响应体，泄漏断言立刻变红。
+UNEXPECTED_ERROR_MESSAGE = "测试：模块路径 src/aicore/core/errors.py 的 RuntimeError"
+
+
+# ---------------------------------------------------------------------------
+# 平台表读取与判定器
+# ---------------------------------------------------------------------------
+
+
+def read_platform_error_codes() -> frozenset[int]:
+    """读 `_common/openapi.yaml` 的 `ErrorCode` 枚举（平台错误码单一事实源）。"""
+    document = yaml.safe_load(PLATFORM_OPENAPI.read_text(encoding="utf-8"))
+    enum_values = document["components"]["schemas"]["ErrorCode"]["enum"]
+    return frozenset(int(value) for value in enum_values)
+
+
+def codes_outside_platform_table(
+    codes: Iterable[int], platform_codes: Collection[int]
+) -> tuple[int, ...]:
+    """返回 `codes` 里不在平台枚举内的码值（升序）。
+
+    本函数就是「业务码只能取平台表内的值」这条红线的判定器，参数化出 `platform_codes`
+    便于直接喂一个「凭空加进来的码」来自证判别力（阴性方向）。
+    """
+    return tuple(sorted({code for code in codes if code not in platform_codes}))
+
+
+# ---------------------------------------------------------------------------
+# 夹具与探针路由（只在用例里存在）
+# ---------------------------------------------------------------------------
+
+
+@pytest.fixture
+def raising_route(app: FastAPI) -> Callable[[BaseException], str]:
+    """登记一条「抛出指定异常」的测试专用路由，返回它的路径。
+
+    路由挂到用例自己的 app 实例上：生产代码不含任何探针 / 调试端点。
+    """
+    counter = itertools.count()
+
+    def _register(exc: BaseException) -> str:
+        path = f"/__test__/raise-{next(counter)}"
+
+        async def _raise() -> None:
+            raise exc
+
+        app.add_api_route(path, _raise, methods=["GET"], include_in_schema=False)
+        return path
+
+    return _register
+
+
+@pytest.fixture
+def error_client(app: FastAPI) -> Iterator[TestClient]:
+    """不把服务端异常抛回用例的客户端：未预期异常要断言的是**响应体**，不是异常本身。"""
+    with TestClient(app, raise_server_exceptions=False) as c:
+        yield c
+
+
+@pytest.fixture
+def validation_client(app: FastAPI, client: TestClient) -> TestClient:
+    """带参数校验探针路由的客户端：用真实的 FastAPI 校验链路触发 422。
+
+    四类失败来源各留一个入口：缺参（missing）、整数解析失败（int_parsing）、
+    字面量不在允许集合（literal_error）、超出上界（less_than_equal）。
+    """
+
+    @app.get("/__test__/validate", include_in_schema=False)
+    async def _validate(
+        name: str,
+        limit: Annotated[int, Query(ge=1, le=10)],
+        mode: Literal["fast", "slow"],
+    ) -> dict[str, str]:
+        return {"name": name, "limit": str(limit), "mode": mode}
+
+    return client
+
+
+# ---------------------------------------------------------------------------
+# 1. 异常类 → 业务码
+# ---------------------------------------------------------------------------
+
+
+def test_base_error_defaults_to_internal_error_code() -> None:
+    """基类缺省码是 5000（内部错误）：派生类没声明码值时按「不猜业务语义」处理。"""
+    assert AiCoreError().code == 5000
+    assert issubclass(AiCoreError, Exception)
+
+
+@pytest.mark.parametrize(
+    ("error_class", "expected_code"),
+    [
+        pytest.param(UnauthorizedError, 2001, id="UnauthorizedError"),
+        pytest.param(ForbiddenError, 2002, id="ForbiddenError"),
+        pytest.param(RateLimitedError, 2004, id="RateLimitedError"),
+        pytest.param(NotFoundError, 3006, id="NotFoundError"),
+        pytest.param(ChannelFailureError, 4003, id="ChannelFailureError"),
+        pytest.param(DependencyTimeoutError, 5002, id="DependencyTimeoutError"),
+    ],
+)
+def test_exception_class_carries_expected_business_code(
+    error_class: type[AiCoreError], expected_code: int
+) -> None:
+    """每个异常类自带业务码；断言用字面量，避免与实现里的常量互相印证。"""
+    assert error_class.code == expected_code
+    assert error_class().code == expected_code
+
+
+def test_exception_message_defaults_and_override() -> None:
+    """缺省文案随码值走（取自平台文案表）；调用方可覆盖文案，但改不了码。"""
+    assert ForbiddenError().message == DEFAULT_MESSAGES[2002]
+    exc = ForbiddenError("测试：该资源属于其他账号")
+    assert (exc.code, exc.message, str(exc)) == (
+        2002,
+        "测试：该资源属于其他账号",
+        "测试：该资源属于其他账号",
+    )
+
+
+def test_param_error_carries_the_three_param_codes() -> None:
+    """`ParamError` 的形状：三档共用一个类，档位由 `code` 指定，缺省 1002（格式）。"""
+    assert ParamError().code == 1002
+    assert ParamError(code=1001).code == 1001
+    assert ParamError(code=1002).code == 1002
+    assert ParamError(code=1003).code == 1003
+    # 文案随最终码值走：缺参档的缺省文案是「参数缺失」，不是构造时的 1002 文案。
+    assert ParamError(code=1001).message == DEFAULT_MESSAGES[1001]
+    assert ParamError("测试：自定义文案", code=1003).message == "测试：自定义文案"
+
+
+@pytest.mark.parametrize("code", [0, 2001, 3006, 429, 9999])
+def test_param_error_rejects_codes_outside_the_param_family(code: int) -> None:
+    """跨段的码（含成功码 0、HTTP 429）在构造期即被拒绝，MUST NOT 落到响应体。"""
+    with pytest.raises(ValueError):
+        ParamError("测试：非法档位", code=code)
+
+
+def test_base_error_rejects_code_outside_the_platform_table() -> None:
+    """派生类写错码值必须立刻炸在构造期，而不是把枚举外的码送到前端。"""
+
+    class _OutOfTableError(AiCoreError):
+        code = 9999
+
+    with pytest.raises(ValueError, match="9999"):
+        _OutOfTableError()
+
+
+# ---------------------------------------------------------------------------
+# 2. 业务异常 → 信封 + HTTP 状态（真实 HTTP 链路）
+# ---------------------------------------------------------------------------
+
+
+@pytest.mark.parametrize(
+    ("exc", "expected_code", "expected_status"),
+    [
+        pytest.param(ParamError("测试：缺参", code=1001), 1001, 400, id="param-missing-1001"),
+        pytest.param(ParamError("测试：格式", code=1002), 1002, 400, id="param-format-1002"),
+        pytest.param(ParamError("测试：范围", code=1003), 1003, 400, id="param-value-1003"),
+        pytest.param(ParamError("测试：缺省档"), 1002, 400, id="param-default-1002"),
+        pytest.param(UnauthorizedError(), 2001, 401, id="unauthorized-2001"),
+        pytest.param(ForbiddenError(), 2002, 403, id="forbidden-2002"),
+        pytest.param(RateLimitedError(), 2004, 429, id="rate-limited-2004"),
+        pytest.param(NotFoundError(), 3006, 404, id="not-found-3006"),
+        pytest.param(ChannelFailureError(), 4003, 502, id="channel-failure-4003"),
+        pytest.param(DependencyTimeoutError(), 5002, 504, id="dependency-timeout-5002"),
+    ],
+)
+def test_business_exception_maps_to_envelope(
+    client: TestClient,
+    raising_route: Callable[[BaseException], str],
+    exc: AiCoreError,
+    expected_code: int,
+    expected_status: int,
+) -> None:
+    """业务异常 → 业务码 + HTTP 状态 + 信封。
+
+    用 conftest 的 `client`（raise_server_exceptions 默认 True）：异常若逃逸出应用，
+    用例会直接炸而不是拿到响应 —— 这正面证明业务异常被处理器完全吸收。
+    """
+    response = client.get(raising_route(exc))
+    body = response.json()
+
+    assert response.status_code == expected_status
+    assert body["code"] == expected_code
+    assert body["message"] == exc.message
+    assert set(body) == ENVELOPE_KEYS
+    assert body["data"] is None
+    # 业务码与 HTTP 状态是两个维度：这里逐例证明两者没有被混用。
+    assert body["code"] != response.status_code
+    assert response.headers["content-type"].startswith("application/json")
+
+
+def test_rate_limited_is_business_code_2004_under_http_429(
+    client: TestClient, raising_route: Callable[[BaseException], str]
+) -> None:
+    """`429` 是 HTTP 状态、业务码是 `2004` —— 前端按 `code` 判断，两者必须同时出现。"""
+    response = client.get(raising_route(RateLimitedError()))
+    assert response.status_code == 429
+    assert response.json()["code"] == 2004
+    assert 429 not in AICORE_ERROR_CODES
+
+
+def test_trace_id_comes_from_request_header(
+    client: TestClient, raising_route: Callable[[BaseException], str]
+) -> None:
+    """信封 traceId 取自请求头 `X-Request-Id`（不另造来源），并由中间件原值回显。"""
+    response = client.get(
+        raising_route(NotFoundError()), headers={TRACE_ID_HEADER: INJECTED_TRACE_ID}
+    )
+    assert response.json()["traceId"] == INJECTED_TRACE_ID
+    assert response.headers[TRACE_ID_HEADER] == INJECTED_TRACE_ID
+
+
+def test_trace_id_is_generated_when_header_is_absent(
+    client: TestClient, raising_route: Callable[[BaseException], str]
+) -> None:
+    """头缺失时信封仍要有可用 traceId（16 位小写 hex），不能是空串。"""
+    body = client.get(raising_route(NotFoundError())).json()
+    assert TRACE_ID_PATTERN.fullmatch(body["traceId"])
+
+
+def test_timestamp_is_iso8601_utc_within_the_request_window(
+    client: TestClient, raising_route: Callable[[BaseException], str]
+) -> None:
+    """`timestamp` 是 UTC ISO 8601（`Z` 结尾），且落在本次请求的时间窗内。"""
+    before = datetime.now(UTC)
+    timestamp = client.get(raising_route(NotFoundError())).json()["timestamp"]
+    after = datetime.now(UTC)
+
+    assert ISO8601_UTC_PATTERN.fullmatch(timestamp), timestamp
+    parsed = datetime.fromisoformat(timestamp)
+    assert parsed.utcoffset() == timedelta(0)
+    assert before <= parsed <= after
+
+
+def test_health_stays_bare_after_handlers_are_registered(client: TestClient) -> None:
+    """`/health` MUST NOT 被信封包裹（Task 1.4 验收项；注册处理器不得让它回归）。"""
+    response = client.get("/health")
+    assert response.status_code == 200
+    assert response.json() == {"status": "ok"}
+    assert set(response.json()).isdisjoint(ENVELOPE_KEYS)
+
+
+def test_create_app_registers_the_three_handlers() -> None:
+    """组合根必须真的接线三条路径：业务异常 / 框架校验 / 未预期异常。"""
+    handlers = create_app().exception_handlers
+    assert {AiCoreError, RequestValidationError, Exception} <= set(handlers)
+
+
+# ---------------------------------------------------------------------------
+# 3. FastAPI 默认 422 被收编
+# ---------------------------------------------------------------------------
+
+
+def test_validation_probe_route_accepts_valid_params(validation_client: TestClient) -> None:
+    """探针路由本身可用：下面的 1xxx 确实来自参数校验，而不是路由写错。"""
+    response = validation_client.get("/__test__/validate?name=x&limit=5&mode=fast")
+    assert response.status_code == 200
+    assert response.json() == {"name": "x", "limit": "5", "mode": "fast"}
+
+
+@pytest.mark.parametrize(
+    ("query", "expected_code", "reason"),
+    [
+        pytest.param("", 1001, "三个必填项全缺", id="all-missing"),
+        pytest.param("?limit=5&mode=fast", 1001, "缺 name", id="one-missing"),
+        pytest.param("?name=x&limit=abc&mode=fast", 1002, "整数解析失败", id="int-parsing"),
+        pytest.param("?name=x&limit=5&mode=nope", 1003, "字面量不在允许集合", id="literal"),
+        pytest.param("?name=x&limit=99&mode=fast", 1003, "超出上界 le=10", id="range"),
+        pytest.param(
+            "?name=x&limit=abc&mode=nope",
+            1003,
+            "枚举优先于格式（同级多错只回一个码）",
+            id="enum-beats-format",
+        ),
+        pytest.param(
+            "?limit=99&mode=nope",
+            1001,
+            "缺失优先于枚举或范围",
+            id="missing-beats-enum",
+        ),
+    ],
+)
+def test_request_validation_error_is_absorbed_into_envelope(
+    validation_client: TestClient, query: str, expected_code: int, reason: str
+) -> None:
+    """框架 422 → 平台信封：HTTP 状态保留 422，响应体换成 1xxx 信封（无 `detail`）。"""
+    response = validation_client.get(f"/__test__/validate{query}")
+    body = response.json()
+
+    assert response.status_code == 422, reason
+    assert set(body) >= REQUIRED_ENVELOPE_KEYS, reason
+    assert set(body) == ENVELOPE_KEYS, reason
+    assert body["code"] == expected_code, reason
+    assert body["code"] != response.status_code, "业务码 MUST NOT 等于 HTTP 状态"
+    assert body["data"] is None
+    assert body["message"] == DEFAULT_MESSAGES[expected_code]
+    # 不回显框架结构，也不回显字段名 / pydantic 文案。
+    assert "detail" not in body
+    for leaked in ("detail", "Field required", "Input should be", "limit", "mode", "name"):
+        assert leaked not in response.text, f"响应体回显了框架内部信息：{leaked}"
+
+
+def test_validation_log_keeps_types_but_not_user_input(
+    validation_client: TestClient, caplog: pytest.LogCaptureFixture
+) -> None:
+    """日志只记 type/loc：pydantic error dict 里的 `input`（用户原值）MUST NOT 进日志。"""
+    with caplog.at_level(logging.INFO, logger="aicore.core.errors"):
+        response = validation_client.get(
+            "/__test__/validate?name=test_secret_value&limit=abc&mode=fast"
+        )
+
+    assert response.status_code == 422
+    assert "test_secret_value" not in caplog.text
+    assert "test_secret_value" not in response.text
+    assert "int_parsing" in caplog.text  # 可排障信息保留
+
+
+@pytest.mark.parametrize(
+    ("error_type", "expected_code"),
+    [
+        pytest.param("missing", 1001, id="missing"),
+        pytest.param("enum", 1003, id="enum"),
+        pytest.param("literal_error", 1003, id="literal_error"),
+        pytest.param("greater_than", 1003, id="greater_than"),
+        pytest.param("greater_than_equal", 1003, id="greater_than_equal"),
+        pytest.param("less_than", 1003, id="less_than"),
+        pytest.param("less_than_equal", 1003, id="less_than_equal"),
+        pytest.param("multiple_of", 1003, id="multiple_of"),
+        pytest.param("finite_number", 1003, id="finite_number"),
+        pytest.param("too_short", 1003, id="too_short"),
+        pytest.param("too_long", 1003, id="too_long"),
+        pytest.param("string_too_short", 1003, id="string_too_short"),
+        pytest.param("string_too_long", 1003, id="string_too_long"),
+        pytest.param("bytes_too_short", 1003, id="bytes_too_short"),
+        pytest.param("bytes_too_long", 1003, id="bytes_too_long"),
+        pytest.param("int_parsing", 1002, id="int_parsing"),
+        pytest.param("string_type", 1002, id="string_type"),
+        pytest.param("string_pattern_mismatch", 1002, id="string_pattern_mismatch"),
+        pytest.param("extra_forbidden", 1002, id="extra_forbidden"),
+        pytest.param("json_invalid", 1002, id="json_invalid"),
+        pytest.param("aicore_future_error_type", 1002, id="unknown-type-falls-back"),
+    ],
+)
+def test_validation_error_type_mapping(error_type: str, expected_code: int) -> None:
+    """直接钉住分类表：pydantic 的 type 字符串很多，逐个用端点触发不现实。
+
+    `unknown-type-falls-back` 是兜底档的守门用例：pydantic 新增 type 时归 1002，
+    MUST NOT 漏成 5000。
+    """
+    assert _validation_error_code([{"type": error_type, "loc": ("query", "x")}]) == expected_code
+
+
+def test_validation_error_code_priority() -> None:
+    """多个错误同时命中时的优先级：缺失 > 枚举或范围 > 格式。"""
+    mixed = [{"type": "int_parsing"}, {"type": "literal_error"}, {"type": "missing"}]
+    assert _validation_error_code(mixed) == 1001
+    assert _validation_error_code([{"type": "int_parsing"}, {"type": "literal_error"}]) == 1003
+    assert _validation_error_code([{"type": "int_parsing"}]) == 1002
+    assert _validation_error_code([]) == 1002
+
+
+# ---------------------------------------------------------------------------
+# 4. 未预期异常 → 5000，堆栈只进日志
+# ---------------------------------------------------------------------------
+
+
+def test_unexpected_exception_maps_to_5000(
+    error_client: TestClient, raising_route: Callable[[BaseException], str]
+) -> None:
+    """未预期异常 → HTTP 500 + code=5000；信封照样四字段齐全、data=null。"""
+    path = raising_route(RuntimeError(UNEXPECTED_ERROR_MESSAGE))
+    response = error_client.get(path, headers={TRACE_ID_HEADER: INJECTED_TRACE_ID})
+    body = response.json()
+
+    assert response.status_code == 500
+    assert body["code"] == 5000
+    assert set(body) == ENVELOPE_KEYS
+    assert body["data"] is None
+    assert body["message"] == DEFAULT_MESSAGES[5000]
+    # 500 路径由 ServerErrorMiddleware 渲染，traceId 仍是网关注入值（中间件在最外层）。
+    assert body["traceId"] == INJECTED_TRACE_ID
+
+
+def test_unexpected_exception_body_leaks_no_internals(
+    error_client: TestClient, raising_route: Callable[[BaseException], str]
+) -> None:
+    """响应体 MUST NOT 含堆栈、文件路径、模块名，也不含原始异常消息。"""
+    path = raising_route(RuntimeError(UNEXPECTED_ERROR_MESSAGE))
+    response = error_client.get(path)
+
+    for leaked in (
+        "Traceback",
+        "File ",
+        ".py",
+        "RuntimeError",
+        "aicore",
+        "services",
+        "测试",  # 原始异常消息里的任意片段
+        path,  # 内部路由路径同样不外泄
+    ):
+        assert leaked not in response.text, f"响应体泄漏了内部细节：{leaked}"
+
+
+def test_unexpected_exception_traceback_is_logged(
+    error_client: TestClient,
+    raising_route: Callable[[BaseException], str],
+    caplog: pytest.LogCaptureFixture,
+) -> None:
+    """堆栈必须进日志（只进日志）：ERROR 记录带完整 traceback，且指向真实抛出点。"""
+    path = raising_route(RuntimeError(UNEXPECTED_ERROR_MESSAGE))
+    with caplog.at_level(logging.ERROR, logger="aicore.core.errors"):
+        error_client.get(path, headers={TRACE_ID_HEADER: INJECTED_TRACE_ID})
+
+    records = [
+        record
+        for record in caplog.records
+        if record.name == "aicore.core.errors" and record.levelno == logging.ERROR
+    ]
+    assert len(records) == 1, "未预期异常没有留下 ERROR 日志"
+    record = records[0]
+    assert record.exc_info is not None, "ERROR 记录未携带异常信息（堆栈丢了）"
+
+    formatted = "".join(traceback.format_exception(*record.exc_info))
+    assert "Traceback (most recent call last)" in formatted
+    assert UNEXPECTED_ERROR_MESSAGE in formatted
+    assert "test_errors.py" in formatted, "堆栈没有指向真实抛出点"
+    assert INJECTED_TRACE_ID in record.getMessage()
+
+
+# ---------------------------------------------------------------------------
+# 5. 错误码与平台表比对（含阴性方向）
+# ---------------------------------------------------------------------------
+
+
+def test_platform_enum_is_readable_and_not_vacuous() -> None:
+    """比对用例的前提：平台表读得到，且不是空集（否则任何比对都会静默通过）。"""
+    assert PLATFORM_OPENAPI.is_file(), PLATFORM_OPENAPI
+    platform_codes = read_platform_error_codes()
+    assert {0, 1001, 1002, 1003, 2004, 3007, 5000, 5002, 5003} <= platform_codes
+    assert len(platform_codes) >= 25, f"平台枚举只读到 {len(platform_codes)} 个码值，解析可能失效"
+
+
+def test_aicore_error_codes_all_exist_in_the_platform_enum() -> None:
+    """正向：本服务发出的每个码都在平台 `ErrorCode` 枚举内。"""
+    assert codes_outside_platform_table(AICORE_ERROR_CODES, read_platform_error_codes()) == ()
+
+
+def test_codes_outside_the_platform_table_are_detected() -> None:
+    """阴性方向：凭空加进来的码必须被判定器抓出来，比对用例才有判别力。
+
+    同时覆盖两类典型误写：自造的码值，以及把 HTTP 状态（429 / 400）当业务码写进来。
+    """
+    platform_codes = read_platform_error_codes()
+    assert codes_outside_platform_table({*AICORE_ERROR_CODES, 9999}, platform_codes) == (9999,)
+    assert codes_outside_platform_table({*AICORE_ERROR_CODES, 429}, platform_codes) == (429,)
+    assert codes_outside_platform_table({*AICORE_ERROR_CODES, 400}, platform_codes) == (400,)
+    assert codes_outside_platform_table({429, 400}, platform_codes) == (400, 429)
+
+
+def test_aicore_error_codes_is_exactly_the_emittable_set() -> None:
+    """集合与「本服务确实会发出的码」逐项一致：多了是死码，少了会漏成 5000。"""
+    emittable = {
+        1001,
+        1002,
+        1003,  # ParamError 三档
+        2001,
+        2002,
+        2004,
+        3006,
+        4003,
+        5000,  # 未预期异常的兜底码
+        5002,
+    }
+    assert sorted(AICORE_ERROR_CODES) == sorted(emittable)
+    assert isinstance(AICORE_ERROR_CODES, frozenset)
+    # 成功码与 HTTP 状态码 MUST NOT 混进业务码集合。
+    assert 0 not in AICORE_ERROR_CODES
+    assert AICORE_ERROR_CODES.isdisjoint({400, 401, 403, 404, 422, 429, 500, 502, 504})
+
+
+def test_every_exception_class_code_is_in_the_set() -> None:
+    """异常类携带的码不得游离于集合之外（集合是 Task 2.4 与比对用例的输入）。"""
+    for error_class in (
+        ParamError,
+        UnauthorizedError,
+        ForbiddenError,
+        RateLimitedError,
+        NotFoundError,
+        ChannelFailureError,
+        DependencyTimeoutError,
+    ):
+        assert error_class.code in AICORE_ERROR_CODES, error_class.__name__
+    assert AiCoreError.code == 5000
+    assert sorted(PARAM_ERROR_CODES) == [1001, 1002, 1003]
+
+
+def test_default_messages_cover_exactly_the_emittable_codes() -> None:
+    """每个码都必须有面向用户的缺省文案（缺文案会在渲染信封时炸成 500）。"""
+    assert set(DEFAULT_MESSAGES) == AICORE_ERROR_CODES
+    assert all(message.strip() for message in DEFAULT_MESSAGES.values())
+
+
+def test_http_status_table_matches_the_locked_platform_mapping() -> None:
+    """码值 → HTTP 状态由控制者锁定：用字面量钉住，避免表与断言互相印证。"""
+    assert dict(HTTP_STATUS_BY_ERROR_CODE) == {
+        1001: 400,
+        1002: 400,
+        1003: 400,
+        2001: 401,
+        2002: 403,
+        2004: 429,
+        3006: 404,
+        4003: 502,
+        5000: 500,
+        5002: 504,
+    }
+    assert set(HTTP_STATUS_BY_ERROR_CODE) == AICORE_ERROR_CODES

```
