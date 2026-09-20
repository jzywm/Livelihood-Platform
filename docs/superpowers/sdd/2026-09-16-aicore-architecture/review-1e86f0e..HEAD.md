# Review package 1e86f0e..HEAD

## Commits

805db9c fix(aicore): 收编框架 HTTPException 为统一信封
5d861b2 build(aicore): 显式声明测试直接导入的 pyyaml

## Stat

 services/aicore/pyproject.toml            |   4 +
 services/aicore/src/aicore/core/errors.py | 175 +++++++++++++++++++-
 services/aicore/tests/unit/test_errors.py | 258 +++++++++++++++++++++++++++++-
 3 files changed, 424 insertions(+), 13 deletions(-)

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
index 5a329ca..e6f31a8 100644
--- a/services/aicore/src/aicore/core/errors.py
+++ b/services/aicore/src/aicore/core/errors.py
@@ -1,20 +1,27 @@
 """异常层次与错误码映射（Task 2.3）。

 本模块是**业务码 → HTTP 响应**的唯一出口：业务代码只抛异常，不自行拼装信封
 （design.md：业务代码只抛业务异常，不自行拼装信封，否则错误码口径会散落）。
-三条路径全部归口在这里注册：
+四条路径全部归口在这里注册：

 1. 业务异常 `AiCoreError` → 下表对应的 HTTP 状态 + 平台信封；
 2. 框架的 `RequestValidationError`（FastAPI 默认 HTTP 422 + `{"detail": [...]}`）→ 收编成
    同一个信封，业务码按 pydantic 的 error `type` 归入 `1xxx`；
-3. 未预期异常 → HTTP 500 + `code=5000`，**堆栈只进日志、不进响应体**。
+3. 框架的 `HTTPException`（Starlette 基类，FastAPI 的 `HTTPException` 由它派生）→ 收编成
+   同一个信封，业务码按 HTTP 状态映射（见下「框架 HTTPException」一节）。
+   **必须显式注册**：FastAPI 构造时就为 `starlette.exceptions.HTTPException` 这个键预注册了
+   它的 `http_exception_handler`（回 `{"detail": …}` 的 JSON），本模块的注册是**覆盖**它
+   （不是并存）；Starlette 的路由层在**匹配不到路径**（404）与**方法不允许**（405）时抛的
+   正是这个基类实例，不注册就没有 `code` 字段——前端要多认一种形状。同理，`HTTPBearer`
+   之类的框架依赖在内部抛 `HTTPException(401/403)`，调用点无法拦截；
+4. 未预期异常 → HTTP 500 + `code=5000`，**堆栈只进日志、不进响应体**。

 **业务码与 HTTP 状态严格分离**：下表的 HTTP 状态只是「送达方式」，`code` 字段永远只放
 业务码（口径来源：`services/_common/openapi.yaml` 的 `ErrorCode` 枚举与各 response 示例）。

 | 业务码 | HTTP | 含义 | 本服务的承载者 |
 | --- | --- | --- | --- |
 | `1001` | 400（框架校验为 422） | 参数缺失 | `ParamError(code=1001)` / 校验缺参 |
 | `1002` | 400（框架校验为 422） | 参数格式错误 | `ParamError()`（默认码）/ 校验类型或解析失败 |
 | `1003` | 400（框架校验为 422） | 枚举或范围非法 | `ParamError(code=1003)` / 校验枚举或范围失败 |
 | `2001` | 401 | 未登录 / Token 失效 | `UnauthorizedError` |
@@ -33,52 +40,92 @@
 `1xxx`；保留框架原生状态可让既有客户端与监控按原有语义继续识别，前端要认的是**响应体**。

 参数校验的 error `type` → 业务码（pydantic v2 的 type 字符串，`RequestValidationError.errors()`
 里的 `type` 字段）：

 | 业务码 | 判定依据 |
 | --- | --- |
 | `1001` | `missing` —— 必填项没送到 |
 | `1003` | 枚举或字面量（`enum` / `literal_error`）、数值范围（`greater_than*` / `less_than*` /
 `multiple_of` / `finite_number`）、长度范围（`too_short` / `too_long` / `string_too_short` /
-`string_too_long` / `bytes_too_short` / `bytes_too_long`） |
+`string_too_long` / `bytes_too_short` / `bytes_too_long`）、Decimal 位数范围
+（`decimal_max_digits` / `decimal_max_places` / `decimal_whole_digits`） |
 | `1002` | 其余全部（类型不符、解析失败、pattern 不匹配、多余字段等）—— 兜底档 |

 同一请求里多个错误同时命中时**只回一个码**，优先级 `1001` > `1003` > `1002`：
 缺参是最该先补齐的问题，枚举/范围比格式更具体，`1002` 才是兜底。

 响应的 `message` 只取平台固定文案（`DEFAULT_MESSAGES`），**不回显 pydantic 的 `msg`/`loc`**：
 `msg` 是英文框架文案，且自定义校验器抛 `ValueError` 时会把用户输入带进 msg（PII 泄漏通道）；
 字段名与 type 只进日志（且只取 `type`/`loc`，不取 pydantic error dict 里的 `input`/`ctx`）。
+
+框架 `HTTPException` 的**状态 → 业务码**映射（`HTTP_STATUS_BY_HTTP_EXCEPTION_STATUS`，
+HTTP 状态原样保留，只换响应体）：
+
+| HTTP | 业务码 | 依据 |
+| --- | --- | --- |
+| 401 | `2001` | 锁定对（`_common` 的 Unauthorized 示例即 2001） |
+| 403 | `2002` | 锁定对（Forbidden） |
+| 404 | `3006` | 锁定对（NotFound），但文案用「接口不存在」以便与业务 `NotFoundError` 区分 |
+| 429 | `2004` | 锁定对（RateLimited） |
+| 502 | `4003` | 锁定对（大模型 / 视觉 API 失败） |
+| 504 | `5002` | 锁定对（依赖超时 / 熔断） |
+| 500 | `5000` | 锁定对（内部错误） |
+| 其余 4xx | `1001` | 兜底：见 `HTTP_EXCEPTION_4XX_FALLBACK_CODE` 的注释 |
+| 其余 5xx | `5000` | 兜底：5xx 对本服务都是「内部错误」这一档 |
+
+**文案策略**：框架的 `exc.detail` 是给开发者看的（`HTTPBearer` 抛的就是
+`"Not authenticated"` / `"Not enough permissions"`），故一律换成平台面向用户的文案，
+MUST NOT 把 `detail` 回显进响应体；`detail` 也不进日志（它可能带上游传入的内容）。
 """

 from __future__ import annotations

 import logging
 from collections.abc import Mapping, Sequence
 from datetime import UTC, datetime
