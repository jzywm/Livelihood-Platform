"""异常层次与错误码映射用例（Task 2.3）。

覆盖点（全部跑真实 HTTP 链路，只有校验分类器是直接调函数）：

1. 每个异常类 → 业务码 + HTTP 状态（含 `ParamError` 三档与缺省档）；
2. 信封形状：四必填字段 `code` / `message` / `traceId` / `timestamp` 加可选的 `data`，
   失败时 `data=null`；`timestamp` 为 UTC ISO 8601；`traceId` 取自请求头 `X-Request-Id`
   （缺失时生成 16 位小写 hex）；
3. FastAPI 默认 422 + `{"detail": [...]}` 被收编成信封（1xxx），响应体里不留框架结构；
4. 框架 `HTTPException`（Starlette 基类）被收编成信封：路由未匹配的 404 → `3006`（文案与业务
   `NotFoundError` 相区分）、方法不允许的 405 → `1001`、`HTTPBearer` 式的 401/403 →
   `2001`/`2002`、未列入锁定对的 5xx → `5000`；**框架的 `detail` 一律不回显**；
   状态不允许响应体时（`1xx` / `204` / `205` / `304`）**回无体响应**（与 FastAPI 默认处理器
   同一契约，`exc.headers` 仍透传），sub-400 状态 **MUST NOT** 落 `5000`；
5. 未预期异常 → HTTP 500 + `code=5000`，响应体不含堆栈 / 文件路径 / 模块名 / 原始异常消息，
   而**堆栈确实进了日志**（caplog 里取到带 traceback 的 ERROR 记录）；
6. `AICORE_ERROR_CODES` 与平台单一事实源 `services/_common/openapi.yaml` 的 `ErrorCode`
   枚举逐项比对，且**阴性方向**有判别力：凭空加一个枚举外的码（含把 HTTP 429 当业务码）
   必须被判定器抓出来；
7. 业务码与 HTTP 状态不混用：集合不含 HTTP 状态，限流是 `(HTTP 429, code 2004)`；
8. `/health` 仍是裸响应（Task 1.4 验收项，注册处理器后 MUST NOT 回归）。

探针路由由夹具挂到用例自己的 `create_app()` 实例上，生产代码不含任何调试端点。

**为什么单独测框架 `HTTPException`**：FastAPI 构造时已经为 `starlette.exceptions.HTTPException`
这个键预注册了它的 `http_exception_handler`，回的是 `{"detail": …}`（**没有 `code` 字段**的第三种
响应形状）；而 Starlette 路由层在未匹配路径（404）与方法不允许（405）时抛的正是这个基类实例。
这些响应在业务代码之外产生，调用点无法拦截，故只能在这里正面钉住。
"""

from __future__ import annotations

import itertools
import logging
import re
import traceback
from collections.abc import Callable, Collection, Iterable, Iterator, Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any, Literal

import httpx
import pytest
import yaml
from fastapi import FastAPI, Query
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field, ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from aicore.core.errors import (
    AICORE_ERROR_CODES,
    DEFAULT_MESSAGES,
    HTTP_EXCEPTION_5XX_FALLBACK_CODE,
    HTTP_EXCEPTION_SUB_5XX_FALLBACK_CODE,
    HTTP_STATUS_BY_ERROR_CODE,
    HTTP_STATUS_BY_HTTP_EXCEPTION_STATUS,
    INTERNAL_ERROR_CODE,
    PARAM_ERROR_CODES,
    ROUTE_NOT_FOUND_MESSAGE,
    AiCoreError,
    ChannelFailureError,
    DependencyTimeoutError,
    ForbiddenError,
    NotFoundError,
    ParamError,
    RateLimitedError,
    UnauthorizedError,
    _handle_ai_core_error,
    _handle_http_exception,
    _handle_request_validation_error,
    _handle_unexpected_error,
    _http_exception_info,
    _validation_error_code,
)
from aicore.core.trace import TRACE_ID_HEADER
from aicore.main import create_app

SERVICE_ROOT = Path(__file__).resolve().parents[2]
#: 平台错误码单一事实源：`services/_common/openapi.yaml`（各服务文档 $ref 引用它，勿内联）。
PLATFORM_OPENAPI = SERVICE_ROOT.parent / "_common" / "openapi.yaml"

#: 信封的四个必填字段 + 可选的 `data`（失败时为 null）。
REQUIRED_ENVELOPE_KEYS = frozenset({"code", "message", "traceId", "timestamp"})
ENVELOPE_KEYS = REQUIRED_ENVELOPE_KEYS | {"data"}

#: `_common` 的示例值，同时也是合法的 16 位 hex 注入值。
INJECTED_TRACE_ID = "3f2a1b9c8d7e6f50"
TRACE_ID_PATTERN = re.compile(r"^[0-9a-f]{16}$")
ISO8601_UTC_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")

#: 未预期异常的原始消息：故意长得像内部细节（模块路径 + 类名），
#: 一旦被写进响应体，泄漏断言立刻变红。
UNEXPECTED_ERROR_MESSAGE = "测试：模块路径 src/aicore/core/errors.py 的 RuntimeError"


# ---------------------------------------------------------------------------
# 平台表读取与判定器
# ---------------------------------------------------------------------------


