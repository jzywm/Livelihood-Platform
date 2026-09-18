"""异常层次与错误码映射用例（Task 2.3）。

覆盖点（全部跑真实 HTTP 链路，只有校验分类器是直接调函数）：

1. 每个异常类 → 业务码 + HTTP 状态（含 `ParamError` 三档与缺省档）；
2. 信封形状：四必填字段 `code` / `message` / `traceId` / `timestamp` 加可选的 `data`，
   失败时 `data=null`；`timestamp` 为 UTC ISO 8601；`traceId` 取自请求头 `X-Request-Id`
   （缺失时生成 16 位小写 hex）；
3. FastAPI 默认 422 + `{"detail": [...]}` 被收编成信封（1xxx），响应体里不留框架结构；
4. 未预期异常 → HTTP 500 + `code=5000`，响应体不含堆栈 / 文件路径 / 模块名 / 原始异常消息，
   而**堆栈确实进了日志**（caplog 里取到带 traceback 的 ERROR 记录）；
5. `AICORE_ERROR_CODES` 与平台单一事实源 `services/_common/openapi.yaml` 的 `ErrorCode`
   枚举逐项比对，且**阴性方向**有判别力：凭空加一个枚举外的码（含把 HTTP 429 当业务码）
   必须被判定器抓出来；
6. 业务码与 HTTP 状态不混用：集合不含 HTTP 状态，限流是 `(HTTP 429, code 2004)`；
7. `/health` 仍是裸响应（Task 1.4 验收项，注册处理器后 MUST NOT 回归）。

探针路由由夹具挂到用例自己的 `create_app()` 实例上，生产代码不含任何调试端点。
"""

from __future__ import annotations

import itertools
import logging
import re
import traceback
from collections.abc import Callable, Collection, Iterable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Literal

import pytest
import yaml
from fastapi import FastAPI, Query
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient

from aicore.core.errors import (
    AICORE_ERROR_CODES,
    DEFAULT_MESSAGES,
    HTTP_STATUS_BY_ERROR_CODE,
    PARAM_ERROR_CODES,
    AiCoreError,
    ChannelFailureError,
    DependencyTimeoutError,
    ForbiddenError,
    NotFoundError,
    ParamError,
    RateLimitedError,
    UnauthorizedError,
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


def test_create_app_registers_the_three_handlers() -> None:
    """组合根必须真的接线三条路径：业务异常 / 框架校验 / 未预期异常。"""
    handlers = create_app().exception_handlers
    assert {AiCoreError, RequestValidationError, Exception} <= set(handlers)


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