-from typing import Any, Final, cast
+from typing import Any, Final, NamedTuple, cast

 from fastapi import FastAPI, Request
 from fastapi.exceptions import RequestValidationError
 from fastapi.responses import JSONResponse
+from starlette.exceptions import HTTPException as StarletteHTTPException

 from aicore.core.trace import get_trace_id

 logger = logging.getLogger(__name__)

 # ---------------------------------------------------------------------------
 # 业务码常量
 #
 # 取值只能来自 `_common/openapi.yaml` 的 ErrorCode 枚举；本服务只用到其中 10 个。
 # 常量名一律以 `_CODE` 结尾且带 `CODE` 字样：**它们是业务码，不是 HTTP 状态码**，
 # 两者读写时 MUST NOT 互相代入（例如 `RATE_LIMITED_CODE` 是 2004，不是 429）。
+#
+# ===========================================================================
+# 【新增一个业务码的完整清单：四处，缺一处就会静默出错】
+#
+#   1. 本文件顶部的码值常量（`XXX_CODE`）——并把它加进下面的 `AICORE_ERROR_CODES`。
+#      ⚠ 漏掉这一处最危险：raise 侧会在**构造期**抛 ValueError，
+#        于是业务失败被 500 处理器接走，前端拿到 5000（而不是新码）。
+#   2. 本文件的 `DEFAULT_MESSAGES`——缺文案会在渲染信封时 KeyError（等于 500）。
+#   3. 本文件的 `HTTP_STATUS_BY_ERROR_CODE`——缺状态会在渲染信封时 KeyError。
+#   4. `tests/unit/test_errors.py` 里**用字面量钉住的两张表**：
+#      `test_aicore_error_codes_is_exactly_the_emittable_set`（码集合）
+#      与 `test_http_status_table_matches_the_locked_platform_mapping`（码 → 状态）。
+#      另：框架校验路径若新增判定依据，`_RANGE_ERROR_TYPES` / `_MISSING_ERROR_TYPES`
+#      与 `test_validation_error_type_mapping` 同步。
+#
+#   前提：该码必须先在 `_common/openapi.yaml` 的 `ErrorCode` 枚举里存在
+#   （比对用例 `test_aicore_error_codes_all_exist_in_the_platform_enum` 强制此红线）。
+#   把四处写在一起，是为了「加码」这件事在评审里有唯一可核对的落点。
+# ===========================================================================
 # ---------------------------------------------------------------------------

 #: 参数缺失。
 PARAM_MISSING_CODE: Final = 1001
 #: 参数格式错误。
 PARAM_FORMAT_CODE: Final = 1002
 #: 枚举或范围非法。
 PARAM_VALUE_CODE: Final = 1003
 #: 未登录 / Token 失效。
 UNAUTHORIZED_CODE: Final = 2001
@@ -126,20 +173,58 @@ HTTP_STATUS_BY_ERROR_CODE: Final[Mapping[int, int]] = {
     RATE_LIMITED_CODE: 429,
     NOT_FOUND_CODE: 404,
     CHANNEL_FAILURE_CODE: 502,
     INTERNAL_ERROR_CODE: 500,
     DEPENDENCY_TIMEOUT_CODE: 504,
 }

 #: 框架参数校验失败的 HTTP 状态：保留 FastAPI 原生的 422，只把响应体换成平台信封。
 VALIDATION_HTTP_STATUS: Final = 422

