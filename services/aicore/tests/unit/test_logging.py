"""结构化 JSON 日志用例（Task 2.6）。

全部驱动**真实**日志链路（真处理器、真 JSON 序列化、真 stdlib 日志器），不 mock 处理器：

1. PDD §8.5.1 L1747 的 12 项必含字段逐字落在真实发出的记录上；同时与字面量集合比对
   —— 实现里的常量被改名/删项时，两边必须同时改，不存在「常量改了就悄悄放过」；
2. `spanId` **存在且恒为空**：`design.md` D9 不接 SkyWalking agent，字段只为 schema 完整，
   调用方显式传入也不放行（防「假装有埋点」）；
3. 输出是「一行一个 JSON 对象」，且 level / message / time 取值正确；
4. `traceId` 与 `traceIdSource` 单一来源于 `core/trace.py`：走真实请求时等于网关注入的
   `X-Request-Id` 且标 `propagated`，无头时自行生成并标 `generated`
   —— 这一对是 Task 2.5 评审遗留项「生成行为需在日志中可区分」的验收证据；
5. stdlib `logging`（Task 2.2 的规则 3 告警走它）被**同一条** JSON 管线收编，schema 一致；
6. 不落敏感信息：`uid` 脱敏（形似证件号的原始值不得出现）、密钥类字段一律打码，
   并有「非密钥字段不被误抹」的阴性对照；
7. 生命周期接线：重复 `configure_logging` 不产生重复处理器 / 不重复输出；启动配置非法时抛
   `ConfigRejected`（不是裸 `ValidationError`）且异常链里没有口令；关闭时刷盘；
   `create_app()` 在 `AICORE_*` 全清空时依然可建实例；
8. **引导配置**（修复轮 1）：进 lifespan 先装一套不依赖配置的 JSON 日志，使「读配置阶段发出的
   第一行日志」也是同一 schema 的 JSON——正式配置随后覆盖它，且两者叠加不重复输出。

用例隔离（本任务把日志配置成**全局**状态，必须自己收拾干净）：自动夹具在每个用例结束后
移除「本用例新挂到 root 的处理器」、还原 root 级别并清 `get_settings()` 缓存，使同一进程内
反复运行不累积处理器、不重复输出。

取值一律 `test_*` / `SENTINEL_*` 占位符，MUST NOT 出现真实凭据；不使用 sleep。
"""

from __future__ import annotations

import json
import logging
import os
import re
import traceback
from collections.abc import Iterator
from datetime import datetime, timedelta
from typing import Any, Final

import pytest
import structlog
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from aicore.core import config as config_module
from aicore.core.config import ConfigRejected, Settings, clear_settings_cache
from aicore.core.logging import (
    BOOTSTRAP_LOG_LEVEL,
    DEFAULT_APP_NAME,
    REQUIRED_LOG_FIELDS,
    SERVICE_NAME,
    bootstrap_logging,
    configure_logging,
    desensitize_uid,
    flush_logging,
    get_logger,
)
from aicore.core.trace import (
    TRACE_ID_HEADER,
    TRACE_SOURCE_FIELD,
    TRACE_SOURCE_GENERATED,
    TRACE_SOURCE_PROPAGATED,
    reset_trace_id,
)
from aicore.main import create_app

#: `core/config.py` 的 stdlib 日志器名（取自模块本身，避免与实现漂移）。
CONFIG_MODULE: Final = config_module.__name__

#: 组合根 lifespan 的 stdlib 日志器名（拒绝启动的那条 ERROR 记录来自它）。
LIFESPAN_MODULE: Final = "aicore.main"

#: 探针模块名：本文件发出的日志都挂在它下面，便于把「第三方库的日志行」滤掉。
PROBE_MODULE: Final = "aicore.__probe__.logging"

#: 探针路由：请求内写一行日志，用于验证 traceId 从请求头走到日志字段。
PROBE_PATH: Final = "/__probe__/logging"

TRACE_ID_PATTERN: Final = re.compile(r"^[0-9a-f]{16}$")

#: `_common` 的示例 traceId，同时也是合法的注入值。
INJECTED_TRACE_ID: Final = "3f2a1b9c8d7e6f50"

#: 形状像 18 位居民身份证号的**测试哨兵**（非真实证件号，校验位无意义）。
CERT_NUMBER_SENTINEL: Final = "110101199003070011"
CERT_NUMBER_MASKED: Final = "110***********0011"

#: 秘密哨兵：任何一条出现在日志输出里都说明脱敏防线失守。
PASSWORD_SENTINEL: Final = "SENTINEL_PASSWORD_DO_NOT_LEAK"
TOKEN_SENTINEL: Final = "SENTINEL_INTERNAL_TOKEN_DO_NOT_LEAK"
CHANNEL_KEY_SENTINEL: Final = "SENTINEL_DEEPSEEK_KEY_DO_NOT_LEAK"
SECRET_SENTINELS: Final = (PASSWORD_SENTINEL, TOKEN_SENTINEL, CHANNEL_KEY_SENTINEL)

#: PDD §8.5.1 L1747 的必含字段**字面量**（不是从实现里的常量派生出来的）。
#: 两边独立写死：实现改常量、或本文件改字面量，都必须有人同时改另一处。
MANDATED_FIELDS_LITERAL: Final = frozenset(
    {
        "time",
        "level",
        "app",
        "service",
        "module",
        "traceId",
        "spanId",
        "uid",
        "bizType",
        "opCode",
        "code",
        "message",
    }
)


def _test_settings(**overrides: object) -> Settings:
    """测试用配置：只给 `test_*` 占位值、不读 `.env`，且默认组合**不触发**规则 3 告警。

    默认走 `dev + deepseek + 占位密钥`：真实通道有密钥即不告警、`provider != mock` 也不告警，
    于是构造本身不会往日志里多写一行（本文件多处断言「捕获到的每一行都是 JSON 且属于本次调用」）。
    """
    base: dict[str, object] = {
        "env": "dev",
        "provider": "deepseek",
        "deepseek_api_key": "test_deepseek_placeholder",
        "mysql_host": "127.0.0.1",
        "mysql_user": "test_user",
        "mysql_password": "test_password",
        "mysql_database": "aicore_test",
        "redis_host": "127.0.0.1",
        "internal_token": "test_internal_token",
        "daily_quota_per_account": 1000,
        "daily_budget_total": 100000,
    }
    base.update(overrides)
    return Settings(_env_file=None, **base)