def read_platform_error_codes() -> frozenset[int]:
    """读 `_common/openapi.yaml` 的 `ErrorCode` 枚举（平台错误码单一事实源）。"""
    document = yaml.safe_load(PLATFORM_OPENAPI.read_text(encoding="utf-8"))
    enum_values = document["components"]["schemas"]["ErrorCode"]["enum"]
    return frozenset(int(value) for value in enum_values)


def codes_outside_platform_table(
    codes: Iterable[int], platform_codes: Collection[int]
) -> tuple[int, ...]:
    """返回 `codes` 里不在平台枚举内的码值（升序）。

    本函数就是「业务码只能取平台表内的值」这条红线的判定器，参数化出 `platform_codes`
    便于直接喂一个「凭空加进来的码」来自证判别力（阴性方向）。
    """
    return tuple(sorted({code for code in codes if code not in platform_codes}))


# ---------------------------------------------------------------------------
# 夹具与探针路由（只在用例里存在）
# ---------------------------------------------------------------------------


@pytest.fixture
def raising_route(app: FastAPI) -> Callable[[BaseException], str]:
    """登记一条「抛出指定异常」的测试专用路由，返回它的路径。

    路由挂到用例自己的 app 实例上：生产代码不含任何探针 / 调试端点。
    """
    counter = itertools.count()

    def _register(exc: BaseException) -> str:
        path = f"/__test__/raise-{next(counter)}"

        async def _raise() -> None:
            raise exc

        app.add_api_route(path, _raise, methods=["GET"], include_in_schema=False)
        return path

    return _register


@pytest.fixture
def error_client(app: FastAPI) -> Iterator[TestClient]:
    """不把服务端异常抛回用例的客户端：未预期异常要断言的是**响应体**，不是异常本身。"""
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def http_exception_route(app: FastAPI) -> Callable[..., str]:
    """登记一条「抛出框架 `HTTPException`」的测试专用路由，返回它的路径。

    模拟的是业务代码之外的框架路径：`HTTPBearer` 之类的依赖内部抛 401/403，
    调用点无法拦截（`HTTPBearer` 真实抛的是基类 `starlette.exceptions.HTTPException`，
    且带 `WWW-Authenticate: Bearer` 头）。`detail` 刻意可定制，用来证明响应体不回显框架文案；
    `headers` 可选，用来证明 `exc.headers` 在**有体与无体两条路径**上都被原样透传。
    """
    counter = itertools.count()

    def _register(status_code: int, detail: str, headers: Mapping[str, str] | None = None) -> str:
        path = f"/__test__/http-exc-{next(counter)}"

        async def _raise() -> None:
            merged = dict(headers or {})
            if status_code == 401:
                merged.setdefault("WWW-Authenticate", "Bearer")
            raise StarletteHTTPException(
                status_code=status_code,
                detail=detail,
                headers=merged or None,
            )

        app.add_api_route(path, _raise, methods=["GET"], include_in_schema=False)
        return path

    return _register


@pytest.fixture
def validation_client(app: FastAPI, client: TestClient) -> TestClient:
    """带参数校验探针路由的客户端：用真实的 FastAPI 校验链路触发 422。

    四类失败来源各留一个入口：缺参（missing）、整数解析失败（int_parsing）、
    字面量不在允许集合（literal_error）、超出上界（less_than_equal）。
    """

    @app.get("/__test__/validate", include_in_schema=False)
    async def _validate(
        name: str,
        limit: Annotated[int, Query(ge=1, le=10)],
        mode: Literal["fast", "slow"],
    ) -> dict[str, str]:
        return {"name": name, "limit": str(limit), "mode": mode}

    return client


# ---------------------------------------------------------------------------
# 1. 异常类 → 业务码
# ---------------------------------------------------------------------------


def test_base_error_defaults_to_internal_error_code() -> None:
    """基类缺省码是 5000（内部错误）：派生类没声明码值时按「不猜业务语义」处理。"""
    assert AiCoreError().code == 5000
    assert issubclass(AiCoreError, Exception)


@pytest.mark.parametrize(
    ("error_class", "expected_code"),
    [
        pytest.param(UnauthorizedError, 2001, id="UnauthorizedError"),
        pytest.param(ForbiddenError, 2002, id="ForbiddenError"),
        pytest.param(RateLimitedError, 2004, id="RateLimitedError"),
        pytest.param(NotFoundError, 3006, id="NotFoundError"),
        pytest.param(ChannelFailureError, 4003, id="ChannelFailureError"),
        pytest.param(DependencyTimeoutError, 5002, id="DependencyTimeoutError"),
    ],
)
def test_exception_class_carries_expected_business_code(
    error_class: type[AiCoreError], expected_code: int
) -> None:
    """每个异常类自带业务码；断言用字面量，避免与实现里的常量互相印证。"""
    assert error_class.code == expected_code
    assert error_class().code == expected_code


def test_exception_message_defaults_and_override() -> None:
    """缺省文案随码值走（取自平台文案表）；调用方可覆盖文案，但改不了码。"""
    assert ForbiddenError().message == DEFAULT_MESSAGES[2002]
    exc = ForbiddenError("测试：该资源属于其他账号")
    assert (exc.code, exc.message, str(exc)) == (
        2002,
        "测试：该资源属于其他账号",
        "测试：该资源属于其他账号",
    )