+#: 框架 `HTTPException` 的 **HTTP 状态 → 业务码**：只能取控制者锁定的那几对。
+#: 键是 HTTP 状态、值是业务码，方向与 `HTTP_STATUS_BY_ERROR_CODE` 相反但同样不许混用。
+#: 用途：Starlette 路由未匹配（404）与方法不允许（405）抛的是基类 `HTTPException`，
+#: 以及 `HTTPBearer` 等框架依赖内部抛的 401/403——这些都不经过业务代码，只能在此收编。
+HTTP_STATUS_BY_HTTP_EXCEPTION_STATUS: Final[Mapping[int, int]] = {
+    401: UNAUTHORIZED_CODE,
+    403: FORBIDDEN_CODE,
+    404: NOT_FOUND_CODE,
+    429: RATE_LIMITED_CODE,
+    500: INTERNAL_ERROR_CODE,
+    502: CHANNEL_FAILURE_CODE,
+    504: DEPENDENCY_TIMEOUT_CODE,
+}
+
+#: 未匹配到的 4xx 的兜底业务码：**只能取平台表里真实存在的码，不为 405 之类的状态发明新码**。
+#: 取 `1001`（参数缺失）的理由：平台表的 `1xxx` 段是「参数校验」，而未匹配的路由
+#: （404）与不被允许的方法（405）**就是**「请求的这一路参数不对」——请求打错了地方；
+#: 普通业务 400 走 `AiCoreError` / `ParamError` 两档，不经过本兜底，
+#: 故此处不会遮住任何业务规则，代价只是 message 用 1001 的平台文案（不暴露路由细节）。
+HTTP_EXCEPTION_4XX_FALLBACK_CODE: Final = PARAM_MISSING_CODE
+
+#: 未匹配到的 5xx 的兜底业务码：对本服务而言 5xx 都是「内部错误」这一档。
+HTTP_EXCEPTION_5XX_FALLBACK_CODE: Final = INTERNAL_ERROR_CODE
+
+#: 框架路由 404 的专用文案：业务码与业务 `NotFoundError` 同为 `3006`（锁定对），
+#: 但**不存在的是接口而不是对象**，文案必须能区分，否则排障时分不清「路径写错」与「查无此对象」。
+#: 它是平台文案表之外唯一新增的文案，理由即是这一条区分需求。
+ROUTE_NOT_FOUND_MESSAGE: Final = "接口不存在"
+
+#: 框架 `HTTPException` 专用的文案覆盖：键是 **HTTP 状态**。
+#: 只放 `404`（见 `ROUTE_NOT_FOUND_MESSAGE`）；其余状态一律取 `DEFAULT_MESSAGES[业务码]`
+#: ——平台文案已按「面向用户、可直接展示」评审过，框架的 `detail` 不在其列。
+HTTP_ERROR_MESSAGES: Final[Mapping[int, str]] = {404: ROUTE_NOT_FOUND_MESSAGE}
+
+#: HTTP 状态分段边界（`_http_exception_info` 的兜底档判据）：它们是 HTTP 状态，不是业务码。
+_CLIENT_ERROR_MIN: Final = 400
+_SERVER_ERROR_MIN: Final = 500
+
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
@@ -161,20 +246,29 @@ _RANGE_ERROR_TYPES: Final[frozenset[str]] = frozenset(
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
+        # Decimal 的位数约束（pydantic 的 `decimal_max_digits` / `decimal_places` 三型）：
+        # 与上面的数值/长度范围同类，属「枚举或范围非法」（1003），故不落 1002 兜底。
+        # 实测（pydantic 2.13.5）：`Field(max_digits=…)` 触发 `decimal_max_digits`、
+        # `Field(decimal_places=…)` 触发 `decimal_max_places`；`decimal_whole_digits`
+        # 用常规 Field 约束触发不到（pydantic-core 报的是 max_digits），但仍按范围类收列，
+        # 以免它一旦出现就落到 1002 兜底。
+        "decimal_max_digits",
+        "decimal_max_places",
+        "decimal_whole_digits",
     }
 )


 class AiCoreError(Exception):
     """业务异常基类：所有**可预期**的业务失败都从这里派生。

     两个字段的语义（MUST NOT 混用）：

     - `code`：**业务码**，取值只能是 `AICORE_ERROR_CODES` 内的值，构造期强校验；
@@ -263,34 +357,48 @@ class ChannelFailureError(AiCoreError):

     code: int = CHANNEL_FAILURE_CODE


 class DependencyTimeoutError(AiCoreError):
     """依赖超时 / 熔断（`5002`，HTTP 504）：**没等到响应**。"""

     code: int = DEPENDENCY_TIMEOUT_CODE


+class _HTTPExceptionInfo(NamedTuple):
+    """框架 `HTTPException` 的映射结果：HTTP 状态原样保留，业务码与文案由本模块决定。"""
+
+    status_code: int
+    code: int
+    message: str
+
+
 def register_exception_handlers(app: FastAPI) -> None:
-    """把三条错误路径收编到平台信封。由组合根 `main.create_app()` 调用。
+    """把四条错误路径收编到平台信封。由组合根 `main.create_app()` 调用。

     - `AiCoreError` → 业务码对应的 HTTP 状态 + 信封；
     - `RequestValidationError` → HTTP 422 + `1xxx` 信封（收编框架默认的 `{"detail": [...]}`，
       否则前端会同时收到两种响应形状）；
+    - `StarletteHTTPException` → 原 HTTP 状态 + 映射业务码的信封（覆盖 FastAPI 预注册的
+      `http_exception_handler`，它回的是 `{"detail": …}`）。**必须用 Starlette 的基类注册**：
+      FastAPI 预注册的键就是 `starlette.exceptions.HTTPException`，而路由层「未匹配路径」（404）
+      与「方法不允许」（405）抛的正是这个基类实例，二者是同一个键；
+      `HTTPBearer` 等依赖抛的 401/403 同理由此收编（详见模块 docstring）；
     - `Exception` → HTTP 500 + `code=5000` 信封（Starlette 会把它提升为 ServerErrorMiddleware
       的 error_handler，故「逃逸出应用的未预期异常」也走信封；组合根把 traceId 中间件包在
       ServerErrorMiddleware 之外，处理器执行时上下文尚未回滚，信封里的 traceId 与请求一致）。

     幂等：同一应用上重复调用只是覆盖同名处理器，`create_app()` 可被多次调用。
     """
     app.add_exception_handler(AiCoreError, _handle_ai_core_error)
     app.add_exception_handler(RequestValidationError, _handle_request_validation_error)
+    app.add_exception_handler(StarletteHTTPException, _handle_http_exception)
     app.add_exception_handler(Exception, _handle_unexpected_error)


 async def _handle_ai_core_error(request: Request, exc: Exception) -> JSONResponse:
     """业务异常 → 信封。

     `exc` 的注解是 `Exception` 而非 `AiCoreError`：Starlette 的 `ExceptionHandler` 把第二
     个参数声明为基类，写窄类型过不了 mypy strict；类型由注册契约保证，故此处 `cast`。
     """
     error = cast(AiCoreError, exc)