def _probe_app() -> FastAPI:
    """全新应用 + 探针路由：请求内按业务代码的方式写一行结构化日志。"""
    app = create_app()

    @app.get(PROBE_PATH, include_in_schema=False)
    async def _probe() -> dict[str, str]:
        get_logger(PROBE_MODULE).info(
            "探针：请求内日志",
            bizType="probe",
            opCode="logging.probe",
            code=0,
        )
        return {"ok": "1"}

    return app


@pytest.fixture(autouse=True)
def _isolated_global_logging_state() -> Iterator[None]:
    """用例隔离：本任务改动的是**进程级**日志状态，必须在每个用例后还原。

    ① traceId 上下文（ContextVar 在 pytest 主线程里跨用例存活）；
    ② root 上的处理器：只移除本用例新增的，并还原 root 与服务命名空间的级别；
    ③ `get_settings()` 缓存：用例可能改过环境变量，缓存清掉以免串味。
    """
    root = logging.getLogger()
    service_logger = logging.getLogger(SERVICE_NAME)
    handlers_before = list(root.handlers)
    root_level_before = root.level
    service_level_before = service_logger.level
    reset_trace_id()
    yield
    reset_trace_id()
    for handler in list(root.handlers):
        if handler not in handlers_before:
            root.removeHandler(handler)
            handler.close()
    root.setLevel(root_level_before)
    service_logger.setLevel(service_level_before)
    clear_settings_cache()


@pytest.fixture
def settings() -> Settings:
    return _test_settings()


@pytest.fixture
def probe_logger(settings: Settings) -> structlog.stdlib.BoundLogger:
    """配置好日志后的探针日志器（每次用例都重新配置，互不继承）。"""
    configure_logging(settings)
    return get_logger(PROBE_MODULE)