def test_param_error_carries_the_three_param_codes() -> None:
    """`ParamError` 的形状：三档共用一个类，档位由 `code` 指定，缺省 1002（格式）。"""
    assert ParamError().code == 1002
    assert ParamError(code=1001).code == 1001
    assert ParamError(code=1002).code == 1002
    assert ParamError(code=1003).code == 1003
    # 文案随最终码值走：缺参档的缺省文案是「参数缺失」，不是构造时的 1002 文案。
    assert ParamError(code=1001).message == DEFAULT_MESSAGES[1001]
    assert ParamError("测试：自定义文案", code=1003).message == "测试：自定义文案"


@pytest.mark.parametrize("code", [0, 2001, 3006, 429, 9999])
def test_param_error_rejects_codes_outside_the_param_family(code: int) -> None:
    """跨段的码（含成功码 0、HTTP 429）在构造期即被拒绝，MUST NOT 落到响应体。"""
    with pytest.raises(ValueError):
        ParamError("测试：非法档位", code=code)


def test_base_error_rejects_code_outside_the_platform_table() -> None:
    """派生类写错码值必须立刻炸在构造期，而不是把枚举外的码送到前端。"""

    class _OutOfTableError(AiCoreError):
        code = 9999

    with pytest.raises(ValueError, match="9999"):
        _OutOfTableError()


# ---------------------------------------------------------------------------
# 2. 业务异常 → 信封 + HTTP 状态（真实 HTTP 链路）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("exc", "expected_code", "expected_status"),
    [
        pytest.param(ParamError("测试：缺参", code=1001), 1001, 400, id="param-missing-1001"),
        pytest.param(ParamError("测试：格式", code=1002), 1002, 400, id="param-format-1002"),
        pytest.param(ParamError("测试：范围", code=1003), 1003, 400, id="param-value-1003"),
        pytest.param(ParamError("测试：缺省档"), 1002, 400, id="param-default-1002"),
        pytest.param(UnauthorizedError(), 2001, 401, id="unauthorized-2001"),
        pytest.param(ForbiddenError(), 2002, 403, id="forbidden-2002"),
        pytest.param(RateLimitedError(), 2004, 429, id="rate-limited-2004"),
        pytest.param(NotFoundError(), 3006, 404, id="not-found-3006"),
        pytest.param(ChannelFailureError(), 4003, 502, id="channel-failure-4003"),
        pytest.param(DependencyTimeoutError(), 5002, 504, id="dependency-timeout-5002"),
    ],
)
def test_business_exception_maps_to_envelope(
    client: TestClient,
    raising_route: Callable[[BaseException], str],
    exc: AiCoreError,
    expected_code: int,
    expected_status: int,
) -> None:
    """业务异常 → 业务码 + HTTP 状态 + 信封。

    用 conftest 的 `client`（raise_server_exceptions 默认 True）：异常若逃逸出应用，
    用例会直接炸而不是拿到响应 —— 这正面证明业务异常被处理器完全吸收。
    """
    response = client.get(raising_route(exc))
    body = response.json()

    assert response.status_code == expected_status
    assert body["code"] == expected_code
    assert body["message"] == exc.message
    assert set(body) == ENVELOPE_KEYS
    assert body["data"] is None
    # 业务码与 HTTP 状态是两个维度：这里逐例证明两者没有被混用。
    assert body["code"] != response.status_code
    assert response.headers["content-type"].startswith("application/json")


def test_rate_limited_is_business_code_2004_under_http_429(
    client: TestClient, raising_route: Callable[[BaseException], str]
) -> None:
    """`429` 是 HTTP 状态、业务码是 `2004` —— 前端按 `code` 判断，两者必须同时出现。"""
    response = client.get(raising_route(RateLimitedError()))
    assert response.status_code == 429
    assert response.json()["code"] == 2004
    assert 429 not in AICORE_ERROR_CODES


def test_trace_id_comes_from_request_header(
    client: TestClient, raising_route: Callable[[BaseException], str]
) -> None:
    """信封 traceId 取自请求头 `X-Request-Id`（不另造来源），并由中间件原值回显。"""
    response = client.get(
        raising_route(NotFoundError()), headers={TRACE_ID_HEADER: INJECTED_TRACE_ID}
    )
    assert response.json()["traceId"] == INJECTED_TRACE_ID
    assert response.headers[TRACE_ID_HEADER] == INJECTED_TRACE_ID


def test_trace_id_is_generated_when_header_is_absent(
    client: TestClient, raising_route: Callable[[BaseException], str]
) -> None:
    """头缺失时信封仍要有可用 traceId（16 位小写 hex），不能是空串。"""
    body = client.get(raising_route(NotFoundError())).json()
    assert TRACE_ID_PATTERN.fullmatch(body["traceId"])


def test_timestamp_is_iso8601_utc_within_the_request_window(
    client: TestClient, raising_route: Callable[[BaseException], str]
) -> None:
    """`timestamp` 是 UTC ISO 8601（`Z` 结尾），且落在本次请求的时间窗内。"""
    before = datetime.now(UTC)
    timestamp = client.get(raising_route(NotFoundError())).json()["timestamp"]
    after = datetime.now(UTC)

    assert ISO8601_UTC_PATTERN.fullmatch(timestamp), timestamp
    parsed = datetime.fromisoformat(timestamp)
    assert parsed.utcoffset() == timedelta(0)
    assert before <= parsed <= after