@@ -316,20 +424,56 @@ async def _handle_request_validation_error(request: Request, exc: Exception) ->
         code,
         request.url.path,
         _loggable_errors(errors),
     )
     return JSONResponse(
         status_code=VALIDATION_HTTP_STATUS,
         content=_error_body(code, DEFAULT_MESSAGES[code]),
     )


+async def _handle_http_exception(request: Request, exc: Exception) -> JSONResponse:
+    """框架 `HTTPException` → 原 HTTP 状态 + 映射业务码的信封。
+
+    收编对象（都在业务代码之外，调用点无法拦截）：
+
+    - Starlette 路由层抛的 404（路径未匹配）与 405（方法不允许）——FastAPI 预注册的
+      `http_exception_handler` 回的是 `{"detail": …}`（无 `code` 的第三种形状），本处理器覆盖它；
+    - `HTTPBearer` 等框架依赖内部抛的 401 / 403；
+    - 任何 `raise HTTPException(...)` 的历史代码（本服务的新代码 MUST NOT 这么写）。
+
+    三条口径（**MUST NOT 自行发挥**）：
+
+    1. `exc.status_code` 原样作为响应的 HTTP 状态；
+    2. 业务码取 `_http_exception_info()` 的映射结果：锁定对优先，其余 4xx → 1001、5xx → 5000；
+    3. 文案只取平台文案表（404 用 `ROUTE_NOT_FOUND_MESSAGE`），**MUST NOT 回显 `exc.detail`**
+       —— 框架的 detail 是给开发者看的（`HTTPBearer` 抛的是 `"Not authenticated"`），
+       平台文案才是面向用户评审过的那一份。
+
+    `exc.headers` 原样透传：FastAPI 的默认处理器就是这么做，也是 HTTP 协议的要求
+    （`HTTPBearer` 的 401 会带 `WWW-Authenticate: Bearer`）。收编响应体 MUST NOT 顺手丢掉它，
+    否则 `WWW-Authenticate` 之类对客户端有协议意义的头会静默消失。
+    """
+    http_exc = cast(StarletteHTTPException, exc)
+    info = _http_exception_info(http_exc.status_code)
+    body = _error_body(info.code, info.message)
+    logger.info(
+        "框架 HTTP 异常 code=%s http=%s method=%s path=%s traceId=%s",
+        info.code,
+        info.status_code,
+        request.method,
+        request.url.path,
+        body["traceId"],
+    )
+    return JSONResponse(status_code=info.status_code, content=body, headers=http_exc.headers)
+
+
 async def _handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
     """未预期异常 → HTTP 500 + `code=5000`，堆栈只进日志。

     响应体**只**放平台固定文案：`str(exc)`、traceback、文件路径、模块名一律不进响应
     （test_errors.py 正面钉住「响应体里没有这些串」）。

     显式传 `exc_info=exc` 而不用 `logger.exception()`：本处理器是 Starlette 在 `except`
     块里 await 的，`logger.exception()` 依赖 `sys.exc_info()`，把异常对象本身交给日志
     才与「一定记下这条异常的堆栈」等价。
     """
@@ -340,20 +484,41 @@ async def _handle_unexpected_error(request: Request, exc: Exception) -> JSONResp
         request.url.path,
         get_trace_id(),
         exc_info=exc,
     )
     return JSONResponse(
         status_code=HTTP_STATUS_BY_ERROR_CODE[INTERNAL_ERROR_CODE],
         content=_error_body(INTERNAL_ERROR_CODE, DEFAULT_MESSAGES[INTERNAL_ERROR_CODE]),
     )


+def _http_exception_info(status_code: int) -> _HTTPExceptionInfo:
+    """HTTP 状态 → `(状态, 业务码, 文案)`：锁定对优先，未列出的按段兜底。
+
+    - 4xx 兜底 `1001`、5xx 兜底 `5000`（理由见两个兜底常量的注释）；
+    - 文案优先取 `HTTP_ERROR_MESSAGES[状态]`（目前只有 404 的专用文案），否则取该业务码的
+      平台文案——两条路都**不碰** `exc.detail`；
+    - `status_code` 不在 4xx/5xx 段内时（框架理论上不会这么抛）按 5xx 兜底处理：宁可回
+      「内部错误」，也不把段外状态硬塞进某个业务段。
+    """
+    code = HTTP_STATUS_BY_HTTP_EXCEPTION_STATUS.get(status_code)
+    if code is None:
+        # 400/500 是 HTTP 段边界字面量，不是业务码；此处刻意不引业务码常量，避免误读。
+        code = (
+            HTTP_EXCEPTION_4XX_FALLBACK_CODE
+            if _CLIENT_ERROR_MIN <= status_code < _SERVER_ERROR_MIN
+            else HTTP_EXCEPTION_5XX_FALLBACK_CODE
+        )
+    message = HTTP_ERROR_MESSAGES.get(status_code, DEFAULT_MESSAGES[code])
+    return _HTTPExceptionInfo(status_code=status_code, code=code, message=message)
+
+
 def _validation_error_code(errors: Sequence[Mapping[str, Any]]) -> int:
     """按「缺失 > 枚举或范围 > 格式」的优先级，把校验错误归到 `1xxx`。

     只回一个码：信封只承载一个业务码，多个字段同时失败时按优先级取最该先修的那个。
     无法归类的 type 落 `1002`（兜底），故新增 pydantic 错误类型不会漏成 5000。
     """
     types = {str(item.get("type", "")) for item in errors}
     if types & _MISSING_ERROR_TYPES:
         return PARAM_MISSING_CODE
     if types & _RANGE_ERROR_TYPES:
diff --git a/services/aicore/tests/unit/test_errors.py b/services/aicore/tests/unit/test_errors.py
index bc69720..2f026a6 100644
--- a/services/aicore/tests/unit/test_errors.py
+++ b/services/aicore/tests/unit/test_errors.py
@@ -1,60 +1,80 @@
 """异常层次与错误码映射用例（Task 2.3）。

 覆盖点（全部跑真实 HTTP 链路，只有校验分类器是直接调函数）：

 1. 每个异常类 → 业务码 + HTTP 状态（含 `ParamError` 三档与缺省档）；
 2. 信封形状：四必填字段 `code` / `message` / `traceId` / `timestamp` 加可选的 `data`，
    失败时 `data=null`；`timestamp` 为 UTC ISO 8601；`traceId` 取自请求头 `X-Request-Id`
    （缺失时生成 16 位小写 hex）；
 3. FastAPI 默认 422 + `{"detail": [...]}` 被收编成信封（1xxx），响应体里不留框架结构；
-4. 未预期异常 → HTTP 500 + `code=5000`，响应体不含堆栈 / 文件路径 / 模块名 / 原始异常消息，
+4. 框架 `HTTPException`（Starlette 基类）被收编成信封：路由未匹配的 404 → `3006`（文案与业务
+   `NotFoundError` 相区分）、方法不允许的 405 → `1001`、`HTTPBearer` 式的 401/403 →
+   `2001`/`2002`、未列入锁定对的 5xx → `5000`；**框架的 `detail` 一律不回显**；
+5. 未预期异常 → HTTP 500 + `code=5000`，响应体不含堆栈 / 文件路径 / 模块名 / 原始异常消息，
    而**堆栈确实进了日志**（caplog 里取到带 traceback 的 ERROR 记录）；
-5. `AICORE_ERROR_CODES` 与平台单一事实源 `services/_common/openapi.yaml` 的 `ErrorCode`
+6. `AICORE_ERROR_CODES` 与平台单一事实源 `services/_common/openapi.yaml` 的 `ErrorCode`
    枚举逐项比对，且**阴性方向**有判别力：凭空加一个枚举外的码（含把 HTTP 429 当业务码）
    必须被判定器抓出来；
-6. 业务码与 HTTP 状态不混用：集合不含 HTTP 状态，限流是 `(HTTP 429, code 2004)`；
-7. `/health` 仍是裸响应（Task 1.4 验收项，注册处理器后 MUST NOT 回归）。
+7. 业务码与 HTTP 状态不混用：集合不含 HTTP 状态，限流是 `(HTTP 429, code 2004)`；
+8. `/health` 仍是裸响应（Task 1.4 验收项，注册处理器后 MUST NOT 回归）。

 探针路由由夹具挂到用例自己的 `create_app()` 实例上，生产代码不含任何调试端点。
+
+**为什么单独测框架 `HTTPException`**：FastAPI 构造时已经为 `starlette.exceptions.HTTPException`
+这个键预注册了它的 `http_exception_handler`，回的是 `{"detail": …}`（**没有 `code` 字段**的第三种
+响应形状）；而 Starlette 路由层在未匹配路径（404）与方法不允许（405）时抛的正是这个基类实例。
+这些响应在业务代码之外产生，调用点无法拦截，故只能在这里正面钉住。
 """

 from __future__ import annotations

 import itertools
 import logging
 import re
 import traceback
 from collections.abc import Callable, Collection, Iterable, Iterator
 from datetime import UTC, datetime, timedelta
+from decimal import Decimal
 from pathlib import Path
-from typing import Annotated, Literal
+from typing import Annotated, Any, Literal

+import httpx
 import pytest
 import yaml
 from fastapi import FastAPI, Query
 from fastapi.exceptions import RequestValidationError
 from fastapi.testclient import TestClient
+from pydantic import BaseModel, Field, ValidationError
+from starlette.exceptions import HTTPException as StarletteHTTPException

 from aicore.core.errors import (
     AICORE_ERROR_CODES,
     DEFAULT_MESSAGES,
+    HTTP_EXCEPTION_4XX_FALLBACK_CODE,
+    HTTP_EXCEPTION_5XX_FALLBACK_CODE,
     HTTP_STATUS_BY_ERROR_CODE,
+    HTTP_STATUS_BY_HTTP_EXCEPTION_STATUS,
     PARAM_ERROR_CODES,
+    ROUTE_NOT_FOUND_MESSAGE,
     AiCoreError,
     ChannelFailureError,
     DependencyTimeoutError,
     ForbiddenError,
     NotFoundError,
     ParamError,
     RateLimitedError,
     UnauthorizedError,
+    _handle_ai_core_error,
+    _handle_http_exception,
+    _handle_request_validation_error,
+    _handle_unexpected_error,
     _validation_error_code,
 )
 from aicore.core.trace import TRACE_ID_HEADER
 from aicore.main import create_app

 SERVICE_ROOT = Path(__file__).resolve().parents[2]
 #: 平台错误码单一事实源：`services/_common/openapi.yaml`（各服务文档 $ref 引用它，勿内联）。
 PLATFORM_OPENAPI = SERVICE_ROOT.parent / "_common" / "openapi.yaml"

 #: 信封的四个必填字段 + 可选的 `data`（失败时为 null）。