def _json_records(text: str) -> list[dict[str, Any]]:
    """把捕获到的输出逐行解析成 JSON 对象；**任何一行不是 JSON 都会让用例失败**。"""
    records: list[dict[str, Any]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        parsed = json.loads(line)
        assert isinstance(parsed, dict), f"日志行不是 JSON 对象：{line!r}"
        records.append(parsed)
    return records


def _probe_records(text: str) -> list[dict[str, Any]]:
    """只保留探针模块发出的记录（root 处理器会连带收编 httpx 等第三方日志）。"""
    return [record for record in _json_records(text) if record.get("module") == PROBE_MODULE]


def _assert_every_line_is_json(text: str) -> list[dict[str, Any]]:
    """逐行断言 `text` 里**每一行**都是 JSON 对象（不是抽查某一行），返回解析结果。

    `pytest` 的 `capsys` 抓不住直接写 `sys.stderr` 的字节，故不能拿「`sys.stderr` 被替换过」
    当判据；这里改用 `json.loads` 作为判据并在失败时报出原始行——修复前的那一行
    （`[告警：env-mock] …` 纯文本）会当场被点出来。
    """
    records: list[dict[str, Any]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError as exc:
            raise AssertionError(f"日志行不是合法 JSON（{exc.msg}）：{line!r}") from exc
        assert isinstance(parsed, dict), f"日志行不是 JSON 对象：{line!r}"
        records.append(parsed)
    return records


def _only_probe_record(text: str) -> dict[str, Any]:
    records = _probe_records(text)
    assert len(records) == 1, f"探针记录应恰好一条，实际 {len(records)} 条：{records}"
    return records[0]


def _added_handlers(handlers_before: list[logging.Handler]) -> list[logging.Handler]:
    return [handler for handler in logging.getLogger().handlers if handler not in handlers_before]


def _config_module_records(text: str) -> list[dict[str, Any]]:
    """只保留 stdlib 告警所在的 `core/config.py` 日志器发出的记录。"""
    return [record for record in _json_records(text) if record.get("module") == CONFIG_MODULE]


# ---------------------------------------------------------------------------
# 1. 必含字段 schema
# ---------------------------------------------------------------------------


def test_required_log_fields_match_the_mandated_schema() -> None:
    """字段名与 PDD §8.5.1 L1747 **逐字一致**，12 项一个不多一个不少。

    `REQUIRED_LOG_FIELDS` 是给后续任务与评审比对用的公开常量；本用例把它与字面量集合钉在
    一起，故「实现里删掉一个字段」或「本文件手滑改字面量」都必须有人同时改另一处。
    """
    assert REQUIRED_LOG_FIELDS == MANDATED_FIELDS_LITERAL
    assert len(REQUIRED_LOG_FIELDS) == 12
    assert isinstance(REQUIRED_LOG_FIELDS, frozenset)


def test_emitted_record_carries_every_mandated_field(capsys: pytest.CaptureFixture[str]) -> None:
    """调用方只给 message，必含字段也一个不少（其余由处理器补齐）。

    这是「schema 完整」的承重用例：任何一项缺失都会被点名，而不是只报一个 not-in。
    """
    configure_logging(_test_settings())
    get_logger(PROBE_MODULE).info("探针：只给 message")

    record = _only_probe_record(capsys.readouterr().err)

    missing = REQUIRED_LOG_FIELDS - set(record)
    assert not missing, f"日志缺少必含字段：{sorted(missing)}"
    assert all(record[field] is not None for field in REQUIRED_LOG_FIELDS)


def test_error_record_with_traceback_stays_one_json_line(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """带异常堆栈的 ERROR 记录**仍是一行一个 JSON 对象**，堆栈落进 `exception` 字段。

    PDD §8.5.1 L1748 要求「ERROR 必须携带可定位上下文」，而堆栈是多行文本——若渲染时
    不转义，一行日志会裂成几十行，采集侧按行解析的假设当场失效（整条记录报废）。
    `format_exc_info` + JSON 字符串转义把堆栈压进一个字段，两个要求同时满足。
    """
    configure_logging(_test_settings())
    try:
        raise RuntimeError("探针：模拟通道失败")
    except RuntimeError:
        get_logger(PROBE_MODULE).exception("通道调用失败", bizType="ocr", opCode="ocr.recognize")

    text = capsys.readouterr().err
    lines = [line for line in text.splitlines() if line.strip()]
    assert len(lines) == 1, f"带堆栈的记录裂成了 {len(lines)} 行"

    record = _json_records(text)[0]
    assert set(record) >= REQUIRED_LOG_FIELDS
    assert record["level"] == "ERROR"
    assert "RuntimeError" in str(record["exception"]), "堆栈未落进 exception 字段"
    assert record["code"] == 0  # 调用方没给错误码，取平台默认值


def test_caller_structured_fields_round_trip(capsys: pytest.CaptureFixture[str]) -> None:
    """业务代码只传结构化字段（不手工拼字符串），字段原样出现在记录里。"""
    configure_logging(_test_settings())
    get_logger(PROBE_MODULE).info(
        "探针：结构化字段",
        bizType="ocr",
        opCode="ocr.recognize",
        code=4003,
        uid="test_uid_0001",
    )

    record = _only_probe_record(capsys.readouterr().err)

    assert record["bizType"] == "ocr"
    assert record["opCode"] == "ocr.recognize"
    assert record["code"] == 4003
    assert record["message"] == "探针：结构化字段"


def test_output_is_one_json_object_per_line(capsys: pytest.CaptureFixture[str]) -> None:
    """输出为「一行一个 JSON 对象」：三次调用三行，且捕获到的每一行都可解析。"""
    configure_logging(_test_settings())
    logger = get_logger(PROBE_MODULE)
    for sequence in range(3):
        logger.info("探针：逐行 JSON", seq=sequence)

    text = capsys.readouterr().err
    lines = [line for line in text.splitlines() if line.strip()]
    assert len(lines) >= 3, f"三次调用至少要三行，实际 {len(lines)} 行"
    # 逐行解析（含第三方库经 root 处理器输出的行）：任何一行不是 JSON 都失败
    assert len(_json_records(text)) == len(lines)
    assert [record["seq"] for record in _probe_records(text)] == [0, 1, 2]


def test_span_id_is_present_and_empty_because_skywalking_is_not_wired(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`spanId` **存在且恒为空**，这是刻意的，不是漏填，MUST NOT 当死字段清掉。

    依据：`design.md` D9 明确**不接 SkyWalking agent**（链路追踪后端留给平台级变更），
    而 PDD §8.5.1 要求日志必含 `spanId`。故输出该字段但值为空——schema 完整、不假装有埋点。

    调用方显式传入也不放行：否则一旦有人「顺手」填个假 spanId，日志就反过来骗人了。
    """
    configure_logging(_test_settings())
    get_logger(PROBE_MODULE).info("探针：spanId 留空", spanId="fake-span-must-not-leak-through")

    record = _only_probe_record(capsys.readouterr().err)

    assert "spanId" in record, "spanId 字段必须存在（PDD 必含字段，缺了就是 schema 断裂）"
    assert record["spanId"] == "", "不接 SkyWalking，spanId 必须为空且不可被调用方填充"


def test_schema_identity_fields_cannot_be_spoofed(capsys: pytest.CaptureFixture[str]) -> None:
    """app / service / spanId / traceId 由处理器强制赋值，调用方覆盖无效。"""
    configure_logging(_test_settings(app_name="aicore-under-test"))
    get_logger(PROBE_MODULE).info(
        "探针：伪造身份字段",
        app="evil-app",
        service="evil-service",
        spanId="evil-span",
        traceId="evil-trace",
    )

    record = _only_probe_record(capsys.readouterr().err)

    assert record["app"] == "aicore-under-test"
    assert record["service"] == "aicore"
    assert record["spanId"] == ""
    assert record["traceId"] != "evil-trace"


@pytest.mark.parametrize(
    ("method", "expected"),
    [
        ("debug", "DEBUG"),
        ("info", "INFO"),
        ("warning", "WARNING"),
        ("warn", "WARNING"),  # structlog 的别名：不归一就会写出 WARN（不在级别词表里）
        ("error", "ERROR"),
        ("critical", "CRITICAL"),
    ],
)
def test_level_reflects_the_call(
    capsys: pytest.CaptureFixture[str], method: str, expected: str
) -> None:
    """`level` 取大写（与 Java 侧 Logback `%level` 同口径），且如实反映调用级别。

    带别名的方法（`warn`）必须归一成词表里的名字：采集侧按级别过滤时，`WARN` 这种词表外的
    取值会被整批漏掉。`exception` 的归一见「带堆栈的记录」用例（它同时要验堆栈）。
    """
    configure_logging(_test_settings(log_level="DEBUG"))
    getattr(get_logger(PROBE_MODULE), method)("探针：级别")

    assert _only_probe_record(capsys.readouterr().err)["level"] == expected


def test_message_keeps_the_original_text(capsys: pytest.CaptureFixture[str]) -> None:
    """event → `message`：字段名换成 schema 要的名字，内容不变（中文可完整还原）。"""
    configure_logging(_test_settings())
    get_logger(PROBE_MODULE).info("识别失败：图片模糊", code=4003)

    record = _only_probe_record(capsys.readouterr().err)

    assert record["message"] == "识别失败：图片模糊"
    assert "event" not in record, "schema 用 message；同时留 event 会造成两套字段名"


def test_time_is_utc_iso8601(capsys: pytest.CaptureFixture[str]) -> None:
    """`time` 为 UTC ISO-8601（与信封 timestamp 同口径），可被运维直接排序比较。"""
    configure_logging(_test_settings())
    get_logger(PROBE_MODULE).info("探针：时间戳")

    record = _only_probe_record(capsys.readouterr().err)

    parsed = datetime.fromisoformat(str(record["time"]))
    assert parsed.tzinfo is not None, f"time 必须带时区：{record['time']!r}"
    assert parsed.utcoffset() == timedelta(0), f"time 必须是 UTC：{record['time']!r}"


def test_app_name_comes_from_settings(capsys: pytest.CaptureFixture[str]) -> None:
    """`app` 取配置里的 `app_name`（换部署名不必改代码），`service` 是固定服务身份。"""
    configure_logging(_test_settings(app_name="aicore-under-test"))
    get_logger(PROBE_MODULE).info("探针：app 名")

    record = _only_probe_record(capsys.readouterr().err)

    assert record["app"] == "aicore-under-test"
    assert record["service"] == "aicore"


def test_log_level_from_settings_is_honoured(capsys: pytest.CaptureFixture[str]) -> None:
    """`log_level` 被真正采纳：低于阈值的记录既不输出、也不落盘。"""
    configure_logging(_test_settings(log_level="WARNING"))
    logger = get_logger(PROBE_MODULE)
    logger.info("探针：低于阈值")
    logger.error("探针：达到阈值")

    records = _probe_records(capsys.readouterr().err)

    assert [record["message"] for record in records] == ["探针：达到阈值"]


def test_log_level_is_scoped_to_the_service_namespace(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """级别只落在 `aicore` 命名空间上，**不动 root**；第三方库的告警仍进同一 schema。

    这条是实测教训的固化：把 root 设成 INFO 之后，httpx 会把**完整请求 URL**（含 query 里的
    用户输入）写成一条 INFO 日志，`test_errors.py` 里「用户原值不得进日志」的用例当场变红
    ——即「顺手把第三方库的日志一起打开」本身就是一条泄漏面。

    处理器仍挂在 root 上：第三方库 WARNING 及以上的记录照样渲染成同一 schema（处理器与级别
    是两件事）。
    """
    root = logging.getLogger()
    root_level_before = root.level

    configure_logging(_test_settings(log_level="DEBUG"))

    assert root.level == root_level_before, "root 级别被改动：第三方库的日志会被顺手打开"
    assert logging.getLogger(SERVICE_NAME).level == logging.DEBUG
    get_logger(PROBE_MODULE).debug("探针：服务自身的 DEBUG 记录")
    logging.getLogger("httpx").warning("[告警：探针] 第三方库的告警")

    records = _json_records(capsys.readouterr().err)

    assert [record["module"] for record in records if record["level"] == "DEBUG"] == [PROBE_MODULE]
    third_party = [record for record in records if record["module"] == "httpx"]
    assert len(third_party) == 1, f"第三方库的告警未被同一管线渲染：{records}"
    assert set(third_party[0]) >= REQUIRED_LOG_FIELDS


def test_unknown_log_level_is_rejected_without_touching_live_configuration(
    capsys: pytest.CaptureFixture[str], settings: Settings
) -> None:
    """非法 `log_level` 当场报错（不静默退回 INFO），且**不改动**已生效的配置。

    静默兜底正是「以为配了其实没配」那类故障；已经配置好的日志器必须原样可用。
    """
    configure_logging(settings)
    handlers_before = list(logging.getLogger().handlers)

    with pytest.raises(ValueError) as excinfo:
        configure_logging(_test_settings(log_level="VERBOSE"))

    assert "VERBOSE" in str(excinfo.value)
    assert list(logging.getLogger().handlers) == handlers_before, "非法级别不应动已生效的处理器"
    get_logger(PROBE_MODULE).info("探针：配置未被破坏")
    assert _only_probe_record(capsys.readouterr().err)["message"] == "探针：配置未被破坏"


def test_get_logger_binds_module_and_yields_a_stdlib_bound_logger(
    capsys: pytest.CaptureFixture[str], settings: Settings
) -> None:
    """`get_logger(module)` 把模块名绑进 schema，并接到 stdlib `logging` 上。

    接到 stdlib 上意味着：级别过滤、`caplog`、root 处理器都照常工作（见 stdlib 记录用例）。
    """
    configure_logging(settings)

    logger = get_logger(PROBE_MODULE)

    bound = logger.bind()
    assert isinstance(bound, structlog.stdlib.BoundLogger)
    # 接在 stdlib logging 上（而不是 structlog 的 PrintLogger）：caplog / 级别过滤照常工作
    assert isinstance(bound._logger, logging.Logger), "structlog 日志器必须接在 stdlib logging 上"
    assert bound._logger.name == PROBE_MODULE
    logger.info("探针：模块名")
    assert _only_probe_record(capsys.readouterr().err)["module"] == PROBE_MODULE


# ---------------------------------------------------------------------------
# 2. stdlib logging 收编（Task 2.2 的规则 3 告警走这条通道）
# ---------------------------------------------------------------------------


def test_stdlib_record_is_rendered_in_the_same_schema(capsys: pytest.CaptureFixture[str]) -> None:
    """`logging.getLogger(...).warning("%s", arg)` 与 structlog 记录**同一 schema**。

    这是「不换掉 stdlib 日志」的正面证据：既有代码（`core/config.py` 的告警）不必改一行，
    就自动获得 JSON 输出与全部必含字段。
    """
    configure_logging(_test_settings())
    logging.getLogger(CONFIG_MODULE).warning("[告警：探针] stdlib 记录：%s", "带位置参数")

    text = capsys.readouterr().err
    records = _config_module_records(text)
    assert len(records) == 1, f"stdlib 记录应恰好一条：{records}"

    record = records[0]
    assert set(record) >= REQUIRED_LOG_FIELDS, (
        f"stdlib 记录缺少必含字段：{sorted(REQUIRED_LOG_FIELDS - set(record))}"
    )
    assert record["level"] == "WARNING"
    assert record["message"] == "[告警：探针] stdlib 记录：带位置参数"  # %s 已渲染
    assert record["module"] == CONFIG_MODULE  # 模块名取自 stdlib 日志器名
    assert record["service"] == "aicore"


def test_rule_three_warning_still_surfaces_in_json(capsys: pytest.CaptureFixture[str]) -> None:
    """Task 2.2 规则 3 的告警（dev/test 降级 mock）必须仍然出现，且以 JSON 形式出现。

    Task 2.2 选了 stdlib `logging` 而非 `warnings.warn`，正是为了被本任务的 JSON 管线收编；
    本用例把这条接线端到端钉住：构造 `dev + mock` 的 `Settings` 即触发告警，输出必须是
    带全部必含字段的 JSON 行，而不是纯文本或 stderr 兜底。
    """
    configure_logging(_test_settings())

    _test_settings(env="dev", provider="mock")  # 构造即告警（规则 3），不阻断

    text = capsys.readouterr().err
    records = _config_module_records(text)
    warnings = [record for record in records if "[告警：env-mock]" in str(record["message"])]
    assert len(warnings) == 1, f"规则 3 告警未落进 JSON 输出：{records}"

    warning = warnings[0]
    assert set(warning) >= REQUIRED_LOG_FIELDS
    assert warning["level"] == "WARNING"
    assert "env=dev" in str(warning["message"])


# ---------------------------------------------------------------------------
# 3. traceId / traceIdSource（Task 2.5 遗留项的验收证据）
# ---------------------------------------------------------------------------


def test_request_trace_id_is_propagated_from_the_header(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """网关注入的 `X-Request-Id` 原样进日志，来源标记 `propagated`。

    走**真实请求**（TestClient 触发 lifespan → 真实配置日志），不是直接调处理器。
    """
    with TestClient(_probe_app()) as client:
        response = client.get(PROBE_PATH, headers={TRACE_ID_HEADER: INJECTED_TRACE_ID})

    assert response.status_code == 200
    record = _only_probe_record(capsys.readouterr().err)
    assert record["traceId"] == INJECTED_TRACE_ID
    assert record[TRACE_SOURCE_FIELD] == TRACE_SOURCE_PROPAGATED
    assert TRACE_SOURCE_FIELD == "traceIdSource", "字段名是平台口径，改名即破坏主站 schema"


def test_request_without_header_generates_trace_id_and_marks_generated(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """网关没注入时自行生成 16 位 hex，并标 `generated` —— 网关故障不被本地生成掩盖。

    这正是 Task 2.5 评审留下的半截要求：没有 `traceIdSource`，「网关没注入」会被本地生成的
    traceId 掩盖；本用例与上一条合起来，就是「生成行为在日志中可区分」的验收证据。
    """
    with TestClient(_probe_app()) as client:
        response = client.get(PROBE_PATH)

    assert response.status_code == 200
    record = _only_probe_record(capsys.readouterr().err)
    assert TRACE_ID_PATTERN.fullmatch(str(record["traceId"])), f"生成值不是 16 位 hex：{record}"
    assert record[TRACE_SOURCE_FIELD] == TRACE_SOURCE_GENERATED
    assert record[TRACE_SOURCE_FIELD] != TRACE_SOURCE_PROPAGATED


def test_request_trace_id_is_carried_into_stdlib_records_too(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """请求上下文里的 traceId 同样进 stdlib 记录（告警与业务日志串得起来）。"""
    app = create_app()

    @app.get(PROBE_PATH, include_in_schema=False)
    async def _probe() -> dict[str, str]:
        logging.getLogger(CONFIG_MODULE).warning("[告警：探针] 请求内 stdlib 记录")
        return {"ok": "1"}

    with TestClient(app) as client:
        client.get(PROBE_PATH, headers={TRACE_ID_HEADER: INJECTED_TRACE_ID})

    records = _config_module_records(capsys.readouterr().err)
    # 只取本用例自己写的那条：修复轮 1 起，lifespan 的引导配置让**读配置阶段的规则 3 告警**
    # 也以 JSON 落在同一个模块（`test + mock` 是 conftest 的默认环境），故这里按消息来源收窄，
    # 而不是断言「整个模块只有一行」——后者会把「规则 3 告警没进 JSON」这个缺陷当成前提。
    own = [record for record in records if "[告警：探针]" in str(record["message"])]
    assert len(own) == 1, f"本用例的 stdlib 记录应恰好一条：{records}"
    assert own[0]["traceId"] == INJECTED_TRACE_ID
    assert own[0][TRACE_SOURCE_FIELD] == TRACE_SOURCE_PROPAGATED


# ---------------------------------------------------------------------------
# 4. 敏感信息：uid 脱敏与密钥打码
# ---------------------------------------------------------------------------


def test_raw_certificate_like_value_never_reaches_the_output(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`uid` 必含且**脱敏**：形似证件号的原始值不得出现在日志输出的任何位置。

    断言针对**整段输出**（不只是那一条记录）：只要原始值在本用例的任何一行里露头即失败。
    """
    configure_logging(_test_settings())
    get_logger(PROBE_MODULE).info(
        "探针：实名认证",
        uid=CERT_NUMBER_SENTINEL,
        bizType="realname",
        opCode="realname.verify",
    )

    text = capsys.readouterr().err

    assert CERT_NUMBER_SENTINEL not in text, "未脱敏的证件号进入了日志输出"
    record = _only_probe_record(text)
    assert record["uid"] == CERT_NUMBER_MASKED
    assert record["uid"] != CERT_NUMBER_SENTINEL


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        pytest.param("", "", id="空值保持空"),
        pytest.param(CERT_NUMBER_SENTINEL, CERT_NUMBER_MASKED, id="18-位证件号"),
        pytest.param("abc1234", "*******", id="长度不足时整串打码"),
        pytest.param("test_uid_0001", "tes******0001", id="普通用户标识"),
    ],
)
def test_desensitize_uid_keeps_only_head_and_tail(raw: str, expected: str) -> None:
    """脱敏规则：保留首 3 位与末 4 位，中间打码；太短就整串打码（不靠截断蒙混）。"""
    assert desensitize_uid(raw) == expected
    if raw:
        assert raw not in desensitize_uid(raw), "脱敏后仍能读到原值，等于没脱敏"


def test_desensitize_uid_never_leaks_length_zero_input() -> None:
    """空 uid 保持空串：字段存在但无值，不编造 `***` 之类假数据。"""
    assert desensitize_uid("") == ""
    assert desensitize_uid(None) == ""


def test_secret_named_fields_are_redacted(capsys: pytest.CaptureFixture[str]) -> None:
    """密钥类字段一律打码（PDD §8.5.1 L1748「禁止记录明文密钥」的兜底防线）。

    这是**兜底**：真正的规矩是「不要把密钥传给日志」。这里再挡一层，是因为一次手滑的
    `logger.info("配置", mysql_password=...)` 就会把口令永久写进日志文件。
    """
    configure_logging(_test_settings())
    get_logger(PROBE_MODULE).info(
        "探针：密钥字段",
        mysql_password=PASSWORD_SENTINEL,
        internal_token=TOKEN_SENTINEL,
        deepseek_api_key=CHANNEL_KEY_SENTINEL,
    )

    text = capsys.readouterr().err

    leaked = [sentinel for sentinel in SECRET_SENTINELS if sentinel in text]
    assert not leaked, f"日志输出泄漏了凭据：{leaked}"
    record = _only_probe_record(text)
    assert record["mysql_password"] == "***"
    assert record["internal_token"] == "***"
    assert record["deepseek_api_key"] == "***"


def test_non_secret_fields_are_not_redacted(capsys: pytest.CaptureFixture[str]) -> None:
    """阴性对照：打码只认密钥类字段名，不能「见 key/token 就抹」。

    LLM 的 token 计数字段是成本护栏的核心数据（`token_count` / `total_tokens` /
    `max_tokens`），抹掉它们等于把可观测性一起抹掉。带 `_token` 后缀的字段才是密钥。
    """
    configure_logging(_test_settings())
    get_logger(PROBE_MODULE).info(
        "探针：token 计数",
        token_count=42,
        total_tokens=1024,
        max_tokens=2048,
        idempotency_key="test-idem-key",
    )

    record = _only_probe_record(capsys.readouterr().err)

    assert record["token_count"] == 42
    assert record["total_tokens"] == 1024
    assert record["max_tokens"] == 2048
    assert record["idempotency_key"] == "test-idem-key"


# ---------------------------------------------------------------------------
# 5. 全局状态：可重复配置、可刷盘
# ---------------------------------------------------------------------------


def test_second_configuration_does_not_double_emit(
    capsys: pytest.CaptureFixture[str], settings: Settings
) -> None:
    """重复 `configure_logging` MUST NOT 重复挂处理器（否则每行日志会输出多份）。

    这是测试自身的卫生要求：pytest 在同一进程里跑完全部用例，本任务又把日志配置成
    进程级状态——第二次配置若只是「再加一个 handler」，日志就会成倍增长。
    """
    configure_logging(settings)
    configure_logging(settings)

    get_logger(PROBE_MODULE).info("探针：只应出现一次")

    records = _probe_records(capsys.readouterr().err)
    assert len(records) == 1, f"重复配置导致重复输出：{records}"


def test_repeated_configuration_installs_exactly_one_handler(settings: Settings) -> None:
    """三次配置后，本模块往 root 上新增的处理器恰好一个。"""
    root = logging.getLogger()
    handlers_before = list(root.handlers)

    configure_logging(settings)
    configure_logging(settings)
    configure_logging(settings)

    assert len(_added_handlers(handlers_before)) == 1


def test_flush_logging_flushes_the_installed_handler(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`flush_logging()` 刷的是本模块安装的处理器（关闭钩子的最小正确动作）。"""
    root = logging.getLogger()
    handlers_before = list(root.handlers)
    configure_logging(settings)
    installed = _added_handlers(handlers_before)
    assert len(installed) == 1

    flushed: list[str] = []
    monkeypatch.setattr(installed[0], "flush", lambda: flushed.append("flush"))

    flush_logging()

    assert flushed == ["flush"]


def test_lifespan_flushes_logging_on_shutdown(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """关闭钩子调用 `flush_logging()`：先不刷，退出 `with` 时刷一次。"""
    calls: list[str] = []
    monkeypatch.setattr("aicore.main.flush_logging", lambda: calls.append("flush"))

    with TestClient(_probe_app()) as client:
        client.get("/health")
        assert calls == [], "关闭前不应刷盘"

    assert calls == ["flush"], "关闭钩子未刷盘"


# ---------------------------------------------------------------------------
# 6. 引导配置（修复轮 1：读配置阶段的第一行日志也必须是 JSON）
# ---------------------------------------------------------------------------


def test_bootstrap_emits_json_before_any_settings_are_read(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`bootstrap_logging()` 之后写的每一行都是完整 schema 的 JSON —— 且它**不读配置**。

    判别力的要害在顺序：修复前「读配置 → 装配日志」，而规则 3 的告警在 `Settings(...)` 构造
    瞬间发出——那一行没有 JSON 处理器，落到 `logging.lastResort` 上变成纯文本。本用例在
    **不构造任何 `Settings`** 的前提下断言 schema 完整，正是把「配置还没读到，日志已经合 schema」
    这条要求钉死。
    """
    root = logging.getLogger()
    handlers_before = list(root.handlers)

    bootstrap_logging()
    get_logger(PROBE_MODULE).info("探针：引导配置后的第一行")

    record = _only_probe_record(capsys.readouterr().err)

    missing = REQUIRED_LOG_FIELDS - set(record)
    assert not missing, f"引导配置输出缺少必含字段：{sorted(missing)}"
    assert all(record[field] is not None for field in REQUIRED_LOG_FIELDS)
    assert record["level"] == "INFO"
    assert record["module"] == PROBE_MODULE
    assert len(_added_handlers(handlers_before)) == 1, "引导配置必须恰好装一个处理器"


def test_bootstrap_writes_to_the_same_schema_as_the_full_configuration(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """引导配置与正式配置产出**逐字相同**的字段集合（不是「另一套 JSON」）。

    这条是修复的实质：把首行换成 JSON 还不够，若引导用的是另一套字段形状，问题只是搬了家。
    只允许 `app` 的**取值**不同（引导读不到配置，取 `DEFAULT_APP_NAME`），字段集合必须一致。
    """
    bootstrap_logging()
    get_logger(PROBE_MODULE).info("探针：引导配置")
    bootstrap_record = _only_probe_record(capsys.readouterr().err)

    configure_logging(_test_settings(app_name="aicore-under-test"))
    get_logger(PROBE_MODULE).info("探针：正式配置")
    configured_record = _only_probe_record(capsys.readouterr().err)

    assert set(bootstrap_record) == set(configured_record)
    assert set(bootstrap_record) >= REQUIRED_LOG_FIELDS
    assert "event" not in bootstrap_record, "字段名必须是 message（两段配置同一口径）"
    assert bootstrap_record["app"] == DEFAULT_APP_NAME
    assert configured_record["app"] == "aicore-under-test"
    assert bootstrap_record["level"] == "INFO" == BOOTSTRAP_LOG_LEVEL
    assert bootstrap_record["service"] == configured_record["service"] == SERVICE_NAME


def test_bootstrap_then_configure_does_not_double_emit(
    capsys: pytest.CaptureFixture[str], settings: Settings
) -> None:
    """「引导 + 正式」是幂等序列：每行日志**只输出一份**，root 上只留一个本模块的处理器。

    这是简报点名的延伸保证：既有用例只覆盖「两次 `configure_logging`」；lifespan 真正跑的
    是「先 `bootstrap_logging()`、再 `configure_logging()`」，若正式配置没有先摘掉引导装的
    处理器，启动后的每行日志都会打印两份（噪声翻倍，采集侧还会当成两条记录）。
    """
    root = logging.getLogger()
    handlers_before = list(root.handlers)

    bootstrap_logging()
    configure_logging(settings)

    installed = _added_handlers(handlers_before)
    assert len(installed) == 1, f"引导 + 正式应只留一个处理器，实际 {len(installed)} 个"

    get_logger(PROBE_MODULE).info("探针：引导 + 正式各配一次")

    records = _probe_records(capsys.readouterr().err)
    assert len(records) == 1, f"引导 + 正式导致重复输出：{records}"


def test_repeated_bootstrap_installs_exactly_one_handler(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`bootstrap_logging()` 自身幂等：连调两次仍只装一个处理器、只输出一份。"""
    root = logging.getLogger()
    handlers_before = list(root.handlers)

    bootstrap_logging()
    bootstrap_logging()

    assert len(_added_handlers(handlers_before)) == 1

    get_logger(PROBE_MODULE).info("探针：引导两次")

    records = _probe_records(capsys.readouterr().err)
    assert len(records) == 1, f"引导配置重复调用导致重复输出：{records}"


def test_bootstrap_default_level_does_not_silence_json_errors(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """引导默认级别 `INFO` 收得住告警与错误，且**不是**把级别设到 root 上。

    `INFO` 的取舍：引导阶段只有启动校验的告警会说话，`INFO` 足够、又不会把正常启动刷成噪音。
    同时核对级别只落在服务命名空间——root 被调松会把第三方库的 INFO 一起打开（泄漏面）。
    """
    root = logging.getLogger()
    root_level_before = root.level

    bootstrap_logging()

    assert root.level == root_level_before, "引导配置改动了 root 级别：第三方库日志会被顺手打开"
    assert logging.getLogger(SERVICE_NAME).level == logging.INFO

    logging.getLogger(CONFIG_MODULE).warning("[告警：探针] 引导阶段的告警")
    assert len(_config_module_records(capsys.readouterr().err)) == 1


def test_bootstrap_after_configure_is_idempotent_too(
    capsys: pytest.CaptureFixture[str], settings: Settings
) -> None:
    """反序也幂等：`configure_logging` 之后再调 `bootstrap_logging`，仍只留一个处理器、一份输出。

    真实启动顺序是「引导 → 正式」，但幂等是被公开承诺的性质（重载、测试隔离、将来多入口），
    故反序也钉住：两个函数都走同一套「先摘旧的再挂新的」，顺序不该改变结论。
    """
    root = logging.getLogger()
    handlers_before = list(root.handlers)

    configure_logging(settings)
    bootstrap_logging()

    assert len(_added_handlers(handlers_before)) == 1

    get_logger(PROBE_MODULE).info("探针：正式 + 引导")

    records = _probe_records(capsys.readouterr().err)
    assert len(records) == 1, f"正式 + 引导导致重复输出：{records}"
    # 引导把 app 换回默认值（它读不到配置）——这条同时说明「后调用的那次配置说了算」。
    assert records[0]["app"] == DEFAULT_APP_NAME


# ---------------------------------------------------------------------------
# 7. lifespan 接线（本任务收口第 2 组）
# ---------------------------------------------------------------------------


def test_lifespan_configures_logging_so_records_are_json(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """启动钩子真的配置了日志：应用起来后业务代码写日志即得 JSON（无需测试手动配置）。"""
    with TestClient(_probe_app()) as client:
        client.get(PROBE_PATH)

    record = _only_probe_record(capsys.readouterr().err)
    assert set(record) >= REQUIRED_LOG_FIELDS
    assert record["level"] == "INFO"


def test_startup_first_emitted_line_is_json_with_every_mandated_field(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """**真实启动路径**下的第一行日志就是 JSON：规则 3 的告警不再落成纯文本（修复轮 1 的验收位）。

    走 `create_app()` + `TestClient`（真的进 lifespan，不是直接调处理器），环境配成
    `dev + mock`——`Settings(...)` 构造瞬间就会发规则 3 的降级告警，**那正是修复前唯一
    不合 schema 的那一行**。

    「首行是 JSON」由三步合起来证明：① 输出里**每一行**都可 `json.loads`（逐行解析，不是抽查）；
    ② 第一行就是规则 3 的告警，且必含字段齐全；③ 首行的 `app` 取引导默认值（此刻还没读到配置），
    后续行由正式配置的 `app_name` 覆盖——两段配置的差别只在取值，不在 schema。
    """
    for name in [name for name in os.environ if name.upper().startswith("AICORE_")]:
        monkeypatch.delenv(name)
    monkeypatch.setenv("AICORE_MYSQL_HOST", "127.0.0.1")
    monkeypatch.setenv("AICORE_MYSQL_USER", "test_user")
    monkeypatch.setenv("AICORE_MYSQL_PASSWORD", "test_password")
    monkeypatch.setenv("AICORE_MYSQL_DATABASE", "aicore_test")
    monkeypatch.setenv("AICORE_REDIS_HOST", "127.0.0.1")
    monkeypatch.setenv("AICORE_PROVIDER", "mock")
    monkeypatch.setenv("AICORE_ENV", "dev")  # 规则 3：dev + mock → 告警（不阻断）
    monkeypatch.setenv("AICORE_INTERNAL_TOKEN", "test_internal_token")
    monkeypatch.setenv("AICORE_DAILY_QUOTA_PER_ACCOUNT", "1000")
    monkeypatch.setenv("AICORE_DAILY_BUDGET_TOTAL", "100000")
    clear_settings_cache()

    with TestClient(_probe_app()) as client:
        client.get(PROBE_PATH)

    text = capsys.readouterr().err
    records = _assert_every_line_is_json(text)
    assert records, "启动一条日志都没写（本用例会静默变绿，故显式失败）"

    first = records[0]
    assert "[告警：env-mock]" in str(first["message"]), f"规则 3 的告警不是第一行：{first}"
    assert first["level"] == "WARNING"
    assert set(first) >= REQUIRED_LOG_FIELDS, (
        f"启动首行缺少必含字段：{sorted(REQUIRED_LOG_FIELDS - set(first))}"
    )
    assert first["app"] == DEFAULT_APP_NAME, "首行由引导配置产出，app 取引导默认值"
    assert first["service"] == SERVICE_NAME
    assert [record for record in records if record["module"] == CONFIG_MODULE] == [first], (
        f"规则 3 的告警应恰好一条：{records}"
    )


def test_rejected_startup_still_logs_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """被**拒绝**的启动同样产出 JSON：阻断项清单以结构化 ERROR 行落进日志管线。

    uvicorn 的启动失败栈是框架的 stderr 明文输出，**不进**本服务的 JSON 管线；拒绝启动恰恰
    是最该被采集器看见的事件，故 lifespan 在抛出前把阻断项清单写成一条结构化 ERROR 记录。
    四条断言：① 异常类型仍是 `ConfigRejected`（不是裸 `ValidationError`）；② `from None` 仍成立；
    ③ 输出里**每一行**都可解析成 JSON（逐行解析，不是抽查）；④ 那一条记录 schema 完整、
    逐条列出阻断项，且不带口令哨兵。
    """
    monkeypatch.setenv("AICORE_ENV", "prod")
    monkeypatch.setenv("AICORE_PROVIDER", "mock")  # 规则 1：prod + mock → 拒绝启动
    monkeypatch.setenv("AICORE_MYSQL_PASSWORD", PASSWORD_SENTINEL)
    clear_settings_cache()

    with pytest.raises(ConfigRejected) as excinfo, TestClient(_probe_app()):
        pass  # pragma: no cover —— 启动即被拒，进不来

    text = capsys.readouterr().err
    assert excinfo.value.__cause__ is None, "from None 未生效：拒绝路径会带出原始 ValidationError"
    rendered = "".join(traceback.format_exception(excinfo.value))
    assert PASSWORD_SENTINEL not in rendered, "异常链泄漏了口令"
    assert PASSWORD_SENTINEL not in text, "拒绝日志泄漏了口令"

    records = _assert_every_line_is_json(text)
    assert len(records) == 1, f"拒绝启动应恰好写一条记录：{records}"
    record = records[0]
    assert set(record) >= REQUIRED_LOG_FIELDS, (
        f"拒绝记录缺少必含字段：{sorted(REQUIRED_LOG_FIELDS - set(record))}"
    )
    assert record["level"] == "ERROR"
    assert record["module"] == LIFESPAN_MODULE, "记录应来自组合根的 lifespan"
    assert "[跨字段：env-mock]" in str(record["message"])
    assert "共 1 项阻断项" in str(record["message"])


def test_logging_survives_a_rejected_startup(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """拒绝启动之后，日志管线仍然可用：改成放行环境重启，第一行依旧是完整 schema 的 JSON。

    这条防的是「拒绝路径把全局日志配置搞坏」（半装状态、处理器被摘掉却没补上）：若引导配置
    装到一半就异常退出，第二次启动的首行又会退回纯文本，而 §6 的用例只跑成功路径，抓不到。
    """
    monkeypatch.setenv("AICORE_ENV", "prod")
    monkeypatch.setenv("AICORE_PROVIDER", "mock")
    clear_settings_cache()
    with pytest.raises(ConfigRejected), TestClient(_probe_app()):
        pass  # pragma: no cover —— 启动即被拒，进不来
    capsys.readouterr()  # 丢弃第一次的输出，下面只断言第二次

    monkeypatch.setenv("AICORE_ENV", "dev")  # 同一份配置改成放行组合
    clear_settings_cache()

    with TestClient(_probe_app()) as client:
        client.get(PROBE_PATH)

    records = _assert_every_line_is_json(capsys.readouterr().err)
    assert records, "拒绝之后重新启动没有产生任何日志行"
    first = records[0]
    assert "[告警：env-mock]" in str(first["message"]), f"第二轮的规则 3 告警不是首行：{first}"
    assert set(first) >= REQUIRED_LOG_FIELDS


def test_startup_rejects_invalid_configuration_with_config_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """配置非法 → 启动抛 `ConfigRejected`（**不是**裸 `ValidationError`），且不带口令。

    走真实启动路径（TestClient 进入 lifespan）。三条断言各管一件事：

    ① 异常类型：运维看到的是「逐条阻断项」的 `ConfigRejected`，不是 pydantic 的报错；
    ② `__cause__ is None` + `__suppress_context__`：`from None` 真的写上了。`from exc` 会把
       `ValidationError` 挂成 cause，异常链因此成为绕过「只用 loc/msg」的泄漏通道
       （见 `core/config.py` 模块 docstring）；
    ③ 渲染后的异常链里没有任何秘密哨兵。
    """
    monkeypatch.setenv("AICORE_ENV", "prod")
    monkeypatch.setenv("AICORE_PROVIDER", "mock")
    monkeypatch.setenv("AICORE_MYSQL_PASSWORD", PASSWORD_SENTINEL)
    clear_settings_cache()  # 缓存里可能还留着上一个用例的配置

    with pytest.raises(ConfigRejected) as excinfo, TestClient(create_app()):
        pass  # pragma: no cover —— 启动即被拒，进不来

    message = str(excinfo.value)
    assert "[跨字段：env-mock]" in message
    assert excinfo.value.__cause__ is None, "from None 未生效：异常链会带上原始 ValidationError"
    assert excinfo.value.__suppress_context__ is True
    rendered = "".join(traceback.format_exception(excinfo.value))
    assert PASSWORD_SENTINEL not in rendered
    assert PASSWORD_SENTINEL not in message


def test_raw_validation_error_carries_the_password_in_its_untruncated_input() -> None:
    """阴性对照：泄漏通道**真实存在** —— 原始 `ValidationError` 的 input 原样带口令。

    pydantic 2.13 在 `str(exc)` 里把 `input_value` 的**中段**省略，故这里 `str()` 未必看得见
    口令；但 `errors()[i]["input"]` 是**未截断**的，任何遍历它的代码（或未来版本调整截断口径）
    都会把口令写出去。本用例固定这个事实，使上一条用例不是「防一个不存在的风险」。
    """
    with pytest.raises(ValidationError) as excinfo:
        _test_settings(env="prod", provider="mock", mysql_password=PASSWORD_SENTINEL)

    payload = repr(excinfo.value.errors())
    assert PASSWORD_SENTINEL in payload, (
        "原始 ValidationError 不再携带口令：上一条用例的判别力需要重新评估"
    )


def test_create_app_still_builds_without_any_aicore_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """组合根仍是**纯装配函数**：清空全部 `AICORE_*` 后 `create_app()` 依然可建实例。

    与 `test_config_startup.py` 的同名用例分工：那条守的是「工厂不读配置」，这条守的是
    **本任务没有把配置读取搬进工厂**（启动接线只允许出现在 lifespan 里）。
    """
    for name in [name for name in os.environ if name.upper().startswith("AICORE_")]:
        monkeypatch.delenv(name)
    clear_settings_cache()

    assert create_app() is not None