def test_health_stays_bare_after_handlers_are_registered(client: TestClient) -> None:
    """`/health` MUST NOT 被信封包裹（Task 1.4 验收项；注册处理器不得让它回归）。"""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert set(response.json()).isdisjoint(ENVELOPE_KEYS)


def test_create_app_registers_the_four_handlers() -> None:
    """组合根必须真的接线四条路径：业务异常 / 框架校验 / 框架 HTTPException / 未预期异常。

    **断言处理器身份而不是键存在**：FastAPI 在构造 `FastAPI()` 时就预注册了
    `RequestValidationError` 与 `starlette.exceptions.HTTPException` 的**默认**处理器
    （`request_validation_exception_handler` / `http_exception_handler`），故「键存在」对这两条
    路径恒真、没有判别力——把 `register_exception_handlers()` 的对应一行删掉，用例照样全绿。
    比对象身份才能让「接线」这件事真的可判：删掉注册行，字典里的值退回 FastAPI 的默认函数，
    本用例立刻变红。

    另注意：FastAPI 注册 `HTTPException` 时用的键就是 `starlette.exceptions.HTTPException`
    （实测 `fastapi.HTTPException is starlette.exceptions.HTTPException` 为 **False**，
    但预注册的键是基类），故本模块的那一行是**覆盖**默认处理器而非并存——这正是想要的：
    同一个键不可能既回 `{"detail": …}` 又回信封。
    """
    handlers = create_app().exception_handlers
    assert handlers[AiCoreError] is _handle_ai_core_error
    assert handlers[RequestValidationError] is _handle_request_validation_error
    assert handlers[StarletteHTTPException] is _handle_http_exception
    assert handlers[Exception] is _handle_unexpected_error


# ---------------------------------------------------------------------------
# 2.5 框架 HTTPException 被收编（Starlette 基类：路由 404/405 与 HTTPBearer 的 401/403）
# ---------------------------------------------------------------------------

#: 框架 `detail` 的哨兵值：一旦被回显进响应体，「不回显 detail」的断言立刻变红。
FRAMEWORK_DETAIL_SENTINEL = "FRAMEWORK_DETAIL_MUST_NOT_LEAK"

#: 框架默认响应体的固定片段：路由 404/405 的 `{"detail": "Not Found"}` /
#: `{"detail": "Method Not Allowed"}` 与 `HTTPBearer` 的 `"Not authenticated"` /
#: `"Not enough permissions"` 都在此列。
FRAMEWORK_DEFAULT_DETAILS = (
    "Not Found",
    "Method Not Allowed",
    "Not authenticated",
    "Not enough permissions",
)


def assert_enveloped(
    response: httpx.Response, expected_status: int, expected_code: int, expected_message: str
) -> dict[str, Any]:
    """断言一条响应已完全信封化：状态 + 业务码 + 四键齐全 + 无 `detail` + 无框架文案。

    被框架 `HTTPException` 的用例共用：它们的共同点正是「响应体里不许留下框架痕迹」。
    """
    body: dict[str, Any] = response.json()
    assert response.status_code == expected_status
    assert set(body) == ENVELOPE_KEYS, f"信封键集合不符：{sorted(body)}"
    assert body["code"] == expected_code
    assert body["code"] != response.status_code, "业务码 MUST NOT 等于 HTTP 状态"
    assert body["data"] is None
    assert body["message"] == expected_message
    assert "detail" not in body
    # traceId / timestamp 的保证与其余路径一致。
    assert TRACE_ID_PATTERN.fullmatch(body["traceId"])
    assert ISO8601_UTC_PATTERN.fullmatch(body["timestamp"])
    assert response.headers["content-type"].startswith("application/json")
    for leaked in (*FRAMEWORK_DEFAULT_DETAILS, FRAMEWORK_DETAIL_SENTINEL):
        assert leaked not in response.text, f"响应体回显了框架文案：{leaked}"
    return body


def test_unmatched_route_is_enveloped_as_route_not_found(client: TestClient) -> None:
    """未匹配路由 → HTTP 404 + `code=3006` + 与业务「对象不存在」**不同**的文案。

    `3006` 的配对是控制者锁定的；但不存在的是**接口**而不是对象，故文案必须是「接口不存在」，
    否则排障时分不清「路径写错」与「查无此对象」。
    """
    body = assert_enveloped(
        client.get("/__test__/no-such-route"), 404, 3006, ROUTE_NOT_FOUND_MESSAGE
    )

    assert body["message"] != DEFAULT_MESSAGES[3006], (
        "路由 404 与业务 NotFoundError 的文案必须可区分"
    )
    # 文案不是框架的 `detail`（`{"detail": "Not Found"}` 的形状已被彻底替换）。
    assert body["message"] != "Not Found"


def test_disallowed_method_is_enveloped(client: TestClient, app: FastAPI) -> None:
    """方法不允许 → HTTP 405 + `code=1001`（兜底），信封形状与其余路径一致。

    405 在平台表里**没有**对应码，控制者的口径是「留在平台表内、用未匹配 4xx 的兜底 `1001`」，
    不为它发明新码——故这里正面钉住 `1001`，防止后人「顺手加个 405 专用码」。
    """

    @app.get("/__test__/method-probe", include_in_schema=False)
    async def _probe() -> dict[str, str]:
        return {"ok": "yes"}

    body = assert_enveloped(
        client.post("/__test__/method-probe"), 405, 1001, DEFAULT_MESSAGES[1001]
    )
    assert body["message"] != "Method Not Allowed"


