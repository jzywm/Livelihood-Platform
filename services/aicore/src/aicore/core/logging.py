"""结构化 JSON 日志（PDD §8.5.1 L1747）。

## 必含字段（`REQUIRED_LOG_FIELDS`，逐字对齐 PDD）

`time` / `level` / `app` / `service` / `module` / `traceId` / `spanId` / `uid` /
`bizType` / `opCode` / `code` / `message`。

计划文档把这一组写成「11 字段」，但 PDD 原文逐字列出的名字是 **12 个**；本模块以 PDD 为准
（`REQUIRED_LOG_FIELDS` 有 12 项，用例同时与字面量集合比对，改一个就要改两处）。

**`spanId` 恒为空**：`design.md` D9 明确**不接 SkyWalking agent**（链路追踪后端留给平台级变更），
故字段只为 schema 完整而输出、取值固定为空串——schema 完整、不假装有埋点。它由处理器强制赋值，
调用方显式传值也不会放行（否则日志会反过来骗人）。

**级别词表**：`DEBUG` / `INFO` / `WARNING` / `ERROR` / `CRITICAL`（一律大写，Python 口径）；
`logger.exception(...)` 与 `logger.warn(...)` 分别归一为 `ERROR` / `WARNING`（别名归一见
`_add_log_level`）。PDD 只钉了字段名没钉取值，本服务先取 Python 口径；主站 Logback 对告警级别
的字面量是 `WARN`——两语言若要对齐字面量，属平台级裁定，届时两侧同时改，本服务不单方面改名。

**`traceId` 单一来源**：只从 `core/trace.py` 的 `get_trace_id()` 取，本模块不另起实现；
同时输出 `traceIdSource`（`propagated` / `generated`）——少了这个标记，「网关没注入」会被本地
生成的 traceId 掩盖（Task 2.5 评审留下的半截要求在此补齐）。

## 与 stdlib `logging` 的关系（不是二选一）

structlog 只负责**事件收集与渲染**，落地仍走 stdlib：`structlog.stdlib.LoggerFactory()` 让
`get_logger(module)` 拿到的是 stdlib 日志器，渲染由 root 上的
`structlog.stdlib.ProcessorFormatter` 统一完成。于是：

- 既有 `logging.getLogger(__name__).warning(...)` 的代码（如 `core/config.py` 规则 3 的告警）
  **不改一行**就获得同一 schema——两条路径共用同一份处理器列表，不存在第二套字段口径；
- 级别过滤、`caplog`、第三方库日志照常工作。

**输出目标是 stderr**（stdlib `StreamHandler` 的默认目标）：stdout 留给程序自身输出，日志不与之
混流；`uvicorn` 的错误日志同样走 stderr，采集侧一并收走。

**级别设在服务自身的命名空间（`aicore`）上**，而不是 root：root 的级别会连带改变 httpx /
sqlalchemy 等第三方库的级别——实测 httpx 的 INFO 会把完整请求 URL（含 query 里的用户输入）写进
日志，那是顺手扩大泄漏面。第三方库保持各自默认级别，它们的 WARNING 及以上仍经 root 上的处理器
渲染成同一 schema（处理器与级别是两件事）。

**中文以 `\\uXXXX` 转义**（`JSONRenderer(ensure_ascii=True)`）：日志要在任意控制台 / 采集器里
无损落地——stderr 在非 UTF-8 代码页（如 Windows 的 cp936）下会把裸中文按 GBK 编码，UTF-8 采集器
读到的是**非法字节序列**（整行丢失，而不只是乱码）。纯 ASCII 输出没有这个依赖，JSON 解析器会把
转义还原成中文。

## MUST NOT 记录的内容（PDD §8.5.1 L1748）

**明文密钥、支付敏感信息、原始图像（含 base64 与图像内容）、未脱敏证件字段**一律不得进入日志。
业务代码只传结构化字段，MUST NOT 手工拼字符串——拼进字符串里的东西本模块识别不出来。

两道兜底都不能替代上面的规矩：

1. `uid` 一律经 `desensitize_uid()` 脱敏（保留首 3 末 4，其余打码）：schema 要求的
   `uid（脱敏）` 由处理器强制执行，不指望每个调用方自觉；
2. 密钥类**字段名**（`*_password` / `*_token` / `*_secret` / `*_api_key` …）的取值一律替换为
   `***`：一次手滑的 `logger.info("配置", mysql_password=...)` 就会把口令永久写进日志文件。
   只认字段名、不扫取值内容——按内容识别实体属于脱敏组件（正则 + 实体识别）的职责，
   在这里重复实现只会造出第二套会漂移的口径。

## 配置与关闭

`configure_logging(settings)` 由组合根的 lifespan 启动钩子调用，**可重复调用**：每次先摘掉上一次
装的处理器，故「配置两次 = 每行输出两份」不会发生。关闭钩子调 `flush_logging()` 刷盘。
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Iterator
from typing import Any, Final

import structlog
from structlog.typing import EventDict, Processor, WrappedLogger

from aicore.core.config import Settings
from aicore.core.trace import TRACE_SOURCE_FIELD, get_trace_id, get_trace_source

#: 服务身份（日志字段 `service`）：平台内固定，不随部署名变化。
SERVICE_NAME: Final = "aicore"

#: 平台码表的成功码（PDD §6.2）：非错误路径的日志默认 `code = 0`。
DEFAULT_CODE: Final = 0

#: `spanId` 的固定取值：不接 SkyWalking（`design.md` D9），字段留空。
SPAN_ID_EMPTY: Final = ""

#: 打码后的替代值（不保留原值长度，避免「长度」本身也成信息）。
REDACTED: Final = "***"

#: 脱敏 uid 时保留的首 / 尾位数。
_UID_HEAD: Final = 3
_UID_TAIL: Final = 4
_UID_MASK: Final = "*"

#: PDD §8.5.1 L1747 的必含字段，**逐字**。供用例与后续任务比对，MUST NOT 改名。
REQUIRED_LOG_FIELDS: Final[frozenset[str]] = frozenset(
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

#: 输出字段顺序：必含字段在前，附加字段（`traceIdSource` / `exception` 等）在后。
#: 固定顺序让每行的字段位置一致，采集侧与人工排障都不必猜「这行的 time 在哪」。
_FIELD_ORDER: Final[tuple[str, ...]] = (
    "time",
    "level",
    "app",
    "service",
    "module",
    "traceId",
    TRACE_SOURCE_FIELD,
    "spanId",
    "uid",
    "bizType",
    "opCode",
    "code",
    "message",
)

#: **精确匹配**即视为密钥的字段名（含各通道密钥字段的裸名写法）。
_SENSITIVE_FIELD_NAMES: Final[frozenset[str]] = frozenset(
    {
        "password",
        "passwd",
        "pwd",
        "secret",
        "token",
        "api_key",
        "apikey",
        "authorization",
        "credential",
        "credentials",
        "private_key",
        "access_token",
        "refresh_token",
        "id_token",
    }
)

#: 以这些后缀结尾即视为密钥（`mysql_password` / `internal_token` / `deepseek_api_key` …）。
#: 刻意不做子串匹配：`token_count` / `total_tokens` / `max_tokens` 是 LLM 成本护栏的核心数据，
#: 抹掉它们等于把可观测性一起抹掉。
_SENSITIVE_FIELD_SUFFIXES: Final[tuple[str, ...]] = (
    "_password",
    "_passwd",
    "_secret",
    "_token",
    "_api_key",
    "_credential",
    "_credentials",
)


def desensitize_uid(value: object) -> str:
    """脱敏 uid：保留首 3 位与末 4 位，其余打码。

    PDD §8.5.1 要求日志里的 `uid` 是**脱敏**值，而 uid 常常就是证件号 / 手机号 / 账号。
    本函数是这条要求的唯一实现，处理器对每条记录强制执行，故调用方传原值也不会漏出去。

    长度不足（≤ 首尾保留位数之和）时**整串打码**：此时「保留首尾」等于几乎没脱敏。
    非字符串取值先转成字符串再脱敏（形如整数的 uid 同样不能原样落盘）；`None` 与空串保持空。
    """
    if value is None:
        return ""
    text = value if isinstance(value, str) else str(value)
    if not text:
        return ""
    if len(text) <= _UID_HEAD + _UID_TAIL:
        return _UID_MASK * len(text)
    masked = len(text) - _UID_HEAD - _UID_TAIL
    return f"{text[:_UID_HEAD]}{_UID_MASK * masked}{text[-_UID_TAIL:]}"


def _add_log_level(logger: WrappedLogger, method_name: str, event_dict: EventDict) -> EventDict:
    """`level`：先按 structlog 的别名表归一，再转大写（`INFO` / `ERROR`，与主站 SLF4J 同口径）。

    别名归一**不能省**：`logger.exception(...)` 传下来的方法名是 `exception`，直接大写会得到
    `EXCEPTION`——它不在平台级别词表里（主站与 PDD 用的是 SLF4J 的 TRACE/DEBUG/INFO/WARN/ERROR），
    采集侧按级别过滤时会把这一类错误日志**整批漏掉**。这里复用 structlog 自己的别名表
    （`exception`→`error`、`warn`→`warning`，见 `structlog._log_levels.map_method_name`），
    只在其结果上做大写转换，不另写一张会漂移的别名表。

    大写是主站口径：Java 侧 Logback `%level` 输出的就是 `INFO` / `ERROR`。
    """
    structured = structlog.stdlib.add_log_level(logger, method_name, event_dict)
    structured["level"] = str(structured["level"]).upper()
    return structured


def _bind_module(logger: WrappedLogger, method_name: str, event_dict: EventDict) -> EventDict:
    """`module` 必含：structlog 路径由 `get_logger(module)` 绑定，stdlib 路径取日志器名。

    stdlib 记录（`ProcessorFormatter` 的 foreign 路径）的事件字典里带着 `_record`，
    日志器名就在它身上；两条路径合起来保证这个字段永不为空。
    """
    if "module" not in event_dict:
        record = event_dict.get("_record")
        event_dict["module"] = getattr(record, "name", "") or ""
    return event_dict


def _add_trace_context(
    logger: WrappedLogger, method_name: str, event_dict: EventDict
) -> EventDict:
    """`traceId` / `traceIdSource`：唯一来源是 `core/trace.py`（此处不另起实现）。

    请求内取到网关注入的值（`propagated`），请求外或网关漏注入时自行生成（`generated`）。
    """
    event_dict["traceId"] = get_trace_id()
    event_dict[TRACE_SOURCE_FIELD] = get_trace_source()
    return event_dict


def _force_empty_span_id(
    logger: WrappedLogger, method_name: str, event_dict: EventDict
) -> EventDict:
    """`spanId` **恒为空**：不接 SkyWalking（`design.md` D9），字段只为 schema 完整。

    强制赋值而非 `setdefault`：一旦允许调用方填值，日志里就会出现无人维护的假 spanId，
    「没接链路追踪」这件事会被日志掩盖。
    """
    event_dict["spanId"] = SPAN_ID_EMPTY
    return event_dict


def _mask_uid(logger: WrappedLogger, method_name: str, event_dict: EventDict) -> EventDict:
    """`uid` 强制脱敏：schema 写的是 `uid（脱敏）`，不能指望每个调用方自觉。"""
    event_dict["uid"] = desensitize_uid(event_dict.get("uid"))
    return event_dict


def _is_sensitive_field_name(name: str) -> bool:
    """字段名是否属于「取值绝不能进日志」的那一类（精确名 or 后缀，见上面两张表）。"""
    lowered = name.lower()
    return lowered in _SENSITIVE_FIELD_NAMES or lowered.endswith(_SENSITIVE_FIELD_SUFFIXES)


def _redact_sensitive_fields(
    logger: WrappedLogger, method_name: str, event_dict: EventDict
) -> EventDict:
    """密钥类字段打码（兜底防线，不能替代「不要把密钥传给日志」这条规矩）。"""
    for key in list(event_dict):
        if isinstance(key, str) and _is_sensitive_field_name(key):
            event_dict[key] = REDACTED
    return event_dict


def _order_fields(logger: WrappedLogger, method_name: str, event_dict: EventDict) -> EventDict:
    """按 `_FIELD_ORDER` 重排：必含字段在前、附加字段在后（渲染前最后一个语义处理器）。"""
    ordered: dict[str, object] = {
        key: event_dict[key] for key in _FIELD_ORDER if key in event_dict
    }
    ordered.update((key, value) for key, value in event_dict.items() if key not in ordered)
    return ordered


class _SchemaDefaults:
    """补齐必含字段里「与单条记录无关」的那些：`app` / `service` 与业务字段默认值。

    写成可调用对象（而不是闭包）是为了让 mypy 按 `Processor` 协议校验签名，同时把
    `settings.app_name` 在装配期就固定下来——渲染期不再读配置（配置只解析一次）。

    `app` / `service` 用**赋值**而非 `setdefault`：这两个字段是 schema 身份，调用方覆盖只会
    制造「同一进程出现两个服务名」的脏数据。`uid` / `bizType` / `opCode` / `code` 用默认值，
    业务代码按需传。
    """

    __slots__ = ("_app",)

    def __init__(self, app: str) -> None:
        self._app = app

    def __call__(self, logger: WrappedLogger, method_name: str, event_dict: EventDict) -> EventDict:
        event_dict["app"] = self._app
        event_dict["service"] = SERVICE_NAME
        event_dict.setdefault("uid", "")
        event_dict.setdefault("bizType", "")
        event_dict.setdefault("opCode", "")
        event_dict.setdefault("code", DEFAULT_CODE)
        return event_dict


class _JsonStreamHandler(logging.StreamHandler[Any]):
    """把 JSON 行写到**当前** `sys.stderr` 的处理器。

    为什么每次 `emit` 重新解析 `sys.stderr` 而不在构造时绑定：pytest 的 capsys / capfd 会在
    用例期间替换 `sys.stderr`、并在用例结束**关闭**被替换的对象。构造时抓到的引用会变成
    「已关闭的流」，之后每次写日志都抛 `ValueError`（`logging` 会打印 `--- Logging error ---`
    污染输出）。惰性解析让处理器永远写向「当下」的输出流。

    泛型参数只为满足 mypy：`logging.StreamHandler` 自 Python 3.11 起可下标
    （CPython gh-92128），本仓库下限 3.12，故这行在运行时同样成立。
    """

    def __init__(self) -> None:
        super().__init__(sys.stderr)

    def emit(self, record: logging.LogRecord) -> None:
        self.stream = sys.stderr
        super().emit(record)


def _iter_installed_handlers() -> Iterator[logging.Handler]:
    """本模块装在 root 上的处理器（按类型识别，不依赖模块级引用）。"""
    for handler in logging.getLogger().handlers:
        if isinstance(handler, _JsonStreamHandler):
            yield handler


def _remove_installed_handlers() -> None:
    """摘掉上一次装的处理器——可重复配置的关键，否则每行日志会被渲染多份。"""
    root = logging.getLogger()
    for handler in list(_iter_installed_handlers()):
        root.removeHandler(handler)
        handler.close()


def _resolve_level(name: str) -> int:
    """把配置里的级别名解析成 `logging` 级别；非法值当场报错，不静默退回 INFO。

    静默兜底正是「以为配了其实没配」那类故障（与 `core/config.py` 不给必填项默认值同一取向）。
    `NOTSET` 也判非法：它的语义是「未设置」，拿它当服务日志级别没有意义。
    """
    level = logging.getLevelNamesMapping().get(name.strip().upper())
    if level is None or level <= 0:
        raise ValueError(
            f"AICORE_LOG_LEVEL 取值非法：{name!r}；"
            "应为 DEBUG / INFO / WARNING / ERROR / CRITICAL 之一"
        )
    return level


def _shared_processors(app: str) -> list[Processor]:
    """两条路径共用的事件字典处理器。

    structlog 记录在**调用期**跑这一串（再交给 `wrap_for_formatter` 打包）；
    stdlib 记录在**格式化期**由 `ProcessorFormatter` 的 `foreign_pre_chain` 跑同一串。
    因此两侧的字段补齐、脱敏、traceId 注入完全一致，不存在第二套 schema。
    """
    return [
        _add_log_level,
        _bind_module,
        _add_trace_context,
        _SchemaDefaults(app),
        _force_empty_span_id,
        _mask_uid,
        _redact_sensitive_fields,
        structlog.processors.TimeStamper(fmt="iso", utc=True, key="time"),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]


def configure_logging(settings: Settings) -> None:
    """按配置装配结构化 JSON 日志（组合根的 lifespan 启动钩子调用）。

    **可重复调用**：每次先摘掉上一次装的处理器，再装新的，故不会出现「配置两次、每行输出两份」。
    非法 `log_level` 在动任何全局状态**之前**就抛错，已生效的配置保持可用。

    **级别设在服务自身的命名空间（`aicore`）上，不是 root**：root 的级别会连带改变
    httpx / sqlalchemy 等第三方库的日志级别——实测 httpx 的 INFO 会把**完整请求 URL**
    （含 query 里的用户输入）打进日志，那是顺手扩大泄漏面。第三方库保持各自默认级别，
    它们的 WARNING 及以上仍会经 root 上的处理器渲染成同一 schema（处理器与级别是两件事）。

    处理器同时设级别（与日志器一致）：兜住「别的代码把某个 logger 的级别调松」的情况。
    """
    level = _resolve_level(settings.log_level)
    shared = _shared_processors(settings.app_name)

    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        # 不缓存：本函数允许重复调用（测试隔离、配置重载），缓存会让已建好的日志器继续用旧配置，
        # 表现为「重新配置后日志还是老格式」这类极难排查的问题。
        cache_logger_on_first_use=False,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        # stdlib 记录先补齐 schema 与 traceId，再进下面的渲染链。
        foreign_pre_chain=shared,
        processors=[
            # 摘掉 `_record` / `_from_structlog`（LogRecord 不是 JSON 可序列化对象）。
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            # `event` → `message`（schema 字段名；放在重排之前，位置才落在末尾）。
            structlog.processors.EventRenamer("message"),
            _order_fields,
            # ensure_ascii=True 是刻意的：见模块 docstring「中文以 \uXXXX 转义」。
            structlog.processors.JSONRenderer(ensure_ascii=True),
        ],
    )

    handler = _JsonStreamHandler()
    handler.setFormatter(formatter)
    handler.setLevel(level)
    # 先摘旧的、再挂新的：新处理器此刻还没进 root 的列表，不会被这一次摘除误伤。
    _remove_installed_handlers()

    root = logging.getLogger()
    root.addHandler(handler)
    # SERVICE_NAME 同时是包名，即本服务全部日志器的命名空间（业务代码按 `__name__` 取日志器）。
    logging.getLogger(SERVICE_NAME).setLevel(level)


def get_logger(module: str) -> structlog.stdlib.BoundLogger:
    """取某个模块的日志器（业务代码写日志的**唯一**入口）。

    - `module` 惯例传 `__name__`：它既作为 stdlib 日志器名（级别过滤、`caplog` 按它工作），
      也绑进日志的 `module` 字段；
    - 返回类型是 `structlog.stdlib.BoundLogger`，但拿到手时是 structlog 的**惰性代理**：
      首次调用日志方法才装配，故「先建日志器、后 `configure_logging`」也没问题
      （模块顶层 `_logger = get_logger(__name__)` 是标准写法）；
    - MUST NOT 用它手工拼字符串：只传结构化字段（`bizType` / `opCode` / `code` / `uid` …），
      拼接会把密钥、原始图像之类的东西绕过本模块的脱敏与打码。
    """
    return structlog.stdlib.get_logger(module, module=module)


def flush_logging() -> None:
    """刷出并刷新本模块安装的处理器（关闭钩子的最小正确动作）。

    只刷自己的处理器：`logging.shutdown()` 会关闭**全部**处理器（含 pytest / uvicorn 挂的），
    进程内再写日志就会撞上已关闭的流——代价远大于「关闭时刷一下盘」这件事本身。
    """
    for handler in _iter_installed_handlers():
        handler.flush()
