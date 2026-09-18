"""统一响应信封（Task 2.4）。

本模块是**信封形状的唯一所有者**：四必填字段 `code` / `message` / `traceId` / `timestamp`
加可选的 `data`，取值口径全部来自平台单一事实源 `services/_common/openapi.yaml`：

- 必填集合与字段名逐字对齐该文件的 `Envelope`（`traceId` 是 camelCase，**不是** `trace_id`）；
- **成功码是 `0`**：`_common` 明写「前端可用 `code === 0` 判断成功」。
  `200` 是 HTTP 状态码，**MUST NOT** 出现在 `code` 字段里（同一条口径下，限流业务码是
  `2004` 而不是 HTTP 的 `429`）；
- `timestamp` 是 UTC ISO 8601、`Z` 结尾（`_common` 示例 `2026-01-15T10:30:00Z`）；
- `message` 是**面向用户**、可直接展示的文案；
- `data` 可选，缺省即 `None`，序列化时键**始终在**、值为 JSON `null`——失败路径
  （`core/errors.py`）已经在发 `"data": null`，成功但无数据的响应若改成省略键，
  同一平台就会出现两种形状。

**落地方式：逐路由 `response_model=Envelope[XxxResult]`，MUST NOT 用全局响应包装中间件。**
中间件会把 `/health`、`/metrics` 一并包住——存活探针判定与 Prometheus 抓取都会失效，
代价远大于少写一个 `response_model`。

**统一出口**：业务代码只准调 `Envelope.ok(...)` / `Envelope.fail(...)`，MUST NOT 手工拼装
四键映射（`tests/unit/test_envelope.py` 有结构扫描盯着这件事）。唯一的窄豁免是
`core/errors.py` 的 `_error_body`：它先于本任务落地、不能等模型就位才回错误响应，
其 docstring 已写明「与 Task 2.4 的模型同形，不是重复定义」，并由「其输出能通过本模型校验」
反向对齐（`test_error_body_builder_output_validates_against_the_envelope_model`）。

**时间戳助手的归属（依赖方向）**：`utc_timestamp()` 住在本模块，`core/errors.py` 从本模块导入。
信封模型是形状的所有者、异常处理器只是消费者，方向只能是 errors → envelope：反过来的
`envelope → errors` 会让模型依赖异常映射层，且 `errors.py` 将来改用 `Envelope.fail(...)`
时立刻成环。两者都只依赖 `core/trace.py`，无环。

**为什么 `extra="forbid"`**：多一个键就说明有人绕开了模型（手工拼装或字段名写错），
静默丢弃会把错误留到前端才暴露；反过来，它也让「错误处理器的输出能通过本模型校验」
成为一条强断言——多键、少键都会失败。

泛型用法（`T` 是 `data` 的类型，可以是任意 pydantic 模型，也可以是 `None`）::

    @router.get("/tasks/{task_id}", response_model=Envelope[TaskResult])
    async def get_task(task_id: str) -> Envelope[TaskResult]:
        return Envelope[TaskResult].ok(await service.load(task_id))
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Final

from pydantic import BaseModel, ConfigDict, field_validator

from aicore.core.trace import get_trace_id

#: 成功业务码。**不是** HTTP 的 `200`：前端按 `code === 0` 判断成功（`_common/openapi.yaml`）。
SUCCESS_CODE: Final = 0

#: 成功信封的文案。平台文案表（`core/errors.py` 的 `DEFAULT_MESSAGES`）只覆盖错误码，
#: 成功文案由本模块给出；取中文是与平台其余文案（`参数缺失` / `对象不存在` …）同口径，
#: `_common` 的 `message` 字段示例 `ok` 是 schema 占位示例，不是锁定值。
SUCCESS_MESSAGE: Final = "成功"

#: `timestamp` 的合法形状：UTC ISO 8601、`Z` 结尾（`_common` 示例 `2026-01-15T10:30:00Z`）。
#: 允许小数秒：`core/errors.py`（以及本模块的 `utc_timestamp()`）给的是 `isoformat()` 的输出，
#: 有微秒时会带小数部分。
UTC_ISO8601_PATTERN: Final = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")


def utc_timestamp() -> str:
    """当前时刻的 UTC ISO 8601 字符串，例：`2026-01-15T10:30:00.123456Z`。

    这是**全服务唯一**的时间戳助手：`core/errors.py` 也从这里导入，避免两处各写一份
    （两份额度会漂移成两种格式，前端与日志解析要各写一套）。
    """
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class Envelope[T](BaseModel):
    """平台统一响应信封：`code` / `message` / `traceId` / `timestamp` + 可选 `data`。

    字段顺序即序列化顺序：四必填在前、`data` 在末尾，读响应体时一眼能看到业务数据。

    构造入口只有两个（`ok` / `fail`），两者都**不接受**时间戳与 traceId 参数：
    `timestamp` 由本模块的 `utc_timestamp()` 现取、`traceId` 取自 `core/trace.py` 的
    `get_trace_id()`。调用方一旦能传，就会出现「时间戳来自别处时钟」与「traceId 另造来源」
    这两类静默漂移。字段本身仍可从外部校验（错误路径的响应体就是这样被反向校验的），
    但 `timestamp` 会被下面的校验器约束成 UTC + `Z`。
    """

    model_config = ConfigDict(extra="forbid")

    #: 业务码：成功 `0`，失败取 `_common` 的 ErrorCode 枚举（HTTP 状态不进这个字段）。
    code: int

    #: 面向用户的提示文案（可直接展示，MUST NOT 带内部细节）。
    message: str

    #: 链路追踪 ID，与请求头 `X-Request-Id` 同源（`core/trace.py`）。字段名 MUST NOT 改成蛇形。
    traceId: str  # noqa: N815 —— 平台契约字段名就是 camelCase 的 traceId

    #: 服务端时间（UTC ISO 8601，`Z` 结尾）。
    timestamp: str

    #: 业务数据：成功时有值，失败时为 `None`。泛型参数 `T` 由各路由的 `response_model` 指定。
    data: T | None = None

    @field_validator("timestamp")
    @classmethod
    def _require_utc_iso8601(cls, value: str) -> str:
        """拒绝非 UTC / 不以 `Z` 结尾的时间戳：两种形状发给前端等于契约失效。"""
        if not UTC_ISO8601_PATTERN.fullmatch(value):
            raise ValueError(
                f"timestamp 必须是 UTC ISO 8601 且以 Z 结尾"
                f"（例 2026-01-15T10:30:00Z），收到 {value!r}"
            )
        return value

    @classmethod
    def ok(cls, data: T) -> Envelope[T]:
        """成功信封：`code = 0`，带业务数据。

        路由里用**参数化**形式调用（`Envelope[XxxResult].ok(...)`），与 `response_model`
        声明的是同一个类；直接写 `Envelope.ok(...)` 也能被 FastAPI 按 `response_model`
        重新校验，但参数化形式在静态检查下就能对上类型。
        """
        return cls(
            code=SUCCESS_CODE,
            message=SUCCESS_MESSAGE,
            traceId=get_trace_id(),
            timestamp=utc_timestamp(),
            data=data,
        )

    @classmethod
    def fail(cls, code: int, message: str) -> Envelope[None]:
        """失败信封：没有业务数据，`data` 固定为 `None`。

        返回值固定是 `Envelope[None]`（而不是 `cls` 的参数化）：失败响应与 `T` 无关，
        硬塞一个业务类型只会让「失败响应也可能有 data」这种误读有市场。
        业务码与文案由调用方给出——码值来自 `core/errors.py` 的异常类或 `DEFAULT_MESSAGES`，
        本模型不替调用方猜码（HTTP 状态与文案映射的唯一出口仍是 `core/errors.py`）。
        """
        return Envelope[None](
            code=code,
            message=message,
            traceId=get_trace_id(),
            timestamp=utc_timestamp(),
            data=None,
        )