@pytest.mark.parametrize(
    ("status_code", "expected_code", "reason"),
    [
        pytest.param(401, 2001, "锁定对：HTTPBearer 未带凭据", id="unauthorized-401"),
        pytest.param(403, 2002, "锁定对：HTTPBearer 权限不足", id="forbidden-403"),
        pytest.param(503, 5000, "未列入锁定对的 5xx → 兜底 5000", id="unmatched-5xx-503"),
    ],
)
def test_framework_http_exception_is_enveloped_with_platform_message(
    client: TestClient,
    http_exception_route: Callable[[int, str], str],
    status_code: int,
    expected_code: int,
    reason: str,
) -> None:
    """框架 `HTTPException` → 原 HTTP 状态 + 平台业务码 + **平台文案**（不是框架 `detail`）。

    这三个状态都来自业务代码之外：401/403 是 `HTTPBearer` 之类的依赖内部抛的（调用点拦不住），
    503 代表任何未列入锁定对的 5xx。响应体里只允许出现平台文案 —— `detail` 是给开发者看的，
    平台文案才是评审过、可直接展示给用户的那一份。
    """
    path = http_exception_route(status_code, FRAMEWORK_DETAIL_SENTINEL)
    body = assert_enveloped(
        client.get(path), status_code, expected_code, DEFAULT_MESSAGES[expected_code]
    )
    assert FRAMEWORK_DETAIL_SENTINEL not in body["message"], reason


def test_framework_http_exception_keeps_trace_id_from_request_header(
    client: TestClient, http_exception_route: Callable[[int, str], str]
) -> None:
    """框架 `HTTPException` 的信封同样取网关注入的 traceId（不另造来源）。"""
    path = http_exception_route(401, "Not authenticated")
    response = client.get(path, headers={TRACE_ID_HEADER: INJECTED_TRACE_ID})
    assert response.json()["traceId"] == INJECTED_TRACE_ID
    assert response.headers[TRACE_ID_HEADER] == INJECTED_TRACE_ID


def test_framework_http_exception_keeps_its_headers(
    client: TestClient, http_exception_route: Callable[[int, str], str]
) -> None:
    """`exc.headers` 原样透传：收编响应体 MUST NOT 顺手丢掉协议头。

    `HTTPBearer` 的 401 带 `WWW-Authenticate: Bearer`，FastAPI 的默认处理器同样透传它；
    丢掉这个头客户端就不知道该怎么补凭据。
    """
    response = client.get(http_exception_route(401, "Not authenticated"))
    assert response.headers.get("WWW-Authenticate") == "Bearer"
    assert response.status_code == 401


def test_http_exception_status_mapping_is_exactly_the_locked_pairs() -> None:
    """状态 → 码的映射用**字面量**钉住（避免表与断言互相印证），并钉住两个兜底码。

    只测 401/403/503 三条状态的话，锁定对里的 404/429/500/502/504 一旦被改动就没有用例会红。
    这里把整张表与两个兜底常量一起钉住：新增/删除锁定对必须同时改本用例，评审才有落点。
    """
    assert dict(HTTP_STATUS_BY_HTTP_EXCEPTION_STATUS) == {
        401: 2001,
        403: 2002,
        404: 3006,
        429: 2004,
        500: 5000,
        502: 4003,
        504: 5002,
    }
    # 表里的值只能是业务码，键只能是 HTTP 状态（两个维度 MUST NOT 互相代入）。
    assert set(HTTP_STATUS_BY_HTTP_EXCEPTION_STATUS.values()) <= AICORE_ERROR_CODES
    assert all(400 <= status < 600 for status in HTTP_STATUS_BY_HTTP_EXCEPTION_STATUS)
    # 兜底码必须在平台表内：405 之类没有专属码的状态只能落到这里，不许发明新码。
    assert HTTP_EXCEPTION_SUB_5XX_FALLBACK_CODE == 1001
    assert HTTP_EXCEPTION_5XX_FALLBACK_CODE == 5000
    assert {HTTP_EXCEPTION_SUB_5XX_FALLBACK_CODE, HTTP_EXCEPTION_5XX_FALLBACK_CODE} <= (
        AICORE_ERROR_CODES
    )


#: 框架契约下**不允许响应体**的状态（`fastapi.utils.is_body_allowed_for_status_code` 的判据：
#: `< 200` 与 `204` / `205` / `304`）。表驱动，新增状态时只改这一处。
BODILESS_HTTP_STATUSES = (204, 205, 304)

#: 无体用例透传的协议头：证明 `exc.headers` 在有体与无体两条路径上都不丢。
BODILESS_HEADERS = {"ETag": '"v1"', "Cache-Control": "no-store"}