@@ -119,20 +139,46 @@ def raising_route(app: FastAPI) -> Callable[[BaseException], str]:
     return _register


 @pytest.fixture
 def error_client(app: FastAPI) -> Iterator[TestClient]:
     """不把服务端异常抛回用例的客户端：未预期异常要断言的是**响应体**，不是异常本身。"""
     with TestClient(app, raise_server_exceptions=False) as c:
         yield c


+@pytest.fixture
+def http_exception_route(app: FastAPI) -> Callable[[int, str], str]:
+    """登记一条「抛出框架 `HTTPException`」的测试专用路由，返回它的路径。
+
+    模拟的是业务代码之外的框架路径：`HTTPBearer` 之类的依赖内部抛 401/403，
+    调用点无法拦截（`HTTPBearer` 真实抛的是基类 `starlette.exceptions.HTTPException`，
+    且带 `WWW-Authenticate: Bearer` 头）。`detail` 刻意可定制，用来证明响应体不回显框架文案。
+    """
+    counter = itertools.count()
+
+    def _register(status_code: int, detail: str) -> str:
+        path = f"/__test__/http-exc-{next(counter)}"
+
+        async def _raise() -> None:
+            raise StarletteHTTPException(
+                status_code=status_code,
+                detail=detail,
+                headers={"WWW-Authenticate": "Bearer"} if status_code == 401 else None,
+            )
+
+        app.add_api_route(path, _raise, methods=["GET"], include_in_schema=False)
+        return path
+
+    return _register
+
+
 @pytest.fixture
 def validation_client(app: FastAPI, client: TestClient) -> TestClient:
     """带参数校验探针路由的客户端：用真实的 FastAPI 校验链路触发 422。

     四类失败来源各留一个入口：缺参（missing）、整数解析失败（int_parsing）、
     字面量不在允许集合（literal_error）、超出上界（less_than_equal）。
     """

     @app.get("/__test__/validate", include_in_schema=False)
     async def _validate(
@@ -303,24 +349,193 @@ def test_timestamp_is_iso8601_utc_within_the_request_window(


 def test_health_stays_bare_after_handlers_are_registered(client: TestClient) -> None:
     """`/health` MUST NOT 被信封包裹（Task 1.4 验收项；注册处理器不得让它回归）。"""
     response = client.get("/health")
     assert response.status_code == 200
     assert response.json() == {"status": "ok"}
     assert set(response.json()).isdisjoint(ENVELOPE_KEYS)


-def test_create_app_registers_the_three_handlers() -> None:
-    """组合根必须真的接线三条路径：业务异常 / 框架校验 / 未预期异常。"""
+def test_create_app_registers_the_four_handlers() -> None:
+    """组合根必须真的接线四条路径：业务异常 / 框架校验 / 框架 HTTPException / 未预期异常。
+
+    **断言处理器身份而不是键存在**：FastAPI 在构造 `FastAPI()` 时就预注册了
+    `RequestValidationError` 与 `starlette.exceptions.HTTPException` 的**默认**处理器
+    （`request_validation_exception_handler` / `http_exception_handler`），故「键存在」对这两条
+    路径恒真、没有判别力——把 `register_exception_handlers()` 的对应一行删掉，用例照样全绿。
+    比对象身份才能让「接线」这件事真的可判：删掉注册行，字典里的值退回 FastAPI 的默认函数，
+    本用例立刻变红。
+
+    另注意：FastAPI 注册 `HTTPException` 时用的键就是 `starlette.exceptions.HTTPException`
+    （实测 `fastapi.HTTPException is starlette.exceptions.HTTPException` 为 **False**，
+    但预注册的键是基类），故本模块的那一行是**覆盖**默认处理器而非并存——这正是想要的：
+    同一个键不可能既回 `{"detail": …}` 又回信封。
+    """
     handlers = create_app().exception_handlers
-    assert {AiCoreError, RequestValidationError, Exception} <= set(handlers)
+    assert handlers[AiCoreError] is _handle_ai_core_error
+    assert handlers[RequestValidationError] is _handle_request_validation_error
+    assert handlers[StarletteHTTPException] is _handle_http_exception
+    assert handlers[Exception] is _handle_unexpected_error
+
+
+# ---------------------------------------------------------------------------
+# 2.5 框架 HTTPException 被收编（Starlette 基类：路由 404/405 与 HTTPBearer 的 401/403）
+# ---------------------------------------------------------------------------
+
+#: 框架 `detail` 的哨兵值：一旦被回显进响应体，「不回显 detail」的断言立刻变红。
+FRAMEWORK_DETAIL_SENTINEL = "FRAMEWORK_DETAIL_MUST_NOT_LEAK"
+
+#: 框架默认响应体的固定片段：路由 404/405 的 `{"detail": "Not Found"}` /
+#: `{"detail": "Method Not Allowed"}` 与 `HTTPBearer` 的 `"Not authenticated"` /
+#: `"Not enough permissions"` 都在此列。
+FRAMEWORK_DEFAULT_DETAILS = (
+    "Not Found",
+    "Method Not Allowed",
+    "Not authenticated",
+    "Not enough permissions",
+)
+
+
+def assert_enveloped(
+    response: httpx.Response, expected_status: int, expected_code: int, expected_message: str
+) -> dict[str, Any]:
+    """断言一条响应已完全信封化：状态 + 业务码 + 四键齐全 + 无 `detail` + 无框架文案。
+
+    被框架 `HTTPException` 的用例共用：它们的共同点正是「响应体里不许留下框架痕迹」。
+    """
+    body: dict[str, Any] = response.json()
+    assert response.status_code == expected_status
+    assert set(body) == ENVELOPE_KEYS, f"信封键集合不符：{sorted(body)}"
+    assert body["code"] == expected_code
+    assert body["code"] != response.status_code, "业务码 MUST NOT 等于 HTTP 状态"
+    assert body["data"] is None
+    assert body["message"] == expected_message
+    assert "detail" not in body
+    # traceId / timestamp 的保证与其余路径一致。
+    assert TRACE_ID_PATTERN.fullmatch(body["traceId"])
+    assert ISO8601_UTC_PATTERN.fullmatch(body["timestamp"])
+    assert response.headers["content-type"].startswith("application/json")
+    for leaked in (*FRAMEWORK_DEFAULT_DETAILS, FRAMEWORK_DETAIL_SENTINEL):
+        assert leaked not in response.text, f"响应体回显了框架文案：{leaked}"
+    return body
+
+
+def test_unmatched_route_is_enveloped_as_route_not_found(client: TestClient) -> None:
+    """未匹配路由 → HTTP 404 + `code=3006` + 与业务「对象不存在」**不同**的文案。
+
+    `3006` 的配对是控制者锁定的；但不存在的是**接口**而不是对象，故文案必须是「接口不存在」，
+    否则排障时分不清「路径写错」与「查无此对象」。
+    """
+    body = assert_enveloped(
+        client.get("/__test__/no-such-route"), 404, 3006, ROUTE_NOT_FOUND_MESSAGE
+    )
+
+    assert body["message"] != DEFAULT_MESSAGES[3006], (
+        "路由 404 与业务 NotFoundError 的文案必须可区分"
+    )
+    # 文案不是框架的 `detail`（`{"detail": "Not Found"}` 的形状已被彻底替换）。
+    assert body["message"] != "Not Found"
+
+
+def test_disallowed_method_is_enveloped(client: TestClient, app: FastAPI) -> None:
+    """方法不允许 → HTTP 405 + `code=1001`（兜底），信封形状与其余路径一致。
+
+    405 在平台表里**没有**对应码，控制者的口径是「留在平台表内、用未匹配 4xx 的兜底 `1001`」，
+    不为它发明新码——故这里正面钉住 `1001`，防止后人「顺手加个 405 专用码」。
+    """
+
+    @app.get("/__test__/method-probe", include_in_schema=False)
+    async def _probe() -> dict[str, str]:
+        return {"ok": "yes"}
+
+    body = assert_enveloped(
+        client.post("/__test__/method-probe"), 405, 1001, DEFAULT_MESSAGES[1001]
+    )
+    assert body["message"] != "Method Not Allowed"
+
+
+@pytest.mark.parametrize(
+    ("status_code", "expected_code", "reason"),
+    [
+        pytest.param(401, 2001, "锁定对：HTTPBearer 未带凭据", id="unauthorized-401"),
+        pytest.param(403, 2002, "锁定对：HTTPBearer 权限不足", id="forbidden-403"),
+        pytest.param(503, 5000, "未列入锁定对的 5xx → 兜底 5000", id="unmatched-5xx-503"),
+    ],
+)
+def test_framework_http_exception_is_enveloped_with_platform_message(
+    client: TestClient,
+    http_exception_route: Callable[[int, str], str],
+    status_code: int,
+    expected_code: int,
+    reason: str,
+) -> None:
+    """框架 `HTTPException` → 原 HTTP 状态 + 平台业务码 + **平台文案**（不是框架 `detail`）。
+
+    这三个状态都来自业务代码之外：401/403 是 `HTTPBearer` 之类的依赖内部抛的（调用点拦不住），
+    503 代表任何未列入锁定对的 5xx。响应体里只允许出现平台文案 —— `detail` 是给开发者看的，
+    平台文案才是评审过、可直接展示给用户的那一份。
+    """
+    path = http_exception_route(status_code, FRAMEWORK_DETAIL_SENTINEL)
+    body = assert_enveloped(
+        client.get(path), status_code, expected_code, DEFAULT_MESSAGES[expected_code]
+    )
+    assert FRAMEWORK_DETAIL_SENTINEL not in body["message"], reason
+
+
+def test_framework_http_exception_keeps_trace_id_from_request_header(
+    client: TestClient, http_exception_route: Callable[[int, str], str]
+) -> None:
+    """框架 `HTTPException` 的信封同样取网关注入的 traceId（不另造来源）。"""
+    path = http_exception_route(401, "Not authenticated")
+    response = client.get(path, headers={TRACE_ID_HEADER: INJECTED_TRACE_ID})
+    assert response.json()["traceId"] == INJECTED_TRACE_ID
+    assert response.headers[TRACE_ID_HEADER] == INJECTED_TRACE_ID
+
+
+def test_framework_http_exception_keeps_its_headers(
+    client: TestClient, http_exception_route: Callable[[int, str], str]
+) -> None:
+    """`exc.headers` 原样透传：收编响应体 MUST NOT 顺手丢掉协议头。
+
+    `HTTPBearer` 的 401 带 `WWW-Authenticate: Bearer`，FastAPI 的默认处理器同样透传它；
+    丢掉这个头客户端就不知道该怎么补凭据。
+    """
+    response = client.get(http_exception_route(401, "Not authenticated"))
+    assert response.headers.get("WWW-Authenticate") == "Bearer"
+    assert response.status_code == 401
+
+
+def test_http_exception_status_mapping_is_exactly_the_locked_pairs() -> None:
+    """状态 → 码的映射用**字面量**钉住（避免表与断言互相印证），并钉住两个兜底码。
+
+    只测 401/403/503 三条状态的话，锁定对里的 404/429/500/502/504 一旦被改动就没有用例会红。
+    这里把整张表与两个兜底常量一起钉住：新增/删除锁定对必须同时改本用例，评审才有落点。
+    """
+    assert dict(HTTP_STATUS_BY_HTTP_EXCEPTION_STATUS) == {
+        401: 2001,
+        403: 2002,
+        404: 3006,
+        429: 2004,
+        500: 5000,
+        502: 4003,
+        504: 5002,
+    }
+    # 表里的值只能是业务码，键只能是 HTTP 状态（两个维度 MUST NOT 互相代入）。
+    assert set(HTTP_STATUS_BY_HTTP_EXCEPTION_STATUS.values()) <= AICORE_ERROR_CODES
+    assert all(400 <= status < 600 for status in HTTP_STATUS_BY_HTTP_EXCEPTION_STATUS)
+    # 兜底码必须在平台表内：405 之类没有专属码的状态只能落到这里，不许发明新码。
+    assert HTTP_EXCEPTION_4XX_FALLBACK_CODE == 1001
+    assert HTTP_EXCEPTION_5XX_FALLBACK_CODE == 5000
+    assert {HTTP_EXCEPTION_4XX_FALLBACK_CODE, HTTP_EXCEPTION_5XX_FALLBACK_CODE} <= (
+        AICORE_ERROR_CODES
+    )


 # ---------------------------------------------------------------------------
 # 3. FastAPI 默认 422 被收编
 # ---------------------------------------------------------------------------


 def test_validation_probe_route_accepts_valid_params(validation_client: TestClient) -> None:
     """探针路由本身可用：下面的 1xxx 确实来自参数校验，而不是路由写错。"""
     response = validation_client.get("/__test__/validate?name=x&limit=5&mode=fast")
@@ -396,20 +611,24 @@ def test_validation_log_keeps_types_but_not_user_input(
         pytest.param("less_than", 1003, id="less_than"),
         pytest.param("less_than_equal", 1003, id="less_than_equal"),
         pytest.param("multiple_of", 1003, id="multiple_of"),
         pytest.param("finite_number", 1003, id="finite_number"),
         pytest.param("too_short", 1003, id="too_short"),
         pytest.param("too_long", 1003, id="too_long"),
         pytest.param("string_too_short", 1003, id="string_too_short"),
         pytest.param("string_too_long", 1003, id="string_too_long"),
         pytest.param("bytes_too_short", 1003, id="bytes_too_short"),
         pytest.param("bytes_too_long", 1003, id="bytes_too_long"),
+        # Decimal 位数约束（M3 评审项）：与数值/长度范围同类，归 1003 而不是落 1002 兜底。
+        pytest.param("decimal_max_digits", 1003, id="decimal_max_digits"),
+        pytest.param("decimal_max_places", 1003, id="decimal_max_places"),
+        pytest.param("decimal_whole_digits", 1003, id="decimal_whole_digits"),
         pytest.param("int_parsing", 1002, id="int_parsing"),
         pytest.param("string_type", 1002, id="string_type"),
         pytest.param("string_pattern_mismatch", 1002, id="string_pattern_mismatch"),
         pytest.param("extra_forbidden", 1002, id="extra_forbidden"),
         pytest.param("json_invalid", 1002, id="json_invalid"),
         pytest.param("aicore_future_error_type", 1002, id="unknown-type-falls-back"),
     ],
 )
 def test_validation_error_type_mapping(error_type: str, expected_code: int) -> None:
     """直接钉住分类表：pydantic 的 type 字符串很多，逐个用端点触发不现实。
@@ -422,20 +641,43 @@ def test_validation_error_type_mapping(error_type: str, expected_code: int) -> N

 def test_validation_error_code_priority() -> None:
     """多个错误同时命中时的优先级：缺失 > 枚举或范围 > 格式。"""
     mixed = [{"type": "int_parsing"}, {"type": "literal_error"}, {"type": "missing"}]
     assert _validation_error_code(mixed) == 1001
     assert _validation_error_code([{"type": "int_parsing"}, {"type": "literal_error"}]) == 1003
     assert _validation_error_code([{"type": "int_parsing"}]) == 1002
     assert _validation_error_code([]) == 1002


+def test_decimal_digit_constraints_are_real_pydantic_types() -> None:
+    """M3 评审项的**行为证据**：Decimal 位数约束真的由 pydantic 发出这些 type，且归 `1003`。
+
+    分类表（`test_validation_error_type_mapping`）用字面量钉住映射，但字面量写错名字也不会红；
+    这里补上行为证据：真造 pydantic 校验错误、取它实际发出的 `type` 再喂给分类器。
+    （实测 pydantic 2.13.5：`max_digits` → `decimal_max_digits`、`decimal_places` →
+    `decimal_max_places`；`decimal_whole_digits` 用常规 `Field` 约束触发不到，故只在上表里
+    按范围类收列，以免它一旦出现就落 1002 兜底。）
+    """
+
+    class _Amount(BaseModel):
+        value: Annotated[Decimal, Field(max_digits=4, decimal_places=2)]
+
+    cases = {"123.45": "decimal_max_digits", "1.234": "decimal_max_places"}
+    for raw, expected_type in cases.items():
+        with pytest.raises(ValidationError) as exc_info:
+            _Amount(value=raw)
+
+        types = [str(item["type"]) for item in exc_info.value.errors()]
+        assert types == [expected_type], (raw, types)
+        assert _validation_error_code([{"type": t} for t in types]) == 1003, raw
+
+
 # ---------------------------------------------------------------------------
 # 4. 未预期异常 → 5000，堆栈只进日志
 # ---------------------------------------------------------------------------


 def test_unexpected_exception_maps_to_5000(
     error_client: TestClient, raising_route: Callable[[BaseException], str]
 ) -> None:
     """未预期异常 → HTTP 500 + code=5000；信封照样四字段齐全、data=null。"""
     path = raising_route(RuntimeError(UNEXPECTED_ERROR_MESSAGE))

```
