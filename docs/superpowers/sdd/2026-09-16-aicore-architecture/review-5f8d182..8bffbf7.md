# Review package 5f8d182..8bffbf7

## Commits

8bffbf7 feat(aicore): 落地统一响应信封模型

## Stat

 services/aicore/src/aicore/core/envelope.py | 147 +++++-
 services/aicore/src/aicore/core/errors.py   |  13 +-
 services/aicore/tests/unit/test_envelope.py | 686 ++++++++++++++++++++++++++++
 3 files changed, 837 insertions(+), 9 deletions(-)

## Diff

```diff
diff --git a/services/aicore/src/aicore/core/envelope.py b/services/aicore/src/aicore/core/envelope.py
index d88be2e..90fd5e5 100644
--- a/services/aicore/src/aicore/core/envelope.py
+++ b/services/aicore/src/aicore/core/envelope.py
@@ -1 +1,146 @@
-"""统一响应信封（code/message/traceId/timestamp）。Task 2.4 实现。"""
+"""统一响应信封（Task 2.4）。
+
+本模块是**信封形状的唯一所有者**：四必填字段 `code` / `message` / `traceId` / `timestamp`
+加可选的 `data`，取值口径全部来自平台单一事实源 `services/_common/openapi.yaml`：
+
+- 必填集合与字段名逐字对齐该文件的 `Envelope`（`traceId` 是 camelCase，**不是** `trace_id`）；
+- **成功码是 `0`**：`_common` 明写「前端可用 `code === 0` 判断成功」。
+  `200` 是 HTTP 状态码，**MUST NOT** 出现在 `code` 字段里（同一条口径下，限流业务码是
+  `2004` 而不是 HTTP 的 `429`）；
+- `timestamp` 是 UTC ISO 8601、`Z` 结尾（`_common` 示例 `2026-01-15T10:30:00Z`）；
+- `message` 是**面向用户**、可直接展示的文案；
+- `data` 可选，缺省即 `None`，序列化时键**始终在**、值为 JSON `null`——失败路径
+  （`core/errors.py`）已经在发 `"data": null`，成功但无数据的响应若改成省略键，
+  同一平台就会出现两种形状。
+
+**落地方式：逐路由 `response_model=Envelope[XxxResult]`，MUST NOT 用全局响应包装中间件。**
+中间件会把 `/health`、`/metrics` 一并包住——存活探针判定与 Prometheus 抓取都会失效，
+代价远大于少写一个 `response_model`。
+
+**统一出口**：业务代码只准调 `Envelope.ok(...)` / `Envelope.fail(...)`，MUST NOT 手工拼装
+四键映射（`tests/unit/test_envelope.py` 有结构扫描盯着这件事）。唯一的窄豁免是
+`core/errors.py` 的 `_error_body`：它先于本任务落地、不能等模型就位才回错误响应，
+其 docstring 已写明「与 Task 2.4 的模型同形，不是重复定义」，并由「其输出能通过本模型校验」
+反向对齐（`test_error_body_builder_output_validates_against_the_envelope_model`）。
+
+**时间戳助手的归属（依赖方向）**：`utc_timestamp()` 住在本模块，`core/errors.py` 从本模块导入。
+信封模型是形状的所有者、异常处理器只是消费者，方向只能是 errors → envelope：反过来的
+`envelope → errors` 会让模型依赖异常映射层，且 `errors.py` 将来改用 `Envelope.fail(...)`
+时立刻成环。两者都只依赖 `core/trace.py`，无环。
+
+**为什么 `extra="forbid"`**：多一个键就说明有人绕开了模型（手工拼装或字段名写错），
+静默丢弃会把错误留到前端才暴露；反过来，它也让「错误处理器的输出能通过本模型校验」
+成为一条强断言——多键、少键都会失败。
+
+泛型用法（`T` 是 `data` 的类型，可以是任意 pydantic 模型，也可以是 `None`）::
+
+    @router.get("/tasks/{task_id}", response_model=Envelope[TaskResult])
+    async def get_task(task_id: str) -> Envelope[TaskResult]:
+        return Envelope[TaskResult].ok(await service.load(task_id))
+"""
+
+from __future__ import annotations
+
+import re
+from datetime import UTC, datetime
+from typing import Final
+
+from pydantic import BaseModel, ConfigDict, field_validator
+
+from aicore.core.trace import get_trace_id
+
+#: 成功业务码。**不是** HTTP 的 `200`：前端按 `code === 0` 判断成功（`_common/openapi.yaml`）。
+SUCCESS_CODE: Final = 0
+
+#: 成功信封的文案。平台文案表（`core/errors.py` 的 `DEFAULT_MESSAGES`）只覆盖错误码，
+#: 成功文案由本模块给出；取中文是与平台其余文案（`参数缺失` / `对象不存在` …）同口径，
+#: `_common` 的 `message` 字段示例 `ok` 是 schema 占位示例，不是锁定值。
+SUCCESS_MESSAGE: Final = "成功"
+
+#: `timestamp` 的合法形状：UTC ISO 8601、`Z` 结尾（`_common` 示例 `2026-01-15T10:30:00Z`）。
+#: 允许小数秒：`core/errors.py`（以及本模块的 `utc_timestamp()`）给的是 `isoformat()` 的输出，
+#: 有微秒时会带小数部分。
+UTC_ISO8601_PATTERN: Final = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")
+
+
+def utc_timestamp() -> str:
+    """当前时刻的 UTC ISO 8601 字符串，例：`2026-01-15T10:30:00.123456Z`。
+
+    这是**全服务唯一**的时间戳助手：`core/errors.py` 也从这里导入，避免两处各写一份
+    （两份额度会漂移成两种格式，前端与日志解析要各写一套）。
+    """
+    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
+
+
+class Envelope[T](BaseModel):
+    """平台统一响应信封：`code` / `message` / `traceId` / `timestamp` + 可选 `data`。
+
+    字段顺序即序列化顺序：四必填在前、`data` 在末尾，读响应体时一眼能看到业务数据。
+
+    构造入口只有两个（`ok` / `fail`），两者都**不接受**时间戳与 traceId 参数：
+    `timestamp` 由本模块的 `utc_timestamp()` 现取、`traceId` 取自 `core/trace.py` 的
+    `get_trace_id()`。调用方一旦能传，就会出现「时间戳来自别处时钟」与「traceId 另造来源」
+    这两类静默漂移。字段本身仍可从外部校验（错误路径的响应体就是这样被反向校验的），
+    但 `timestamp` 会被下面的校验器约束成 UTC + `Z`。
+    """
+
+    model_config = ConfigDict(extra="forbid")
+
+    #: 业务码：成功 `0`，失败取 `_common` 的 ErrorCode 枚举（HTTP 状态不进这个字段）。
+    code: int
+
+    #: 面向用户的提示文案（可直接展示，MUST NOT 带内部细节）。
+    message: str
+
+    #: 链路追踪 ID，与请求头 `X-Request-Id` 同源（`core/trace.py`）。字段名 MUST NOT 改成蛇形。
+    traceId: str  # noqa: N815 —— 平台契约字段名就是 camelCase 的 traceId
+
+    #: 服务端时间（UTC ISO 8601，`Z` 结尾）。
+    timestamp: str
+
+    #: 业务数据：成功时有值，失败时为 `None`。泛型参数 `T` 由各路由的 `response_model` 指定。
+    data: T | None = None
+
+    @field_validator("timestamp")
+    @classmethod
+    def _require_utc_iso8601(cls, value: str) -> str:
+        """拒绝非 UTC / 不以 `Z` 结尾的时间戳：两种形状发给前端等于契约失效。"""
+        if not UTC_ISO8601_PATTERN.fullmatch(value):
+            raise ValueError(
+                f"timestamp 必须是 UTC ISO 8601 且以 Z 结尾"
+                f"（例 2026-01-15T10:30:00Z），收到 {value!r}"
+            )
+        return value
+
+    @classmethod
+    def ok(cls, data: T) -> Envelope[T]:
+        """成功信封：`code = 0`，带业务数据。
+
+        路由里用**参数化**形式调用（`Envelope[XxxResult].ok(...)`），与 `response_model`
+        声明的是同一个类；直接写 `Envelope.ok(...)` 也能被 FastAPI 按 `response_model`
+        重新校验，但参数化形式在静态检查下就能对上类型。
+        """
+        return cls(
+            code=SUCCESS_CODE,
+            message=SUCCESS_MESSAGE,
+            traceId=get_trace_id(),
+            timestamp=utc_timestamp(),
+            data=data,
+        )
+
+    @classmethod
+    def fail(cls, code: int, message: str) -> Envelope[None]:
+        """失败信封：没有业务数据，`data` 固定为 `None`。
+
+        返回值固定是 `Envelope[None]`（而不是 `cls` 的参数化）：失败响应与 `T` 无关，
+        硬塞一个业务类型只会让「失败响应也可能有 data」这种误读有市场。
+        业务码与文案由调用方给出——码值来自 `core/errors.py` 的异常类或 `DEFAULT_MESSAGES`，
+        本模型不替调用方猜码（HTTP 状态与文案映射的唯一出口仍是 `core/errors.py`）。
+        """
+        return Envelope[None](
+            code=code,
+            message=message,
+            traceId=get_trace_id(),
+            timestamp=utc_timestamp(),
+            data=None,
+        )
diff --git a/services/aicore/src/aicore/core/errors.py b/services/aicore/src/aicore/core/errors.py
index e99185a..8bd29ae 100644
--- a/services/aicore/src/aicore/core/errors.py
+++ b/services/aicore/src/aicore/core/errors.py
@@ -82,29 +82,29 @@ FastAPI 默认处理器对这些状态回的就是无体 `Response`（`fastapi/e

 **文案策略**：框架的 `exc.detail` 是给开发者看的（`HTTPBearer` 抛的就是
 `"Not authenticated"` / `"Not enough permissions"`），故一律换成平台面向用户的文案，
 MUST NOT 把 `detail` 回显进响应体；`detail` 也不进日志（它可能带上游传入的内容）。
 """

 from __future__ import annotations

 import logging
 from collections.abc import Mapping, Sequence
-from datetime import UTC, datetime
 from typing import Any, Final, NamedTuple, cast

 from fastapi import FastAPI, Request
 from fastapi.exceptions import RequestValidationError
 from fastapi.responses import JSONResponse, Response
 from fastapi.utils import is_body_allowed_for_status_code
 from starlette.exceptions import HTTPException as StarletteHTTPException

+from aicore.core.envelope import utc_timestamp
 from aicore.core.trace import get_trace_id

 logger = logging.getLogger(__name__)

 # ---------------------------------------------------------------------------
 # 业务码常量
 #
 # 取值只能来自 `_common/openapi.yaml` 的 ErrorCode 枚举；本服务只用到其中 10 个。
 # 常量名一律以 `_CODE` 结尾且带 `CODE` 字样：**它们是业务码，不是 HTTP 状态码**，
 # 两者读写时 MUST NOT 互相代入（例如 `RATE_LIMITED_CODE` 是 2004，不是 429）。
@@ -572,25 +572,22 @@ def _loggable_errors(errors: Sequence[Mapping[str, Any]]) -> list[tuple[str, tup

 def _error_body(code: int, message: str) -> dict[str, Any]:
     """失败信封：`code` / `message` / `traceId` / `timestamp` 四必填字段 + `data: null`。

     **这里的形状是刻意的**：它就是 `_common/openapi.yaml` 的 `Envelope` 形状，与 Task 2.4
     的 `core/envelope.py` 模型同形，不是重复定义 —— Task 2.3 先于 Task 2.4 落地，异常处理器
     不能等模型就位才能返回错误响应，故此处用等价 dict 承载；`Envelope` 模型（及
     `Envelope.ok/fail`）由 **Task 2.4 拥有**，届时以「本处理器的输出能通过该模型校验」
     反向对齐，MUST NOT 在 core/envelope.py 之外再造一个模型类。