@pytest.mark.parametrize("status_code", BODILESS_HTTP_STATUSES)
def test_bodiless_status_is_returned_without_a_body(
    client: TestClient,
    http_exception_route: Callable[..., str],
    status_code: int,
) -> None:
    """无体状态 → **无体**响应，且 `exc.headers` 仍在（镜像框架默认处理器的契约）。

    FastAPI 的默认 `http_exception_handler` 对这些状态回的是 `Response(status_code=…)`：
    `204`/`205`/`304` 按 HTTP 契约 MUST NOT 带响应体。收编响应体若一律回 `JSONResponse`，
    就会造出「204 带 `application/json` 与一个信封体」的畸形响应——比不收编更糟。
    """
    path = http_exception_route(status_code, FRAMEWORK_DETAIL_SENTINEL, dict(BODILESS_HEADERS))
    response = client.get(path, follow_redirects=False)

    assert response.status_code == status_code
    # 无体：既没有 body，也没有 `application/json`（框架默认处理器连 `content-type` 都不带）。
    assert response.content == b""
    assert response.text == ""
    assert "content-type" not in response.headers
    assert FRAMEWORK_DETAIL_SENTINEL not in response.text
    # `exc.headers` 在无体路径上同样原样透传（`WWW-Authenticate` 之外的头也不许丢）。
    for name, value in BODILESS_HEADERS.items():
        assert response.headers[name] == value


def test_sub_400_status_is_enveloped_without_the_internal_error_code(
    client: TestClient, http_exception_route: Callable[..., str]
) -> None:
    """sub-400 状态（这里取响应体允许的 `302`）走真实链路：**不是** `5000`。

    sub-400 状态不是服务端故障，落 5xx 兜底会送出「内部错误」假信号。用 `302` 而不是
    `204`/`304`：只有它允许响应体，`code` 才真的能被断言到（无体状态的码只进日志）。
    """
    path = http_exception_route(302, FRAMEWORK_DETAIL_SENTINEL, {"Location": "/health"})
    response = client.get(path, follow_redirects=False)

    body = assert_enveloped(
        response,
        302,
        HTTP_EXCEPTION_SUB_5XX_FALLBACK_CODE,
        DEFAULT_MESSAGES[HTTP_EXCEPTION_SUB_5XX_FALLBACK_CODE],
    )
    assert body["code"] != INTERNAL_ERROR_CODE
    assert response.headers["Location"] == "/health"


@pytest.mark.parametrize("status_code", [*BODILESS_HTTP_STATUSES, 100, 200, 302])
def test_sub_400_status_never_maps_to_the_internal_error_code(status_code: int) -> None:
    """`_http_exception_info` 对 sub-400 一律不落 `5000`，且码必须仍在平台表内。

    `204`/`304` 的码进不了响应体（无体），只能在这个层级钉住；`100` 是框架理论上会抛的
    1xx，`200`/`302` 代表响应体允许的 sub-400。三者一起把「`< 500` 走客户端侧兜底」这条
    分段判据的正反两面钉死：只要有人把判据改回「落在 4xx 段」，本用例立刻变红。
    """
    info = _http_exception_info(status_code)
    assert info.status_code == status_code
    assert info.code != INTERNAL_ERROR_CODE, "sub-400 不是服务端故障，MUST NOT 落 5000"
    assert info.code == HTTP_EXCEPTION_SUB_5XX_FALLBACK_CODE
    assert info.code in AICORE_ERROR_CODES
    assert info.message == DEFAULT_MESSAGES[info.code]


# ---------------------------------------------------------------------------
# 3. FastAPI 默认 422 被收编
# ---------------------------------------------------------------------------


def test_validation_probe_route_accepts_valid_params(validation_client: TestClient) -> None:
    """探针路由本身可用：下面的 1xxx 确实来自参数校验，而不是路由写错。"""
    response = validation_client.get("/__test__/validate?name=x&limit=5&mode=fast")
    assert response.status_code == 200
    assert response.json() == {"name": "x", "limit": "5", "mode": "fast"}


@pytest.mark.parametrize(
    ("query", "expected_code", "reason"),
    [
        pytest.param("", 1001, "三个必填项全缺", id="all-missing"),
        pytest.param("?limit=5&mode=fast", 1001, "缺 name", id="one-missing"),
        pytest.param("?name=x&limit=abc&mode=fast", 1002, "整数解析失败", id="int-parsing"),
        pytest.param("?name=x&limit=5&mode=nope", 1003, "字面量不在允许集合", id="literal"),
        pytest.param("?name=x&limit=99&mode=fast", 1003, "超出上界 le=10", id="range"),
        pytest.param(
            "?name=x&limit=abc&mode=nope",
            1003,
            "枚举优先于格式（同级多错只回一个码）",
            id="enum-beats-format",
        ),
        pytest.param(
            "?limit=99&mode=nope",
            1001,
            "缺失优先于枚举或范围",
            id="missing-beats-enum",
        ),
    ],
)
def test_request_validation_error_is_absorbed_into_envelope(
    validation_client: TestClient, query: str, expected_code: int, reason: str
) -> None:
    """框架 422 → 平台信封：HTTP 状态保留 422，响应体换成 1xxx 信封（无 `detail`）。"""
    response = validation_client.get(f"/__test__/validate{query}")
    body = response.json()

    assert response.status_code == 422, reason
    assert set(body) >= REQUIRED_ENVELOPE_KEYS, reason
    assert set(body) == ENVELOPE_KEYS, reason
    assert body["code"] == expected_code, reason
    assert body["code"] != response.status_code, "业务码 MUST NOT 等于 HTTP 状态"
    assert body["data"] is None
    assert body["message"] == DEFAULT_MESSAGES[expected_code]
    # 不回显框架结构，也不回显字段名 / pydantic 文案。
    assert "detail" not in body
    for leaked in ("detail", "Field required", "Input should be", "limit", "mode", "name"):
        assert leaked not in response.text, f"响应体回显了框架内部信息：{leaked}"