-    `timestamp` 为 UTC ISO 8601（`Z` 结尾，与 `_common` 示例 `2026-01-15T10:30:00Z` 同形）；
+    `timestamp` 为 UTC ISO 8601（`Z` 结尾，与 `_common` 示例 `2026-01-15T10:30:00Z` 同形），
+    由 `core/envelope.py` 的 `utc_timestamp()` 现取：时间戳助手全服务只有一份，方向是
+    errors → envelope（信封模型是形状的所有者，处理器只是消费者，反向 import 会成环）。
     `traceId` 一律取自 `core/trace.py` 的 `get_trace_id()`，不另造来源。
     """
     return {
         "code": code,
         "message": message,
         "data": None,
         "traceId": get_trace_id(),
-        "timestamp": _utc_timestamp(),
+        "timestamp": utc_timestamp(),
     }
-
-
-def _utc_timestamp() -> str:
-    """当前时刻的 UTC ISO 8601 字符串，例：`2026-01-15T10:30:00.123456Z`。"""
-    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
diff --git a/services/aicore/tests/unit/test_envelope.py b/services/aicore/tests/unit/test_envelope.py
new file mode 100644
index 0000000..fd9c6e1
--- /dev/null
+++ b/services/aicore/tests/unit/test_envelope.py
@@ -0,0 +1,686 @@
+"""统一响应信封用例（Task 2.4）。
+
+覆盖点：
+
+1. 模型形状与平台单一事实源（`services/_common/openapi.yaml` 的 `Envelope`）逐项对齐：
+   四必填字段 `code` / `message` / `traceId` / `timestamp`、可选 `data`、camelCase 字段名；
+2. `Envelope.ok` 的成功码是 **`0`**（不是 HTTP 的 `200`）；`Envelope.fail` 的 `data` 为 `None`；
+3. `timestamp` 由信封模块自己生成（UTC、`Z` 结尾），两个入口都**不接受**调用方传入的时间戳；
+4. `traceId` 只取自 `core/trace.py`（请求头 `X-Request-Id`），成功路径与错误路径同源；
+5. **反向对齐**：Task 2.3 的 `core/errors.py` 手工拼装的失败信封必须能通过本模型校验
+   （其 docstring 承诺过这件事）；
+6. `/health` 仍是裸响应：信封 MUST NOT 走全局响应包装中间件；
+7. 结构性红线：业务代码 MUST NOT 手工拼装信封、MUST NOT 再造第二个信封模型，
+   两条扫描器都带阴性对照，证明它们真的会报违规。
+
+**为什么结构扫描放在本文件**：任务简报钉死本任务只新建 `tests/unit/test_envelope.py`
+这一个文件；扫描器与判它判别力的用例紧邻，便于一起评审。
+"""
+
+from __future__ import annotations
+
+import ast
+import inspect
+import json
+import re
+from datetime import UTC, datetime, timedelta
+from pathlib import Path
+from typing import Any, Final
+
+import pytest
+import yaml
+from fastapi import FastAPI
+from fastapi.routing import iter_route_contexts
+from fastapi.testclient import TestClient
+from pydantic import BaseModel, ValidationError
+
+from aicore.core import envelope as envelope_module
+from aicore.core import errors as errors_module
+from aicore.core.envelope import SUCCESS_CODE, SUCCESS_MESSAGE, Envelope, utc_timestamp
+from aicore.core.errors import AICORE_ERROR_CODES, DEFAULT_MESSAGES, NotFoundError, _error_body
+from aicore.core.trace import TRACE_ID_HEADER
+from aicore.main import create_app
+
+SERVICE_ROOT = Path(__file__).resolve().parents[2]
+SRC = SERVICE_ROOT / "src" / "aicore"
+#: 平台单一事实源：各服务文档以相对路径 $ref 引用它，勿内联。
+PLATFORM_OPENAPI = SERVICE_ROOT.parent / "_common" / "openapi.yaml"
+
+#: 信封模型的文件（相对 `src/aicore`）：它是唯一允许出现信封形状的地方，故扫描时排除。
+ENVELOPE_MODULE_FILE: Final = "core/envelope.py"
+
+#: 信封的全部键 + 其中的必填键（与 `_common` 的 `Envelope.required` 一致）。
+ENVELOPE_KEYS: Final = frozenset({"code", "message", "traceId", "timestamp", "data"})
+ENVELOPE_REQUIRED_KEYS: Final = frozenset({"code", "message", "traceId", "timestamp"})
+
+#: UTC ISO 8601（`_common` 的示例是 `2026-01-15T10:30:00Z`；带微秒也合法）。
+ISO8601_UTC_PATTERN: Final = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")
+#: `core/trace.py` 自行生成时的形状：16 位小写 hex。
+TRACE_ID_PATTERN: Final = re.compile(r"^[0-9a-f]{16}$")
+#: `_common` 的示例值，同时也是合法的注入值。
+INJECTED_TRACE_ID: Final = "3f2a1b9c8d7e6f50"
+
+#: 扫描范围非空下限：低于此值说明扫描根失效，用例会静默变成空集而全绿。
+MIN_SCANNED_FILES: Final = 20
+
+#: 手工拼装信封的**窄豁免**：只有 Task 2.3 的错误处理器（其 docstring 明写「与 Task 2.4
+#: 的模型同形，不是重复定义」，且它先于本任务落地，不能等模型就位才回错误响应）。
+#: 豁免是承重的：`test_hand_assembly_scan_is_not_vacuous` 会证明关掉豁免它就立刻违规。
+HAND_ASSEMBLY_EXEMPT_FILES: Final = frozenset({"core/errors.py"})
+
+
+# ---------------------------------------------------------------------------
+# 平台单一事实源读取
+# ---------------------------------------------------------------------------
+
+
+def read_platform_envelope_schema() -> dict[str, Any]:
+    """读 `_common/openapi.yaml` 的 `Envelope` schema。"""
+    document = yaml.safe_load(PLATFORM_OPENAPI.read_text(encoding="utf-8"))
+    return document["components"]["schemas"]["Envelope"]
+
+
+def read_platform_error_codes() -> frozenset[int]:
+    """读同一个文件的 `ErrorCode` 枚举（成功码 `0` 也在这个枚举里）。"""
+    document = yaml.safe_load(PLATFORM_OPENAPI.read_text(encoding="utf-8"))
+    return frozenset(int(value) for value in document["components"]["schemas"]["ErrorCode"]["enum"])
+
+
+# ---------------------------------------------------------------------------
+# 探针模型、夹具与探针路由（只在用例里存在，生产代码不含任何调试端点）
+# ---------------------------------------------------------------------------
+
+
+class EchoResult(BaseModel):
+    """探针业务模型：证明 `Envelope[T]` 的泛型参数在真实路由上可用。"""
+
+    taskId: str  # noqa: N815 —— 业务字段名跟平台 camelCase 口径，该规则不适用于响应模型
+
+
+@pytest.fixture
+def enveloped_route(app: FastAPI) -> str:
+    """登记一条「成功且带业务数据」的探针路由，返回它的路径。
+
+    声明方式与生产路由一致：`response_model=Envelope[XxxResult]`，返回参数化实例——
+    这正是设计的落地方式（**不用**全局响应包装中间件）。
+    """
+    path = "/__test__/enveloped"
+
+    async def _handler() -> Envelope[EchoResult]:
+        return Envelope[EchoResult].ok(EchoResult(taskId="T-2026"))
+
+    app.add_api_route(path, _handler, methods=["GET"], response_model=Envelope[EchoResult])
+    return path
+
+
+@pytest.fixture
+def failure_route(app: FastAPI) -> str:
+    """登记一条「抛业务异常」的探针路由，返回它的路径（错误路径的反向对齐用）。"""
+    path = "/__test__/envelope-failure"
+
+    async def _raise() -> None:
+        raise NotFoundError("测试：对象不存在")
+
+    app.add_api_route(path, _raise, methods=["GET"], include_in_schema=False)
+    return path
+
+
+# ---------------------------------------------------------------------------
+# 1. 模型形状与平台契约
+# ---------------------------------------------------------------------------
+
+
+def test_required_fields_match_the_platform_contract() -> None:
+    """四必填字段与 `_common` 的 `Envelope.required` 逐项一致，`data` **不在**必填列表里。
+
+    两侧（平台文档 / 本模型）都取字面量比对，避免任一侧被悄悄改宽：
+    `data` 缺失时序列化成 `null`（见下一条用例），但它在契约里是可选字段。
+    """
+    platform = read_platform_envelope_schema()
+    assert set(platform["required"]) == ENVELOPE_REQUIRED_KEYS
+
+    schema = Envelope.model_json_schema()
+    assert set(schema["required"]) == ENVELOPE_REQUIRED_KEYS, (
+        "必填集合必须与 _common 的 Envelope.required 一致；"
+        "四字段一旦带上缺省值就会掉出 required，契约随之失效"
+    )
+    assert set(schema["properties"]) == ENVELOPE_KEYS
+    assert set(platform["properties"]) == ENVELOPE_KEYS
+
+
+def test_field_names_are_camel_case_trace_id_not_snake_case() -> None:
+    """字段名是 camelCase：`traceId`，**不是** `trace_id`（平台契约，前端按此解析）。"""
+    assert set(Envelope.model_fields) == ENVELOPE_KEYS
+    assert "trace_id" not in Envelope.model_fields
+    assert not any("_" in name for name in Envelope.model_fields)
+
+    dumped = Envelope.ok(None).model_dump()
+    assert "traceId" in dumped
+    assert "trace_id" not in dumped
+
+
+def test_data_is_serialized_as_json_null_rather_than_omitted() -> None:
+    """`data` 的序列化语义：**键始终在**，没有业务数据时是 JSON `null`（不是省略）。
+
+    理由：错误路径（`core/errors.py` 的 `_error_body`）已经在发 `"data": null`；
+    成功但无数据的响应若**省略** `data`，同一平台就会出现两种形状，前端要写两套判空。
+    """
+    envelope = Envelope.ok(None)
+    text = envelope.model_dump_json()
+
+    assert re.search(r'"data"\s*:\s*null', text), text
+    assert json.loads(text)["data"] is None
+    assert envelope.model_dump()["data"] is None
+    assert set(envelope.model_dump()) == ENVELOPE_KEYS
+
+
+def test_unknown_keys_are_rejected() -> None:
+    """`extra="forbid"`：多一个键就是形状被改过（拼装残留 / 字段名写错），当场拒绝。
+
+    静默丢弃会把错误留到前端才暴露；拒绝也顺便让「错误处理器的输出能通过模型校验」
+    成为强断言——多键、少键都会失败。
+    """
+    with pytest.raises(ValidationError):
+        Envelope.model_validate(
+            {
+                "code": 0,
+                "message": "成功",
+                "traceId": INJECTED_TRACE_ID,
+                "timestamp": "2026-01-15T10:30:00Z",
+                "data": None,
+                "detail": "框架残留的键",
+            }
+        )
+
+
+# ---------------------------------------------------------------------------
+# 2. 成功码 0 / 失败信封
+# ---------------------------------------------------------------------------
+
+
+def test_success_code_is_zero_and_must_never_become_http_200() -> None:
+    """成功码是 **`0`**，不是 HTTP 的 `200`。
+
+    平台口径（`_common/openapi.yaml`）：「前端可用 `code === 0` 判断成功」。
+    把成功码「修正」成 `200` 会让前端把所有成功响应判成失败，故本用例的断言消息里
+    写明原因：谁想改成 `200`，都会在这里先读到为什么不行。
+    """
+    assert SUCCESS_CODE == 0, "平台成功码是 0（前端按 code === 0 判断成功），不是 200"
+    assert SUCCESS_CODE != 200, "200 是 HTTP 状态码，不是平台业务码"
+    assert Envelope.ok(None).code == 0
+
+    platform_codes = read_platform_error_codes()
+    assert 0 in platform_codes, "成功码 0 必须在平台 ErrorCode 枚举内"
+    assert 200 not in platform_codes, "200 不得出现在平台业务码枚举内"
+
+
+def test_ok_fills_the_four_required_fields_and_keeps_data() -> None:
+    """`Envelope.ok(data)`：成功码 + 四必填齐全 + 业务数据原样保留。"""
+    result = EchoResult(taskId="T-2026")
+    envelope = Envelope.ok(result)
+
+    assert envelope.code == SUCCESS_CODE
+    assert envelope.data is result
+    assert envelope.message == SUCCESS_MESSAGE
+    assert SUCCESS_MESSAGE.strip(), "成功文案不能是空白"
+    assert TRACE_ID_PATTERN.fullmatch(envelope.traceId)
+    assert ISO8601_UTC_PATTERN.fullmatch(envelope.timestamp)
+    assert set(envelope.model_dump()) == ENVELOPE_KEYS
+
+
+@pytest.mark.parametrize("code", [1001, 2004, 3006, 4003, 5000, 5002])
+def test_fail_keeps_code_and_message_and_leaves_data_null(code: int) -> None:
+    """`Envelope.fail(code, message)`：码与文案原样带回，`data` 为 `None`。
+
+    参数化里刻意包含 `2004`（限流业务码）：它证明失败信封承载的是**业务码**，
+    与 HTTP 状态无关——`429` 永远不会出现在 `code` 字段里。
+    """
+    envelope = Envelope.fail(code, DEFAULT_MESSAGES[code])
+
+    assert envelope.code == code
+    assert envelope.message == DEFAULT_MESSAGES[code]
+    assert envelope.data is None
+    assert envelope.code != 200
+    assert set(envelope.model_dump()) == ENVELOPE_KEYS
+
+
+def test_ok_and_fail_accept_no_caller_supplied_timestamp_or_trace_id() -> None:
+    """两个入口 MUST NOT 接受 `timestamp` / `traceId` 参数：两者都由信封模块自己取。
+
+    调用方一旦能传，就会出现「时间戳取自业务进程的别处时钟」与「traceId 另造来源」
+    这两类静默漂移；签名是这两个入口唯一的对外形状，故在这里钉死。
+    """
+    assert list(inspect.signature(Envelope.ok).parameters) == ["data"]
+    assert list(inspect.signature(Envelope.fail).parameters) == ["code", "message"]
+
+
+def test_both_generic_parametrizations_are_usable() -> None:
+    """泛型参数真的生效：`Envelope[SomeModel]` 收得下业务模型，`Envelope[None]` 也能用。
+
+    并且 `T` 不是 `Any`：类型不符的 `data` 必须被拒（否则 `response_model` 等于没声明）。
+    """
+    typed = Envelope[EchoResult].ok(EchoResult(taskId="T-1"))
+    assert typed.data is not None
+    assert typed.data.taskId == "T-1"
+    assert Envelope[EchoResult].model_validate(typed.model_dump()).data == EchoResult(taskId="T-1")
+
+    none_typed = Envelope.fail(3006, DEFAULT_MESSAGES[3006])
+    assert none_typed.data is None
+    assert Envelope[None].model_validate(none_typed.model_dump()).code == 3006
+
+    with pytest.raises(ValidationError):
+        Envelope[EchoResult].model_validate(
+            {
+                "code": 0,
+                "message": "成功",
+                "traceId": INJECTED_TRACE_ID,
+                "timestamp": "2026-01-15T10:30:00Z",
+                "data": {"taskId": 1},
+            }
+        )
+
+
+# ---------------------------------------------------------------------------
+# 3. timestamp：由信封模块生成，UTC + Z 结尾
+# ---------------------------------------------------------------------------
+
+
+def test_timestamp_is_utc_iso8601_with_z_suffix() -> None:
+    """`timestamp` 是 UTC ISO 8601、`Z` 结尾，且落在本次构造的时间窗内（每次现取）。"""
+    before = datetime.now(UTC)
+    envelope = Envelope.ok(EchoResult(taskId="T-2026"))
+    after = datetime.now(UTC)
+
+    assert ISO8601_UTC_PATTERN.fullmatch(envelope.timestamp), envelope.timestamp
+    assert envelope.timestamp.endswith("Z")
+    parsed = datetime.fromisoformat(envelope.timestamp)
+    assert parsed.utcoffset() == timedelta(0)
+    assert before <= parsed <= after
+
+
+def test_timestamp_module_helper_and_construction_time_are_consistent() -> None:
+    """时间戳助手自身同形，且每构造一次取一次（不是模块级常量）。"""
+    assert ISO8601_UTC_PATTERN.fullmatch(utc_timestamp()), utc_timestamp()
+    assert utc_timestamp().endswith("Z")
+
+    first = datetime.fromisoformat(Envelope.ok(None).timestamp)
+    second = datetime.fromisoformat(Envelope.fail(3006, DEFAULT_MESSAGES[3006]).timestamp)
+    assert first <= second, "timestamp 必须是构造时现取，不能是固定的模块级常量"
+
+
+@pytest.mark.parametrize(
+    "timestamp",
+    [
+        pytest.param("2026-01-15T18:30:00+08:00", id="非 UTC 偏移"),
+        pytest.param("2026-01-15T10:30:00", id="无时区后缀"),
+        pytest.param("2026-01-15 10:30:00Z", id="空格分隔"),
+        pytest.param("2026-01-15T10:30:00+00:00", id="用了 +00:00 而非 Z"),
+        pytest.param("不是时间", id="非时间字符串"),
+    ],
+)
+def test_timestamp_rejects_non_utc_or_non_z_values(timestamp: str) -> None:
+    """阴性对照：非 UTC 或不以 `Z` 结尾的时间戳一律拒绝。
+
+    平台契约写的是「UTC，ISO 8601，例 `2026-01-15T10:30:00Z`」；随手传本地时间或
+    `+00:00` 都算漂移，必须在构造期就炸，而不是把两种形状发给前端。
+    """
+    with pytest.raises(ValidationError):
+        Envelope(
+            code=SUCCESS_CODE,
+            message=SUCCESS_MESSAGE,
+            traceId=INJECTED_TRACE_ID,
+            timestamp=timestamp,
+        )
+
+
+# ---------------------------------------------------------------------------
+# 4. traceId 与请求头同源（真实 HTTP 链路）
+# ---------------------------------------------------------------------------
+
+
+def test_trace_id_matches_the_request_header_on_both_paths(
+    enveloped_route: str, failure_route: str, client: TestClient
+) -> None:
+    """成功路径与错误路径的 `traceId` 同源：都取自 `core/trace.py`（请求头 `X-Request-Id`）。
+
+    同一个请求头打两条路径：成功路径的 traceId 由 `Envelope.ok` 现取，失败路径的由
+    `core/errors.py` 现取——两者必须给出同一个值，否则前端拿响应体里的 traceId 去查日志
+    会查不到，排障链路断在信封上。
+    """
+    headers = {TRACE_ID_HEADER: INJECTED_TRACE_ID}
+    ok_body = client.get(enveloped_route, headers=headers).json()
+    fail_body = client.get(failure_route, headers=headers).json()
+
+    assert ok_body["traceId"] == INJECTED_TRACE_ID
+    assert fail_body["traceId"] == INJECTED_TRACE_ID
+    assert ok_body["traceId"] == fail_body["traceId"]
+
+
+def test_trace_id_is_generated_when_the_header_is_absent(
+    enveloped_route: str, client: TestClient
+) -> None:
+    """头缺失时信封仍要有可用 traceId（16 位小写 hex），不能是空串。"""
+    body = client.get(enveloped_route).json()
+    assert TRACE_ID_PATTERN.fullmatch(body["traceId"]), body["traceId"]
+
+
+# ---------------------------------------------------------------------------
+# 5. 逐路由落地：response_model=Envelope[XxxResult] + OpenAPI 生成
+# ---------------------------------------------------------------------------
+
+
+def test_route_declaring_response_model_serializes_the_envelope(
+    enveloped_route: str, client: TestClient
+) -> None:
+    """路由用 `response_model=Envelope[EchoResult]` 声明即可落地信封（无需中间件）。
+
+    响应体的键集合、成功码与 `data` 形状都按模型走；`Envelope[EchoResult]` 能反解响应体，
+    说明 FastAPI 的响应校验用的就是同一个模型。
+    """
+    response = client.get(enveloped_route)
+    body = response.json()
+
+    assert response.status_code == 200
+    assert set(body) == ENVELOPE_KEYS
+    assert body["code"] == 0
+    assert body["data"] == {"taskId": "T-2026"}
+    assert ISO8601_UTC_PATTERN.fullmatch(body["timestamp"])
+
+    parsed = Envelope[EchoResult].model_validate(body)
+    assert parsed.data == EchoResult(taskId="T-2026")
+
+
+def test_openapi_generation_still_works_with_the_generic_response_model(
+    enveloped_route: str, app: FastAPI
+) -> None:
+    """泛型响应模型不得让 OpenAPI 生成失败，且响应 schema 指向信封组件。
+
+    这里只钉「响应 schema 是 Envelope 的参数化组件」这一件事：组件名由 FastAPI 生成
+    （形如 `Envelope_EchoResult_`），故从 `$ref` 反查，不写死名字。
+    """
+    spec = app.openapi()
+    response_schema = spec["paths"][enveloped_route]["get"]["responses"]["200"]["content"][
+        "application/json"
+    ]["schema"]
+    ref = response_schema["$ref"]
+
+    assert ref.startswith("#/components/schemas/Envelope"), ref
+    component = spec["components"]["schemas"][ref.rsplit("/", 1)[-1]]
+    assert set(component["required"]) == ENVELOPE_REQUIRED_KEYS
+    assert set(component["properties"]) == ENVELOPE_KEYS
+    assert component["properties"]["data"], "参数化组件的 data 必须带上业务模型，而不是空 schema"
+
+    # 生产应用的 schema 同样必须生成得出来（信封只在路由上落地，未改装配）。
+    assert "/health" in create_app().openapi()["paths"]
+
+
+# ---------------------------------------------------------------------------
+# 6. 反向对齐：Task 2.3 的错误信封必须能通过本模型校验
+# ---------------------------------------------------------------------------
+
+
+@pytest.mark.parametrize("code", sorted(AICORE_ERROR_CODES))
+def test_error_body_builder_output_validates_against_the_envelope_model(code: int) -> None:
+    """反向对齐（逐码）：`core/errors.py` 的 `_error_body` 输出必须能通过本模型校验。
+
+    这正是 Task 2.3 在 `_error_body` 的 docstring 里承诺的事：先用等价 dict 承载形状，
+    等 Task 2.4 的模型就位后「以本处理器的输出能通过该模型校验」反向对齐。
+    模型开了 `extra="forbid"`，故多一个键、少一个键都会在这里变红。
+    """
+    body = _error_body(code, DEFAULT_MESSAGES[code])
+    assert set(body) == ENVELOPE_KEYS, f"错误信封的键集合不符：{sorted(body)}"
+
+    envelope = Envelope.model_validate(body)
+    assert envelope.code == code
+    assert envelope.message == DEFAULT_MESSAGES[code]
+    assert envelope.data is None
+    assert TRACE_ID_PATTERN.fullmatch(envelope.traceId)
+    assert ISO8601_UTC_PATTERN.fullmatch(envelope.timestamp)
+
+
+def test_failing_http_responses_validate_against_the_envelope_model(
+    failure_route: str, client: TestClient
+) -> None:
+    """端到端反向对齐：**真实失败请求**的响应体也能通过模型校验（业务异常 + 框架 404）。
+
+    不只看手工构造的 dict：走完中间件、异常处理器与 JSON 序列化后，响应体仍是同一个形状。
+    """
+    business = client.get(failure_route)
+    assert business.status_code == 404
+    business_envelope = Envelope.model_validate(business.json())
+    assert business_envelope.code == 3006
+    assert business_envelope.data is None
+
+    framework_envelope = Envelope[None].model_validate(client.get("/__test__/no-such-route").json())
+    assert framework_envelope.code == 3006
+    assert framework_envelope.message != business_envelope.message, (
+        "路由 404 与业务 NotFoundError 的文案必须可区分（Task 2.3 的口径）"
+    )
+
+
+def test_timestamp_helper_has_a_single_source() -> None:
+    """时间戳助手只有一个来源：`core/envelope.py`（方向是 errors → envelope）。
+
+    信封模型是形状的唯一所有者，异常处理器只是它的消费者；反过来的 import 会让模型
+    依赖异常映射层，且 `errors.py` 将来改用 `Envelope.fail` 时立刻成环。
+    """
+    assert errors_module.utc_timestamp is envelope_module.utc_timestamp
+    assert not hasattr(errors_module, "_utc_timestamp"), "core/errors.py 又冒出第二个时间戳助手"
+    assert Path(inspect.getsourcefile(utc_timestamp) or "").resolve() == (
+        SRC / "core" / "envelope.py"
+    ).resolve()
+
+
+# ---------------------------------------------------------------------------
+# 7. /health 与 /metrics 必须裸（信封 MUST NOT 走全局中间件）
+# ---------------------------------------------------------------------------
+
+
+def test_health_stays_bare_because_the_envelope_is_not_a_middleware(
+    client: TestClient,
+) -> None:
+    """`/health` 是裸响应（Task 1.4 验收项 MUST NOT 回归）。
+
+    信封只能经 `response_model=` 逐路由落地。一旦有人改成全局响应包装中间件，
+    `/health` 立刻被包住、容器存活探针判定失效——本用例就是那条红线的哨兵。
+    """
+    body = client.get("/health").json()
+
+    assert body == {"status": "ok"}
+    assert ENVELOPE_KEYS.isdisjoint(body)
+
+
+def test_metrics_is_bare_too_when_the_endpoint_lands(client: TestClient) -> None:
+    """`/metrics` 同样必须裸：Prometheus 抓的是指标文本，被信封包住就抓不出指标了。
+
+    该端点在后续任务（可观测性组）才落地，故这里「存在才断言」：端点到岗后本用例
+    自动开始生效，不会因为「落地时忘了补」而漏掉。当前不存在时显式 skip，而不是静默通过。
+    """
+    paths = {context.path for context in iter_route_contexts(client.app.routes)}
+    if "/metrics" not in paths:
+        pytest.skip("/metrics 尚未落地（后续任务）；端点到岗后本用例自动开始断言")
+
+    response = client.get("/metrics")
+    assert response.status_code == 200
+    assert "traceId" not in response.text
+    assert not response.headers["content-type"].startswith("application/json")
+
+
+# ---------------------------------------------------------------------------
+# 8. 结构性红线：不得手工拼装信封、不得再造信封模型
+# ---------------------------------------------------------------------------
+
+
+def iter_source_files() -> list[Path]:
+    """`src/aicore` 下的全部 .py（排除字节码缓存目录）。"""
+    return sorted(path for path in SRC.rglob("*.py") if "__pycache__" not in path.parts)
+
+
+def mapping_literal_keys(node: ast.AST) -> set[str] | None:
+    """取该节点的「字面量键集合」；不是映射构造则返回 None。
+
+    - `ast.Dict`：只取字符串常量键（`{**other}` 的键位置是 None，跳过；变量键无法静态判定）；
+    - `dict(...)` 调用：取关键字参数名（`dict(**other)` 的 `arg` 是 None，跳过）。
+      这是等价的拼装口，不覆盖它扫描器就有一个现成的绕过通道。
+    """
+    if isinstance(node, ast.Dict):
+        return {
+            key.value
+            for key in node.keys
+            if isinstance(key, ast.Constant) and isinstance(key.value, str)
+        }
+    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "dict":
+        return {keyword.arg for keyword in node.keywords if keyword.arg is not None}
+    return None
+
+
+def find_hand_assembled_envelopes(source: str) -> list[int]:
+    """返回「手工拼装信封」的行号：同一个映射字面量里出现**全部四个**信封键。
+
+    判据是四键全中，而不是「含 code 与 message」：只带 code/message 的映射在本仓库到处
+    都是（业务 DTO、日志字段），放宽判据会让扫描器变成噪音源，最后被人关掉。
+    """
+    hits: list[int] = []
+    for node in ast.walk(ast.parse(source)):
+        keys = mapping_literal_keys(node)
+        if keys is not None and ENVELOPE_REQUIRED_KEYS.issubset(keys):
+            hits.append(node.lineno)
+    return sorted(hits)
+
+
+def scan_hand_assembled_envelopes() -> dict[str, list[int]]:
+    """扫描 `src/aicore/**`，返回「违规文件 → 行号」；排除信封模块自身与窄豁免清单。"""
+    offenders: dict[str, list[int]] = {}
+    for path in iter_source_files():
+        relative = path.relative_to(SRC).as_posix()
+        if relative == ENVELOPE_MODULE_FILE or relative in HAND_ASSEMBLY_EXEMPT_FILES:
+            continue
+        hits = find_hand_assembled_envelopes(path.read_text(encoding="utf-8"))
+        if hits:
+            offenders[relative] = hits
+    return offenders
+
+
+def find_envelope_model_classes(source: str) -> list[tuple[str, int]]:
+    """返回「类体字段注解覆盖四个信封键」的类（类名, 行号）。
+
+    只看形状、不看基类：不管是不是 pydantic 模型，把四个信封键都声明成类字段，
+    就已经是「第二个信封模型」。
+    """
+    hits: list[tuple[str, int]] = []
+    for node in ast.walk(ast.parse(source)):
+        if not isinstance(node, ast.ClassDef):
+            continue
+        fields = {
+            statement.target.id
+            for statement in node.body
+            if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name)
+        }
+        if ENVELOPE_REQUIRED_KEYS.issubset(fields):
+            hits.append((node.name, node.lineno))
+    return sorted(hits, key=lambda hit: hit[1])
+
+
+def test_no_business_code_hand_assembles_the_envelope() -> None:
+    """结构红线：除 `core/envelope.py` 外，业务代码 MUST NOT 手工拼装信封。
+
+    豁免只有 `core/errors.py` 一个文件（见 `HAND_ASSEMBLY_EXEMPT_FILES` 的注释）：
+    它的 `_error_body` 是 Task 2.3 刻意留下的等价 dict，docstring 已写明「不是重复定义」。
+    豁免的范围是**按文件**给的，而不是「core/ 整层不管」——后者会让 core/ 里任何新模块
+    都能悄悄手工拼装，等于把红线拆掉。
+    """
+    offenders = scan_hand_assembled_envelopes()
+
+    assert offenders == {}, (
+        f"以下文件手工拼装了信封（四键映射字面量）：{offenders}；"
+        f"请改用 Envelope.ok(...) / Envelope.fail(...)（信封唯一出口是 core/envelope.py）"
+    )
+
+
+def test_hand_assembly_scan_is_not_vacuous() -> None:
+    """扫描器的非空下限 + 豁免承重自检。
+
+    1. 扫描范围不得塌掉（文件数下限）：路径写错时遍历会静默变成空集而全绿；
+    2. 豁免必须**承重**：关掉豁免，`core/errors.py` 今天就应当被判违规。这一条同时证明
+       「扫描器在真实代码上有判别力」与「豁免没写歪」；若哪天 errors.py 改用 `Envelope.fail`，
+       本用例会变红，提示把豁免删掉（不留失效豁免）。
+    """
+    files = iter_source_files()
+    assert len(files) >= MIN_SCANNED_FILES, (
+        f"只扫到 {len(files)} 个 .py（下限 {MIN_SCANNED_FILES}）：扫描根 {SRC} 可能已失效"
+    )
+
+    assert sorted(HAND_ASSEMBLY_EXEMPT_FILES) == ["core/errors.py"], "豁免清单只允许这一个文件"
+    for relative in sorted(HAND_ASSEMBLY_EXEMPT_FILES):
+        exempt = SRC / relative
+        assert exempt.is_file(), f"豁免清单里的文件不存在：{relative}"
+        assert find_hand_assembled_envelopes(exempt.read_text(encoding="utf-8")), (
+            f"豁免 {relative} 已失效：该文件不再手工拼装信封，请从豁免清单中删除它"
+        )
+
+
+def test_hand_assembly_detector_fires_on_synthetic_samples() -> None:
+    """阴性对照：扫描器必须报得出违规样本，且不误报合法样本。
+
+    「永远绿的检查」等于没有检查，故每个样本都要求扫描器表态。
+    """
+    offenders = (
+        # Task 2.3 的写法：直接字面量
+        'def f():\n    return {"code": 0, "message": "ok", "traceId": t, "timestamp": s}\n',
+        # 带上 data 也一样命中（判据是四键全中，data 可有可无）
+        'def f():\n    return {"code": 0, "message": "ok", "traceId": t,'
+        ' "timestamp": s, "data": d}\n',
+        # dict(...) 关键字写法是等价的拼装口，不能成为绕过通道
+        'def f():\n    return dict(code=0, message="ok", traceId=t, timestamp=s)\n',
+        # 嵌套在别的字典里同样要报
+        'def f():\n    return {"outer": {"code": 0, "message": "ok",'
+        ' "traceId": t, "timestamp": s}}\n',
+    )
+    for source in offenders:
+        assert find_hand_assembled_envelopes(source), f"扫描器漏报违规样本：{source!r}"
+
+    legit = (
+        # 少一个键就不算信封
+        'def f():\n    return {"code": 0, "message": "ok", "traceId": t}\n',
+        'def f():\n    return {"code": 0, "message": "ok", "timestamp": s}\n',
+        # 键名出现在字符串字面量里不算（扫的是映射键，不是文本）
+        'def f():\n    return "code message traceId timestamp"\n',
+    )
+    for source in legit:
+        assert find_hand_assembled_envelopes(source) == [], f"扫描器误报合法样本：{source!r}"
+
+
+def test_only_core_envelope_declares_the_envelope_model() -> None:
+    """结构红线：MUST NOT 在 `core/envelope.py` 之外再造一个信封模型类。
+
+    正本自己必须能被这个判据认出来（下面的断言），否则判据是瞎的。
+    """
+    envelope_source = (SRC / ENVELOPE_MODULE_FILE).read_text(encoding="utf-8")
+    assert [name for name, _ in find_envelope_model_classes(envelope_source)] == ["Envelope"], (
+        "判据必须能认出正本 core/envelope.py 里的 Envelope 类"
+    )
+
+    offenders = {
+        relative: hits
+        for path in iter_source_files()
+        if (relative := path.relative_to(SRC).as_posix()) != ENVELOPE_MODULE_FILE
+        and (hits := find_envelope_model_classes(path.read_text(encoding="utf-8")))
+    }
+    assert offenders == {}, (
+        f"以下模块自建了信封模型类：{offenders}；信封模型的唯一出口是 core/envelope.py"
+    )
+
+
+def test_envelope_model_detector_fires_on_a_second_model() -> None:
+    """阴性对照：第二个信封模型必须被检出，少一个字段的类不得误报。"""
+    bad = (
+        "class OtherEnvelope(BaseModel):\n"
+        "    code: int\n"
+        "    message: str\n"
+        "    traceId: str\n"
+        "    timestamp: str\n"
+    )
+    assert find_envelope_model_classes(bad) == [("OtherEnvelope", 1)]
+
+    partial = "class Other(BaseModel):\n    code: int\n    message: str\n    traceId: str\n"
+    assert find_envelope_model_classes(partial) == []

```