def test_validation_log_keeps_types_but_not_user_input(
    validation_client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    """日志只记 type/loc：pydantic error dict 里的 `input`（用户原值）MUST NOT 进日志。"""
    with caplog.at_level(logging.INFO, logger="aicore.core.errors"):
        response = validation_client.get(
            "/__test__/validate?name=test_secret_value&limit=abc&mode=fast"
        )

    assert response.status_code == 422
    assert "test_secret_value" not in caplog.text
    assert "test_secret_value" not in response.text
    assert "int_parsing" in caplog.text  # 可排障信息保留


@pytest.mark.parametrize(
    ("error_type", "expected_code"),
    [
        pytest.param("missing", 1001, id="missing"),
        pytest.param("enum", 1003, id="enum"),
        pytest.param("literal_error", 1003, id="literal_error"),
        pytest.param("greater_than", 1003, id="greater_than"),
        pytest.param("greater_than_equal", 1003, id="greater_than_equal"),
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
        # Decimal 位数约束（M3 评审项）：与数值/长度范围同类，归 1003 而不是落 1002 兜底。
        pytest.param("decimal_max_digits", 1003, id="decimal_max_digits"),
        pytest.param("decimal_max_places", 1003, id="decimal_max_places"),
        pytest.param("decimal_whole_digits", 1003, id="decimal_whole_digits"),
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

    `unknown-type-falls-back` 是兜底档的守门用例：pydantic 新增 type 时归 1002，
    MUST NOT 漏成 5000。
    """
    assert _validation_error_code([{"type": error_type, "loc": ("query", "x")}]) == expected_code


def test_validation_error_code_priority() -> None:
    """多个错误同时命中时的优先级：缺失 > 枚举或范围 > 格式。"""
    mixed = [{"type": "int_parsing"}, {"type": "literal_error"}, {"type": "missing"}]
    assert _validation_error_code(mixed) == 1001
    assert _validation_error_code([{"type": "int_parsing"}, {"type": "literal_error"}]) == 1003
    assert _validation_error_code([{"type": "int_parsing"}]) == 1002
    assert _validation_error_code([]) == 1002


def test_decimal_digit_constraints_are_real_pydantic_types() -> None:
    """M3 评审项的**行为证据**：Decimal 位数约束真的由 pydantic 发出这些 type，且归 `1003`。

    分类表（`test_validation_error_type_mapping`）用字面量钉住映射，但字面量写错名字也不会红；
    这里补上行为证据：真造 pydantic 校验错误、取它实际发出的 `type` 再喂给分类器。
    （实测 pydantic 2.13.5：`max_digits` → `decimal_max_digits`、`decimal_places` →
    `decimal_max_places`；`decimal_whole_digits` 用常规 `Field` 约束触发不到，故只在上表里
    按范围类收列，以免它一旦出现就落 1002 兜底。）
    """

    class _Amount(BaseModel):
        value: Annotated[Decimal, Field(max_digits=4, decimal_places=2)]

    cases = {"123.45": "decimal_max_digits", "1.234": "decimal_max_places"}
    for raw, expected_type in cases.items():
        with pytest.raises(ValidationError) as exc_info:
            _Amount(value=raw)

        types = [str(item["type"]) for item in exc_info.value.errors()]
        assert types == [expected_type], (raw, types)
        assert _validation_error_code([{"type": t} for t in types]) == 1003, raw


# ---------------------------------------------------------------------------
# 4. 未预期异常 → 5000，堆栈只进日志
# ---------------------------------------------------------------------------


def test_unexpected_exception_maps_to_5000(
    error_client: TestClient, raising_route: Callable[[BaseException], str]
) -> None:
    """未预期异常 → HTTP 500 + code=5000；信封照样四字段齐全、data=null。"""
    path = raising_route(RuntimeError(UNEXPECTED_ERROR_MESSAGE))
    response = error_client.get(path, headers={TRACE_ID_HEADER: INJECTED_TRACE_ID})
    body = response.json()

    assert response.status_code == 500
    assert body["code"] == 5000
    assert set(body) == ENVELOPE_KEYS
    assert body["data"] is None
    assert body["message"] == DEFAULT_MESSAGES[5000]
    # 500 路径由 ServerErrorMiddleware 渲染，traceId 仍是网关注入值（中间件在最外层）。
    assert body["traceId"] == INJECTED_TRACE_ID


def test_unexpected_exception_body_leaks_no_internals(
    error_client: TestClient, raising_route: Callable[[BaseException], str]
) -> None:
    """响应体 MUST NOT 含堆栈、文件路径、模块名，也不含原始异常消息。"""
    path = raising_route(RuntimeError(UNEXPECTED_ERROR_MESSAGE))
    response = error_client.get(path)

    for leaked in (
        "Traceback",
        "File ",
        ".py",
        "RuntimeError",
        "aicore",
        "services",
        "测试",  # 原始异常消息里的任意片段
        path,  # 内部路由路径同样不外泄
    ):
        assert leaked not in response.text, f"响应体泄漏了内部细节：{leaked}"


def test_unexpected_exception_traceback_is_logged(
    error_client: TestClient,
    raising_route: Callable[[BaseException], str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """堆栈必须进日志（只进日志）：ERROR 记录带完整 traceback，且指向真实抛出点。"""
    path = raising_route(RuntimeError(UNEXPECTED_ERROR_MESSAGE))
    with caplog.at_level(logging.ERROR, logger="aicore.core.errors"):
        error_client.get(path, headers={TRACE_ID_HEADER: INJECTED_TRACE_ID})

    records = [
        record
        for record in caplog.records
        if record.name == "aicore.core.errors" and record.levelno == logging.ERROR
    ]
    assert len(records) == 1, "未预期异常没有留下 ERROR 日志"
    record = records[0]
    assert record.exc_info is not None, "ERROR 记录未携带异常信息（堆栈丢了）"

    formatted = "".join(traceback.format_exception(*record.exc_info))
    assert "Traceback (most recent call last)" in formatted
    assert UNEXPECTED_ERROR_MESSAGE in formatted
    assert "test_errors.py" in formatted, "堆栈没有指向真实抛出点"
    assert INJECTED_TRACE_ID in record.getMessage()


# ---------------------------------------------------------------------------
# 5. 错误码与平台表比对（含阴性方向）
# ---------------------------------------------------------------------------


def test_platform_enum_is_readable_and_not_vacuous() -> None:
    """比对用例的前提：平台表读得到，且不是空集（否则任何比对都会静默通过）。"""
    assert PLATFORM_OPENAPI.is_file(), PLATFORM_OPENAPI
    platform_codes = read_platform_error_codes()
    assert {0, 1001, 1002, 1003, 2004, 3007, 5000, 5002, 5003} <= platform_codes
    assert len(platform_codes) >= 25, f"平台枚举只读到 {len(platform_codes)} 个码值，解析可能失效"


def test_aicore_error_codes_all_exist_in_the_platform_enum() -> None:
    """正向：本服务发出的每个码都在平台 `ErrorCode` 枚举内。"""
    assert codes_outside_platform_table(AICORE_ERROR_CODES, read_platform_error_codes()) == ()


def test_codes_outside_the_platform_table_are_detected() -> None:
    """阴性方向：凭空加进来的码必须被判定器抓出来，比对用例才有判别力。

    同时覆盖两类典型误写：自造的码值，以及把 HTTP 状态（429 / 400）当业务码写进来。
    """
    platform_codes = read_platform_error_codes()
    assert codes_outside_platform_table({*AICORE_ERROR_CODES, 9999}, platform_codes) == (9999,)
    assert codes_outside_platform_table({*AICORE_ERROR_CODES, 429}, platform_codes) == (429,)
    assert codes_outside_platform_table({*AICORE_ERROR_CODES, 400}, platform_codes) == (400,)
    assert codes_outside_platform_table({429, 400}, platform_codes) == (400, 429)


def test_aicore_error_codes_is_exactly_the_emittable_set() -> None:
    """集合与「本服务确实会发出的码」逐项一致：多了是死码，少了会漏成 5000。"""
    emittable = {
        1001,
        1002,
        1003,  # ParamError 三档
        2001,
        2002,
        2004,
        3006,
        4003,
        5000,  # 未预期异常的兜底码
        5002,
    }
    assert sorted(AICORE_ERROR_CODES) == sorted(emittable)
    assert isinstance(AICORE_ERROR_CODES, frozenset)
    # 成功码与 HTTP 状态码 MUST NOT 混进业务码集合。
    assert 0 not in AICORE_ERROR_CODES
    assert AICORE_ERROR_CODES.isdisjoint({400, 401, 403, 404, 422, 429, 500, 502, 504})


def test_every_exception_class_code_is_in_the_set() -> None:
    """异常类携带的码不得游离于集合之外（集合是 Task 2.4 与比对用例的输入）。"""
    for error_class in (
        ParamError,
        UnauthorizedError,
        ForbiddenError,
        RateLimitedError,
        NotFoundError,
        ChannelFailureError,
        DependencyTimeoutError,
    ):
        assert error_class.code in AICORE_ERROR_CODES, error_class.__name__
    assert AiCoreError.code == 5000
    assert sorted(PARAM_ERROR_CODES) == [1001, 1002, 1003]


def test_default_messages_cover_exactly_the_emittable_codes() -> None:
    """每个码都必须有面向用户的缺省文案（缺文案会在渲染信封时炸成 500）。"""
    assert set(DEFAULT_MESSAGES) == AICORE_ERROR_CODES
    assert all(message.strip() for message in DEFAULT_MESSAGES.values())


def test_http_status_table_matches_the_locked_platform_mapping() -> None:
    """码值 → HTTP 状态由控制者锁定：用字面量钉住，避免表与断言互相印证。"""
    assert dict(HTTP_STATUS_BY_ERROR_CODE) == {
        1001: 400,
        1002: 400,
        1003: 400,
        2001: 401,
        2002: 403,
        2004: 429,
        3006: 404,
        4003: 502,
        5000: 500,
        5002: 504,
    }
    assert set(HTTP_STATUS_BY_ERROR_CODE) == AICORE_ERROR_CODES
