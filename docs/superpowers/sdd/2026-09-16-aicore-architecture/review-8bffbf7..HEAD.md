# Review package 8bffbf7..HEAD

## Commits

9a3f4be docs(aicore): 修正日志必含字段数 11→12（PDD 逐字为 12 项）
fdd7ee3 fix(aicore): 启动首行日志改为引导配置下的 JSON
0ac7f5d feat(aicore): 实现结构化 JSON 日志并接线启动钩子

## Stat

 .../plans/2026-09-16-aicore-architecture.md        |   12 +-
 services/aicore/src/aicore/core/logging.py         |  509 ++++++++-
 services/aicore/src/aicore/main.py                 |   48 +-
 services/aicore/tests/unit/test_logging.py         | 1122 ++++++++++++++++++++
 4 files changed, 1680 insertions(+), 11 deletions(-)

## Diff

```diff
diff --git a/docs/superpowers/plans/2026-09-16-aicore-architecture.md b/docs/superpowers/plans/2026-09-16-aicore-architecture.md
index 8cdcfcd..abcaacb 100644
--- a/docs/superpowers/plans/2026-09-16-aicore-architecture.md
+++ b/docs/superpowers/plans/2026-09-16-aicore-architecture.md
@@ -13,21 +13,21 @@
 ## Global Constraints

 以下约束作用于**每一个任务**，逐条抄自 spec 已核实的权威口径，不得凭记忆改动：

 - **成功码 = `0`**（`_common/openapi.yaml` L122「前端可用 `code === 0` 判断成功」）；**MUST NOT** 使用 `200`。
 - **`Envelope` 必填四字段**：`code` / `message` / `traceId` / `timestamp`；`data` 可选；字段名 **camelCase**（`traceId`，非 `trace_id`）；`timestamp` 为 **UTC ISO 8601**。
 - **限流的业务码是 `2004`**，不是 `429`——`429` 是 HTTP 状态码，**不在平台码表内**。
 - **错误码只能取 `_common/openapi.yaml` `ErrorCode` 枚举内的值**：`0` `1001` `1002` `1003` `2001` `2002` `2003` `2004` `3001`–`3011` `4001`–`4004` `5000` `5001` `5002` `5003`。AICORE 用到：`1001`/`1002`/`1003`/`2001`/`2002`/`2004`/`3006`/`4003`/`5000`/`5002`。
 - **traceId 请求头 = `X-Request-Id`**（`PDD` §8.5.1 L1750）；**MUST NOT** 使用 `X-Trace-Id`。
 - **内部凭据请求头 = `X-Internal-Token`**；服务端间接口 **MUST NOT** 接受终端用户 JWT。
-- **日志必含 11 字段**：`time` / `level` / `app` / `service` / `module` / `traceId` / `spanId` / `uid` / `bizType` / `opCode` / `code` / `message`；**MUST NOT** 记录明文密钥、支付敏感信息、原始图像、未脱敏证件字段。
+- **日志必含 12 字段**（PDD §8.5.1 L1747 逐字）：`time` / `level` / `app` / `service` / `module` / `traceId` / `spanId` / `uid` / `bizType` / `opCode` / `code` / `message`；**MUST NOT** 记录明文密钥、支付敏感信息、原始图像、未脱敏证件字段。
 - **AI 超时 5s**（高并发 §7.6 L423）。
 - **数据库**：独立库 `aicore`，MySQL 8，InnoDB，`utf8mb4`，时间 `datetime(3)`（UTC 存储、输出 Asia/Shanghai），置信度 `decimal(3,2)`，风险分 `decimal(5,2)`，数组用 JSON 列，**MUST NOT** 存原始图像或证件明文。**枚举值与 `openapi.yaml` `components.schemas` 一一对应**。
 - **ID 策略**：`前缀 + UUID`，**总长 ≤32**（所有 ID 列均 `varchar(32)`）；前缀集 `task_` / `cor_` / `rev_` / `marker_` / `kan_` / `qa_`；**MUST NOT** 引入雪花 ID 或 workerId。
 - **分片**：仅 `ai_task` / `ocr_result` / `ocr_correction` 三张按月分表（`_YYYYMM`）；查询 **MUST** 携带分片键下推；**MUST NOT** 跨分片 JOIN / 聚合 / 事务。
 - **写后立即读强制走主库**（`er.md` §5.5）。
 - **合规红线**：AI 只标记不决策（C8）；脱敏失败即拒绝外发（D4）；无人工复核结论不得回写权威数据（D5）；画像权重不进定价（R-07）。涉及处须在代码注释中同步标注。
 - **提交规范**：Conventional Commits，type 英文 + 描述中文，**不带 `[AI]` 前缀**；提交前过 `commit-check` 门禁。
 - **测试内 MUST NOT 出现任意 `sleep`**；等待走可控时钟或轮询断言。
 - **覆盖率门禁 ≥80%**（`pytest --cov src/aicore`），`main.py` 与 `provider/` 真实通道骨架允许排除。

@@ -360,21 +360,21 @@ git commit -m "chore: 搭建 AICORE 工程骨架与工具链"

 ```python
 """统一响应信封（code/message/traceId/timestamp）。Task 2.4 实现。"""
 ```

 ```python
 """traceId 上下文变量与传播（请求头 X-Request-Id）。Task 2.5 实现。"""
 ```

 ```python
-"""结构化 JSON 日志（11 必含字段）。Task 2.6 实现。"""
+"""结构化 JSON 日志（12 必含字段，PDD §8.5.1 L1747 逐字）。Task 2.6 实现。"""
 ```

 - [ ] **Step 4: 写 `core/idgen.py`、`core/security.py`、`core/ratelimit.py`、`core/budget.py`、`core/task_runner.py` 空壳**

 ```python
 """前缀化分布式 ID（前缀 + UUID，总长 ≤32）。Task 3.8 实现。"""
 ```

 ```python
 """内部 Token 校验（请求头 X-Internal-Token）。第 4 组实现。"""
@@ -1341,31 +1341,31 @@ git commit -m "feat: 实现 AICORE 组合根与存活检查"
 ### Task 2.6: 结构化 JSON 日志

 **Files:**
 - Modify: `services/aicore/src/aicore/core/logging.py`
 - Modify: `services/aicore/src/aicore/main.py`（启动时初始化）
 - Create: `services/aicore/tests/unit/test_logging.py`

 **Interfaces:**
 - Consumes: `core/trace.py` 的 `get_trace_id()`；`core/config.py` 的 `Settings.log_level`
 - Produces: `configure_logging(settings: Settings) -> None`；`get_logger(module: str) -> structlog.BoundLogger`；
-  `REQUIRED_LOG_FIELDS: frozenset[str]`（11 字段常量，供用例比对）
+  `REQUIRED_LOG_FIELDS: frozenset[str]`（12 字段常量，供用例比对）

-**硬约束**：必含 11 字段 `time` / `level` / `app` / `service` / `module` / `traceId` / `spanId` / `uid` /
+**硬约束**：必含 12 字段 `time` / `level` / `app` / `service` / `module` / `traceId` / `spanId` / `uid` /
 `bizType` / `opCode` / `code` / `message`（字段名与 PDD §8.5.1 L1747 **逐字一致**）；
 **`spanId` 输出字段但值为空**（`design.md` D9 明确不接 SkyWalking agent，不假装有埋点）；
 **MUST NOT** 记录明文密钥、未脱敏证件字段、原始图像。

-- [ ] Step 1~N：先写「输出为合法 JSON 且含全部 11 字段」用例，再写
+- [ ] Step 1~N：先写「输出为合法 JSON 且含全部 12 字段」用例，再写
   「`spanId` 存在且为空」用例，最后写「构造含证件号的输入，断言日志中不出现明文」用例

-**验收**：11 字段 schema 用例通过；`spanId` 留空；敏感信息不出现在日志
+**验收**：12 字段 schema 用例通过；`spanId` 留空；敏感信息不出现在日志

 ---

 ## 第 3 组：数据层与分表路由

 ### Task 3.1: DDL

 **Files:**
 - Create: `services/aicore/deploy/sql/ddl/00_create_database.sql`
 - Create: `services/aicore/deploy/sql/ddl/10_ai_task.template.sql`、`11_ocr_result.template.sql`、`12_ocr_correction.template.sql`
diff --git a/services/aicore/src/aicore/core/logging.py b/services/aicore/src/aicore/core/logging.py
index 9932206..958a78c 100644
--- a/services/aicore/src/aicore/core/logging.py
+++ b/services/aicore/src/aicore/core/logging.py
@@ -1 +1,508 @@
-"""结构化 JSON 日志（11 必含字段）。Task 2.6 实现。"""
+"""结构化 JSON 日志（PDD §8.5.1 L1747）。
+
+## 必含字段（`REQUIRED_LOG_FIELDS`，逐字对齐 PDD）
+
+`time` / `level` / `app` / `service` / `module` / `traceId` / `spanId` / `uid` /
+`bizType` / `opCode` / `code` / `message`。
+
+计划文档把这一组写成「11 字段」，但 PDD 原文逐字列出的名字是 **12 个**；本模块以 PDD 为准
+（`REQUIRED_LOG_FIELDS` 有 12 项，用例同时与字面量集合比对，改一个就要改两处）。
+
+**`spanId` 恒为空**：`design.md` D9 明确**不接 SkyWalking agent**（链路追踪后端留给平台级变更），
+故字段只为 schema 完整而输出、取值固定为空串——schema 完整、不假装有埋点。它由处理器强制赋值，
+调用方显式传值也不会放行（否则日志会反过来骗人）。
+
+**级别词表**：`DEBUG` / `INFO` / `WARNING` / `ERROR` / `CRITICAL`（一律大写，Python 口径）；
+`logger.exception(...)` 与 `logger.warn(...)` 分别归一为 `ERROR` / `WARNING`（别名归一见
+`_add_log_level`）。PDD 只钉了字段名没钉取值，本服务先取 Python 口径；主站 Logback 对告警级别
+的字面量是 `WARN`——两语言若要对齐字面量，属平台级裁定，届时两侧同时改，本服务不单方面改名。
+
+**`traceId` 单一来源**：只从 `core/trace.py` 的 `get_trace_id()` 取，本模块不另起实现；
+同时输出 `traceIdSource`（`propagated` / `generated`）——少了这个标记，「网关没注入」会被本地
+生成的 traceId 掩盖（Task 2.5 评审留下的半截要求在此补齐）。
+
+## 与 stdlib `logging` 的关系（不是二选一）
+
+structlog 只负责**事件收集与渲染**，落地仍走 stdlib：`structlog.stdlib.LoggerFactory()` 让
+`get_logger(module)` 拿到的是 stdlib 日志器，渲染由 root 上的
+`structlog.stdlib.ProcessorFormatter` 统一完成。于是：
+
+- 既有 `logging.getLogger(__name__).warning(...)` 的代码（如 `core/config.py` 规则 3 的告警）
+  **不改一行**就获得同一 schema——两条路径共用同一份处理器列表，不存在第二套字段口径；
+- 级别过滤、`caplog`、第三方库日志照常工作。
+
+**输出目标是 stderr**（stdlib `StreamHandler` 的默认目标）：stdout 留给程序自身输出，日志不与之
+混流；`uvicorn` 的错误日志同样走 stderr，采集侧一并收走。
+
+**级别设在服务自身的命名空间（`aicore`）上**，而不是 root：root 的级别会连带改变 httpx /
+sqlalchemy 等第三方库的级别——实测 httpx 的 INFO 会把完整请求 URL（含 query 里的用户输入）写进
+日志，那是顺手扩大泄漏面。第三方库保持各自默认级别，它们的 WARNING 及以上仍经 root 上的处理器
+渲染成同一 schema（处理器与级别是两件事）。
+
+**中文以 `\\uXXXX` 转义**（`JSONRenderer(ensure_ascii=True)`）：日志要在任意控制台 / 采集器里
+无损落地——stderr 在非 UTF-8 代码页（如 Windows 的 cp936）下会把裸中文按 GBK 编码，UTF-8 采集器
+读到的是**非法字节序列**（整行丢失，而不只是乱码）。纯 ASCII 输出没有这个依赖，JSON 解析器会把
+转义还原成中文。
+
+## MUST NOT 记录的内容（PDD §8.5.1 L1748）
+
+**明文密钥、支付敏感信息、原始图像（含 base64 与图像内容）、未脱敏证件字段**一律不得进入日志。
+业务代码只传结构化字段，MUST NOT 手工拼字符串——拼进字符串里的东西本模块识别不出来。
+
+两道兜底都不能替代上面的规矩：
+
+1. `uid` 一律经 `desensitize_uid()` 脱敏（保留首 3 末 4，其余打码）：schema 要求的
+   `uid（脱敏）` 由处理器强制执行，不指望每个调用方自觉；
+2. 密钥类**字段名**（`*_password` / `*_token` / `*_secret` / `*_api_key` …）的取值一律替换为
+   `***`：一次手滑的 `logger.info("配置", mysql_password=...)` 就会把口令永久写进日志文件。
+   只认字段名、不扫取值内容——按内容识别实体属于脱敏组件（正则 + 实体识别）的职责，
+   在这里重复实现只会造出第二套会漂移的口径。
+
+## 配置与关闭（两段式：引导 + 正式）
+
+组合根的 lifespan 按固定顺序调用两个函数，**两段式**是为了让进程的**第一行**日志也合 schema：
+
+1. `bootstrap_logging()` —— 进 lifespan 先调，**早于 `get_settings()`**。读配置本身就会写日志
+   （`core/config.py` 规则 3 的降级告警在 `Settings(...)` 构造瞬间发出），那时正式配置还不存在；
+   没有引导配置，这一行会落到 `logging.lastResort` 上变成**纯文本**，采集侧按 JSON 解析会整行丢掉。
+   引导用**文档化的最小默认值**（级别 `INFO`，`app` 取 `DEFAULT_APP_NAME`）——它读不到配置，
+   故 MUST NOT 依赖配置，`log_level` / `app_name` 只能等第二步生效；
+2. `configure_logging(settings)` —— 拿到配置后调，用配置里的 `log_level` / `app_name` 覆盖引导配置。
+
+两个函数**同一份 schema**：共用 `_assemble_handler` 与 `_shared_processors`，不存在「引导一种形状、
+正式另一种形状」的第二套字段口径。
+
+**幂等**：`configure_logging` 每次先摘掉上一次装的处理器再装新的；`bootstrap_logging` 在
+`configure_logging` 之后、以及被连续调用两次，同样只留一个处理器（新处理器替换旧的）。
+故「引导 + 正式」「正式 + 正式」「引导 + 引导」都不会重复输出。关闭钩子调 `flush_logging()` 刷盘。
+"""
+
+from __future__ import annotations
+
+import logging
+import sys
+from collections.abc import Iterator, Sequence
+from typing import Any, Final
+
+import structlog
+from structlog.typing import EventDict, Processor, WrappedLogger
+
+from aicore.core.config import Settings
+from aicore.core.trace import TRACE_SOURCE_FIELD, get_trace_id, get_trace_source
+
+#: 服务身份（日志字段 `service`）：平台内固定，不随部署名变化。
+SERVICE_NAME: Final = "aicore"
+
+#: 平台码表的成功码（PDD §6.2）：非错误路径的日志默认 `code = 0`。
+DEFAULT_CODE: Final = 0
+
+#: `spanId` 的固定取值：不接 SkyWalking（`design.md` D9），字段留空。
+SPAN_ID_EMPTY: Final = ""
+
+#: 打码后的替代值（不保留原值长度，避免「长度」本身也成信息）。
+REDACTED: Final = "***"
+
+#: 引导配置（`bootstrap_logging()`）的日志级别。
+#:
+#: 为什么是 `INFO` 而不是 `DEBUG`：引导阶段只有启动校验的告警会说话，`INFO` 收得住它们，
+#: 又不会把一个正常启动的进程刷成噪音；真实级别在 `AICORE_LOG_LEVEL` 里，第二步生效。
+BOOTSTRAP_LOG_LEVEL: Final = "INFO"
+
+#: 引导配置写进 `app` 字段的部署名（正式配置用 `settings.app_name`）。
+#:
+#: 引导**读不到配置**，故只能取固定值；这也是 `DEFAULT_CODE` / `SERVICE_NAME` 之外的第三个
+#: 「配置到位前的兜底取值」。代价是：若部署把 `AICORE_APP_NAME` 改成别的名字，启动的第一行
+#: 仍写 `aicore`——这是有意的取舍（宁可字段值在头几行与后面不同，也不让首行缺字段或非 JSON）。
+#: 三种「引导 + 正式」的实际取值组合见 tests/unit/test_logging.py 的用例。
+DEFAULT_APP_NAME: Final = SERVICE_NAME
+
+#: 脱敏 uid 时保留的首 / 尾位数。
+_UID_HEAD: Final = 3
+_UID_TAIL: Final = 4
+_UID_MASK: Final = "*"
+
+#: PDD §8.5.1 L1747 的必含字段，**逐字**。供用例与后续任务比对，MUST NOT 改名。
+REQUIRED_LOG_FIELDS: Final[frozenset[str]] = frozenset(
+    {
+        "time",
+        "level",
+        "app",
+        "service",
+        "module",
+        "traceId",
+        "spanId",
+        "uid",
+        "bizType",
+        "opCode",
+        "code",
+        "message",
+    }
+)
+
+#: 输出字段顺序：必含字段在前，附加字段（`traceIdSource` / `exception` 等）在后。
+#: 固定顺序让每行的字段位置一致，采集侧与人工排障都不必猜「这行的 time 在哪」。
+_FIELD_ORDER: Final[tuple[str, ...]] = (
+    "time",
+    "level",
+    "app",
+    "service",
+    "module",
+    "traceId",
+    TRACE_SOURCE_FIELD,
+    "spanId",
+    "uid",
+    "bizType",
+    "opCode",
+    "code",
+    "message",
+)
+
+#: **精确匹配**即视为密钥的字段名（含各通道密钥字段的裸名写法）。
+_SENSITIVE_FIELD_NAMES: Final[frozenset[str]] = frozenset(
+    {
+        "password",
+        "passwd",
+        "pwd",
+        "secret",
+        "token",
+        "api_key",
+        "apikey",
+        "authorization",
+        "credential",
+        "credentials",
+        "private_key",
+        "access_token",
+        "refresh_token",
+        "id_token",
+    }
+)
+
+#: 以这些后缀结尾即视为密钥（`mysql_password` / `internal_token` / `deepseek_api_key` …）。
+#: 刻意不做子串匹配：`token_count` / `total_tokens` / `max_tokens` 是 LLM 成本护栏的核心数据，
+#: 抹掉它们等于把可观测性一起抹掉。
+_SENSITIVE_FIELD_SUFFIXES: Final[tuple[str, ...]] = (
+    "_password",
+    "_passwd",
+    "_secret",
+    "_token",
+    "_api_key",
+    "_credential",
+    "_credentials",
+)
+
+
+def desensitize_uid(value: object) -> str:
+    """脱敏 uid：保留首 3 位与末 4 位，其余打码。
+
+    PDD §8.5.1 要求日志里的 `uid` 是**脱敏**值，而 uid 常常就是证件号 / 手机号 / 账号。
+    本函数是这条要求的唯一实现，处理器对每条记录强制执行，故调用方传原值也不会漏出去。
+
+    长度不足（≤ 首尾保留位数之和）时**整串打码**：此时「保留首尾」等于几乎没脱敏。
+    非字符串取值先转成字符串再脱敏（形如整数的 uid 同样不能原样落盘）；`None` 与空串保持空。
+    """
+    if value is None:
+        return ""
+    text = value if isinstance(value, str) else str(value)
+    if not text:
+        return ""
+    if len(text) <= _UID_HEAD + _UID_TAIL:
+        return _UID_MASK * len(text)
+    masked = len(text) - _UID_HEAD - _UID_TAIL
+    return f"{text[:_UID_HEAD]}{_UID_MASK * masked}{text[-_UID_TAIL:]}"
+
+
+def _add_log_level(logger: WrappedLogger, method_name: str, event_dict: EventDict) -> EventDict:
+    """`level`：先按 structlog 的别名表归一，再转大写（`INFO` / `ERROR`，与主站 SLF4J 同口径）。
+
+    别名归一**不能省**：`logger.exception(...)` 传下来的方法名是 `exception`，直接大写会得到
+    `EXCEPTION`——它不在平台级别词表里（主站与 PDD 用的是 SLF4J 的 TRACE/DEBUG/INFO/WARN/ERROR），
+    采集侧按级别过滤时会把这一类错误日志**整批漏掉**。这里复用 structlog 自己的别名表
+    （`exception`→`error`、`warn`→`warning`，见 `structlog._log_levels.map_method_name`），
+    只在其结果上做大写转换，不另写一张会漂移的别名表。
+
+    大写是主站口径：Java 侧 Logback `%level` 输出的就是 `INFO` / `ERROR`。
+    """
+    structured = structlog.stdlib.add_log_level(logger, method_name, event_dict)
+    structured["level"] = str(structured["level"]).upper()
+    return structured
+
+
+def _bind_module(logger: WrappedLogger, method_name: str, event_dict: EventDict) -> EventDict:
+    """`module` 必含：structlog 路径由 `get_logger(module)` 绑定，stdlib 路径取日志器名。
+
+    stdlib 记录（`ProcessorFormatter` 的 foreign 路径）的事件字典里带着 `_record`，
+    日志器名就在它身上；两条路径合起来保证这个字段永不为空。
+    """
+    if "module" not in event_dict:
+        record = event_dict.get("_record")
+        event_dict["module"] = getattr(record, "name", "") or ""
+    return event_dict
+
+
+def _add_trace_context(
+    logger: WrappedLogger, method_name: str, event_dict: EventDict
+) -> EventDict:
+    """`traceId` / `traceIdSource`：唯一来源是 `core/trace.py`（此处不另起实现）。
+
+    请求内取到网关注入的值（`propagated`），请求外或网关漏注入时自行生成（`generated`）。
+    """
+    event_dict["traceId"] = get_trace_id()
+    event_dict[TRACE_SOURCE_FIELD] = get_trace_source()
+    return event_dict
+
+
+def _force_empty_span_id(
+    logger: WrappedLogger, method_name: str, event_dict: EventDict
+) -> EventDict:
+    """`spanId` **恒为空**：不接 SkyWalking（`design.md` D9），字段只为 schema 完整。
+
+    强制赋值而非 `setdefault`：一旦允许调用方填值，日志里就会出现无人维护的假 spanId，
+    「没接链路追踪」这件事会被日志掩盖。
+    """
+    event_dict["spanId"] = SPAN_ID_EMPTY
+    return event_dict
+
+
+def _mask_uid(logger: WrappedLogger, method_name: str, event_dict: EventDict) -> EventDict:
+    """`uid` 强制脱敏：schema 写的是 `uid（脱敏）`，不能指望每个调用方自觉。"""
+    event_dict["uid"] = desensitize_uid(event_dict.get("uid"))
+    return event_dict
+
+
+def _is_sensitive_field_name(name: str) -> bool:
+    """字段名是否属于「取值绝不能进日志」的那一类（精确名 or 后缀，见上面两张表）。"""
+    lowered = name.lower()
+    return lowered in _SENSITIVE_FIELD_NAMES or lowered.endswith(_SENSITIVE_FIELD_SUFFIXES)
+
+
+def _redact_sensitive_fields(
+    logger: WrappedLogger, method_name: str, event_dict: EventDict
+) -> EventDict:
+    """密钥类字段打码（兜底防线，不能替代「不要把密钥传给日志」这条规矩）。"""
+    for key in list(event_dict):
+        if isinstance(key, str) and _is_sensitive_field_name(key):
+            event_dict[key] = REDACTED
+    return event_dict
+
+
+def _order_fields(logger: WrappedLogger, method_name: str, event_dict: EventDict) -> EventDict:
+    """按 `_FIELD_ORDER` 重排：必含字段在前、附加字段在后（渲染前最后一个语义处理器）。"""
+    ordered: dict[str, object] = {
+        key: event_dict[key] for key in _FIELD_ORDER if key in event_dict
+    }
+    ordered.update((key, value) for key, value in event_dict.items() if key not in ordered)
+    return ordered
+
+
+class _SchemaDefaults:
+    """补齐必含字段里「与单条记录无关」的那些：`app` / `service` 与业务字段默认值。
+
+    写成可调用对象（而不是闭包）是为了让 mypy 按 `Processor` 协议校验签名，同时把
+    `settings.app_name` 在装配期就固定下来——渲染期不再读配置（配置只解析一次）。
+
+    `app` / `service` 用**赋值**而非 `setdefault`：这两个字段是 schema 身份，调用方覆盖只会
+    制造「同一进程出现两个服务名」的脏数据。`uid` / `bizType` / `opCode` / `code` 用默认值，
+    业务代码按需传。
+    """
+
+    __slots__ = ("_app",)
+
+    def __init__(self, app: str) -> None:
+        self._app = app
+
+    def __call__(self, logger: WrappedLogger, method_name: str, event_dict: EventDict) -> EventDict:
+        event_dict["app"] = self._app
+        event_dict["service"] = SERVICE_NAME
+        event_dict.setdefault("uid", "")
+        event_dict.setdefault("bizType", "")
+        event_dict.setdefault("opCode", "")
+        event_dict.setdefault("code", DEFAULT_CODE)
+        return event_dict
+
+
+class _JsonStreamHandler(logging.StreamHandler[Any]):
+    """把 JSON 行写到**当前** `sys.stderr` 的处理器。
+
+    为什么每次 `emit` 重新解析 `sys.stderr` 而不在构造时绑定：pytest 的 capsys / capfd 会在
+    用例期间替换 `sys.stderr`、并在用例结束**关闭**被替换的对象。构造时抓到的引用会变成
+    「已关闭的流」，之后每次写日志都抛 `ValueError`（`logging` 会打印 `--- Logging error ---`
+    污染输出）。惰性解析让处理器永远写向「当下」的输出流。
+
+    泛型参数只为满足 mypy：`logging.StreamHandler` 自 Python 3.11 起可下标
+    （CPython gh-92128），本仓库下限 3.12，故这行在运行时同样成立。
+    """
+
+    def __init__(self) -> None:
+        super().__init__(sys.stderr)
+
+    def emit(self, record: logging.LogRecord) -> None:
+        self.stream = sys.stderr
+        super().emit(record)
+
+
+def _iter_installed_handlers() -> Iterator[_JsonStreamHandler]:
+    """本模块装在 root 上的处理器（按类型识别，不依赖模块级引用）。"""
+    for handler in logging.getLogger().handlers:
+        if isinstance(handler, _JsonStreamHandler):
+            yield handler
+
+
+def _remove_installed_handlers() -> None:
+    """摘掉上一次装的处理器——可重复配置的关键，否则每行日志会被渲染多份。"""
+    root = logging.getLogger()
+    for handler in list(_iter_installed_handlers()):
+        root.removeHandler(handler)
+        handler.close()
+
+
+def _resolve_level(name: str) -> int:
+    """把配置里的级别名解析成 `logging` 级别；非法值当场报错，不静默退回 INFO。
+
+    静默兜底正是「以为配了其实没配」那类故障（与 `core/config.py` 不给必填项默认值同一取向）。
+    `NOTSET` 也判非法：它的语义是「未设置」，拿它当服务日志级别没有意义。
+    """
+    level = logging.getLevelNamesMapping().get(name.strip().upper())
+    if level is None or level <= 0:
+        raise ValueError(
+            f"AICORE_LOG_LEVEL 取值非法：{name!r}；"
+            "应为 DEBUG / INFO / WARNING / ERROR / CRITICAL 之一"
+        )
+    return level
+
+
+def _shared_processors(app: str) -> list[Processor]:
+    """两条路径共用的事件字典处理器。
+
+    structlog 记录在**调用期**跑这一串（再交给 `wrap_for_formatter` 打包）；
+    stdlib 记录在**格式化期**由 `ProcessorFormatter` 的 `foreign_pre_chain` 跑同一串。
+    因此两侧的字段补齐、脱敏、traceId 注入完全一致，不存在第二套 schema。
+    """
+    return [
+        _add_log_level,
+        _bind_module,
+        _add_trace_context,
+        _SchemaDefaults(app),
+        _force_empty_span_id,
+        _mask_uid,
+        _redact_sensitive_fields,
+        structlog.processors.TimeStamper(fmt="iso", utc=True, key="time"),
+        structlog.processors.format_exc_info,
+        structlog.processors.UnicodeDecoder(),
+    ]
+
+
+def _assemble_handler(shared: Sequence[Processor], level: int) -> _JsonStreamHandler:
+    """装配一个完整的 JSON 行处理器（schema、级别、格式器一次到位）。
+
+    引导配置与正式配置的**唯一**区别就是入参（`shared` 里的 `app` 与 `level`）：处理器类型、
+    字段顺序、脱敏、traceId 注入全部走同一条装配路径，故两段配置产出的 schema 逐字相同
+    ——否则「首行非 JSON」只是被换成了「首行是另一套 JSON」，问题没解决只是搬了家。
+    """
+    formatter = structlog.stdlib.ProcessorFormatter(
+        # stdlib 记录先补齐 schema 与 traceId，再进下面的渲染链。
+        foreign_pre_chain=list(shared),
+        processors=[
+            # 摘掉 `_record` / `_from_structlog`（LogRecord 不是 JSON 可序列化对象）。
+            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
+            # `event` → `message`（schema 字段名；放在重排之前，位置才落在末尾）。
+            structlog.processors.EventRenamer("message"),
+            _order_fields,
+            # ensure_ascii=True 是刻意的：见模块 docstring「中文以 \uXXXX 转义」。
+            structlog.processors.JSONRenderer(ensure_ascii=True),
+        ],
+    )
+    handler = _JsonStreamHandler()
+    handler.setFormatter(formatter)
+    handler.setLevel(level)
+    return handler
+
+
+def _apply_json_logging(app: str, level: int) -> None:
+    """装配 JSON 日志的**完整**动作：structlog 全局配置 + root 处理器 + 服务命名空间级别。
+
+    `bootstrap_logging()` 与 `configure_logging()` 都只调这一个函数，区别仅在入参
+    （引导给文档化的默认值，正式给配置里的值）。故下面三步的取向对两段配置同样成立：
+
+    ① 「先摘旧的、再挂新的」是可重复配置的关键：否则每行日志会被渲染多份
+       （「引导 + 正式」「正式 + 正式」都会踩到）；
+    ② 级别设在服务命名空间上、**不动 root**（见 `configure_logging` 的 docstring）；
+    ③ 全程**不读任何配置**，因此可以在 `get_settings()` 之前调用（引导配置正是这么用的）。
+    """
+    shared = _shared_processors(app)
+
+    structlog.configure(
+        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
+        logger_factory=structlog.stdlib.LoggerFactory(),
+        wrapper_class=structlog.stdlib.BoundLogger,
+        # 不缓存：本函数允许重复调用（测试隔离、配置重载），缓存会让已建好的日志器继续用旧配置，
+        # 表现为「重新配置后日志还是老格式」这类极难排查的问题。
+        cache_logger_on_first_use=False,
+    )
+
+    handler = _assemble_handler(shared, level)
+    _remove_installed_handlers()
+
+    root = logging.getLogger()
+    root.addHandler(handler)
+    # SERVICE_NAME 同时是包名，即本服务全部日志器的命名空间（业务代码按 `__name__` 取日志器）。
+    logging.getLogger(SERVICE_NAME).setLevel(level)
+
+
+def bootstrap_logging() -> None:
+    """装一套**不依赖配置**的引导日志配置（组合根的 lifespan 启动钩子第一件事）。
+
+    为什么必须有它：`core/config.py` 规则 3 的降级告警在 `Settings(...)` **构造瞬间**发出，
+    而正式配置要等 `get_settings()` 返回之后才存在。没有引导配置，进程的第一行日志会落到
+    `logging.lastResort` 上变成**纯文本**（生产下 root 无处理器）——采集侧按 JSON 解析会整行
+    丢掉，正是「统一结构化日志」要防的那种漏。
+
+    取值是**文档化的最小默认**：级别 `BOOTSTRAP_LOG_LEVEL`（`INFO`）、`app` 取
+    `DEFAULT_APP_NAME`。MUST NOT 依赖 `Settings`（此刻读不到，读它只是把顺序问题搬个地方）；
+    `log_level` / `app_name` 由随后的 `configure_logging(settings)` 覆盖。
+
+    可重复调用（幂等）：每次都先摘掉自己上一次装的处理器，故「引导 + 正式」「引导 + 引导」
+    都不会让每行日志输出两份。schema 与正式配置逐字相同（共用 `_assemble_handler`）。
+    """
+    _apply_json_logging(DEFAULT_APP_NAME, _resolve_level(BOOTSTRAP_LOG_LEVEL))
+
+
+def configure_logging(settings: Settings) -> None:
+    """按配置装配结构化 JSON 日志（组合根的 lifespan 启动钩子调用）。
+
+    **可重复调用**：每次先摘掉上一次装的处理器，再装新的，故不会出现「配置两次、每行输出两份」。
+    这一条对「`bootstrap_logging()` 之后再 `configure_logging()`」同样成立（见模块 docstring）。
+    非法 `log_level` 在动任何全局状态**之前**就抛错，已生效的配置保持可用。
+
+    **级别设在服务自身的命名空间（`aicore`）上，不是 root**：root 的级别会连带改变
+    httpx / sqlalchemy 等第三方库的日志级别——实测 httpx 的 INFO 会把**完整请求 URL**
+    （含 query 里的用户输入）打进日志，那是顺手扩大泄漏面。第三方库保持各自默认级别，
+    它们的 WARNING 及以上仍会经 root 上的处理器渲染成同一 schema（处理器与级别是两件事）。
+
+    处理器同时设级别（与日志器一致）：兜住「别的代码把某个 logger 的级别调松」的情况。
+    """
+    level = _resolve_level(settings.log_level)
+    _apply_json_logging(settings.app_name, level)
+
+
+def get_logger(module: str) -> structlog.stdlib.BoundLogger:
+    """取某个模块的日志器（业务代码写日志的**唯一**入口）。
+
+    - `module` 惯例传 `__name__`：它既作为 stdlib 日志器名（级别过滤、`caplog` 按它工作），
+      也绑进日志的 `module` 字段；
+    - 返回类型是 `structlog.stdlib.BoundLogger`，但拿到手时是 structlog 的**惰性代理**：
+      首次调用日志方法才装配，故「先建日志器、后 `configure_logging`」也没问题
+      （模块顶层 `_logger = get_logger(__name__)` 是标准写法）；
+    - MUST NOT 用它手工拼字符串：只传结构化字段（`bizType` / `opCode` / `code` / `uid` …），
+      拼接会把密钥、原始图像之类的东西绕过本模块的脱敏与打码。
+    """
+    return structlog.stdlib.get_logger(module, module=module)
+
+
+def flush_logging() -> None:
+    """刷出并刷新本模块安装的处理器（关闭钩子的最小正确动作）。
+
+    只刷自己的处理器：`logging.shutdown()` 会关闭**全部**处理器（含 pytest / uvicorn 挂的），
+    进程内再写日志就会撞上已关闭的流——代价远大于「关闭时刷一下盘」这件事本身。
+    """
+    for handler in _iter_installed_handlers():
+        handler.flush()
diff --git a/services/aicore/src/aicore/main.py b/services/aicore/src/aicore/main.py
index a496d55..25901b4 100644
--- a/services/aicore/src/aicore/main.py
+++ b/services/aicore/src/aicore/main.py
@@ -2,40 +2,80 @@

 **唯一允许把具体 Provider / repository 实现注入 service 的位置。**
 其余各层 MUST NOT 自行构造具体实现（由 `.importlinter` 的 import-linter 契约强制）。

 路由路径不含 `/api/v1` 前缀：GATEWAY 已用 RewritePath 去前缀，
 故本服务路由与 openapi.yaml 一致，为 `/aicore/**` 与 `/health`。
 """

 from __future__ import annotations

+import logging
 from collections.abc import AsyncIterator
 from contextlib import asynccontextmanager

 from fastapi import FastAPI
+from pydantic import ValidationError
 from starlette.types import ASGIApp

 from aicore import __version__
 from aicore.api import health
+from aicore.core.config import ConfigRejected, get_settings
 from aicore.core.errors import register_exception_handlers
+from aicore.core.logging import bootstrap_logging, configure_logging, flush_logging
 from aicore.core.trace import TraceIdMiddleware

+# stdlib 日志器（与 `core/config.py` / `core/errors.py` 同一写法）：本模块的日志少而关键，
+# 且 stdlib 记录会被 root 上的 JSON 处理器收编，schema 与业务日志逐字一致。
+_logger = logging.getLogger(__name__)
+

 @asynccontextmanager
 async def lifespan(app: FastAPI) -> AsyncIterator[None]:
-    """启动与关闭钩子。
-
-    启动即校验配置（Task 2.2）、装配依赖（Task 3.4 起）、
-    启动任务执行器（第 4 组）都将挂在这里。
+    """启动与关闭钩子（第 2 组的收口位置）。
+
+    顺序是硬要求：
+
+    1. **先装引导日志配置**（`bootstrap_logging()`，Task 2.6 修复轮 1）——它不读配置，故能在
+       读配置**之前**跑；没有这一步，第 2 步构造 `Settings` 时发出的规则 3 告警会缺少 JSON
+       处理器，落成纯文本（进程的第一行日志不合 schema）；
+    2. 读配置（`get_settings()`，进程内只解析一次）。失败即**拒绝启动**——先把阻断项清单写进
+       一条结构化 ERROR 日志（此刻引导配置已就位，故这一行同样是 JSON），再抛
+       `ConfigRejected`，进程起不来本身就是「拒绝启动」。为什么在抛出前还写一条日志：
+       uvicorn 的启动失败栈是**框架的** stderr 明文输出，不进本服务的 JSON 管线；拒绝启动
+       恰恰是最该被日志采集器看见的事件（否则它只在运维翻 stderr 时才存在）。记录的内容
+       `str(exc)` 只含字段名 / 环境变量名 / 阈值数字，**不含任何配置取值**（见 `core/config.py`）；
+    3. 按配置装配结构化 JSON 日志（Task 2.6）——配置里的 `log_level` / `app_name` 在此覆盖
+       引导配置的默认值（两者共用同一套 schema 与同一份处理器装卸逻辑，故不重复输出）；
+    4. `yield`：进程存活期；
+    5. 关闭时刷日志处理器（只刷本服务的，不做别的生命周期工作）。
+
+    **必须 `raise ... from None`**：`from exc` 会把 `__cause__` 设成原始 `ValidationError`，
+    而 uvicorn 记录 lifespan 启动失败时带 `exc_info`，`str(ValidationError)` 会回显
+    （截断后的）`input_value`——那里面含 `mysql_password` 等原始值。异常链因此会成为一条绕过
+    「只用 loc/msg」的泄漏通道。完整推理见 `core/config.py` 模块 docstring。
+    （引导配置不改变这一点：它只装日志处理器，不碰异常链。）
+    上面那条 ERROR 日志同样只记 `str(ConfigRejected)`——它与异常消息同源，故同一份保证覆盖它。
+
+    依赖装配（Task 3.4 起）与任务执行器（第 4 组）仍将挂在这里；本任务只做配置与日志。
     """
+    bootstrap_logging()
+    try:
+        settings = get_settings()
+    except ValidationError as exc:
+        rejected = ConfigRejected.from_validation_error(exc)
+        # 阻断项清单已是「可直接打印、不含取值」的多行摘要；JSON 渲染会把换行转义，仍是一行。
+        _logger.error("%s", rejected)
+        raise rejected from None
+    configure_logging(settings)
     yield
+    flush_logging()


 class _TracedFastAPI(FastAPI):
     """把 traceId 中间件包在**整条 ASGI 栈之外**的应用类。

     为什么不用 `app.add_middleware(TraceIdMiddleware)`：Starlette 固定把用户中间件
     插在 ServerErrorMiddleware **之内**（starlette/applications.py 的
     build_middleware_stack：`[ServerErrorMiddleware] + user_middleware + [ExceptionMiddleware]`）。
     未捕获异常由 ServerErrorMiddleware 在最外层渲染成 500，那条路径会失守两处：

diff --git a/services/aicore/tests/unit/test_logging.py b/services/aicore/tests/unit/test_logging.py
new file mode 100644
index 0000000..9e44afe
--- /dev/null
+++ b/services/aicore/tests/unit/test_logging.py
@@ -0,0 +1,1122 @@
+"""结构化 JSON 日志用例（Task 2.6）。
+
+全部驱动**真实**日志链路（真处理器、真 JSON 序列化、真 stdlib 日志器），不 mock 处理器：
+
+1. PDD §8.5.1 L1747 的 12 项必含字段逐字落在真实发出的记录上；同时与字面量集合比对
+   —— 实现里的常量被改名/删项时，两边必须同时改，不存在「常量改了就悄悄放过」；
+2. `spanId` **存在且恒为空**：`design.md` D9 不接 SkyWalking agent，字段只为 schema 完整，
+   调用方显式传入也不放行（防「假装有埋点」）；
+3. 输出是「一行一个 JSON 对象」，且 level / message / time 取值正确；
+4. `traceId` 与 `traceIdSource` 单一来源于 `core/trace.py`：走真实请求时等于网关注入的
+   `X-Request-Id` 且标 `propagated`，无头时自行生成并标 `generated`
+   —— 这一对是 Task 2.5 评审遗留项「生成行为需在日志中可区分」的验收证据；
+5. stdlib `logging`（Task 2.2 的规则 3 告警走它）被**同一条** JSON 管线收编，schema 一致；
+6. 不落敏感信息：`uid` 脱敏（形似证件号的原始值不得出现）、密钥类字段一律打码，
+   并有「非密钥字段不被误抹」的阴性对照；
+7. 生命周期接线：重复 `configure_logging` 不产生重复处理器 / 不重复输出；启动配置非法时抛
+   `ConfigRejected`（不是裸 `ValidationError`）且异常链里没有口令；关闭时刷盘；
+   `create_app()` 在 `AICORE_*` 全清空时依然可建实例；
+8. **引导配置**（修复轮 1）：进 lifespan 先装一套不依赖配置的 JSON 日志，使「读配置阶段发出的
+   第一行日志」也是同一 schema 的 JSON——正式配置随后覆盖它，且两者叠加不重复输出。
+
+用例隔离（本任务把日志配置成**全局**状态，必须自己收拾干净）：自动夹具在每个用例结束后
+移除「本用例新挂到 root 的处理器」、还原 root 级别并清 `get_settings()` 缓存，使同一进程内
+反复运行不累积处理器、不重复输出。
+
+取值一律 `test_*` / `SENTINEL_*` 占位符，MUST NOT 出现真实凭据；不使用 sleep。
+"""
+
+from __future__ import annotations
+
+import json
+import logging
+import os
+import re
+import traceback
+from collections.abc import Iterator
+from datetime import datetime, timedelta
+from typing import Any, Final
+
+import pytest
+import structlog
+from fastapi import FastAPI
+from fastapi.testclient import TestClient
+from pydantic import ValidationError
+
+from aicore.core import config as config_module
+from aicore.core.config import ConfigRejected, Settings, clear_settings_cache
+from aicore.core.logging import (
+    BOOTSTRAP_LOG_LEVEL,
+    DEFAULT_APP_NAME,
+    REQUIRED_LOG_FIELDS,
+    SERVICE_NAME,
+    bootstrap_logging,
+    configure_logging,
+    desensitize_uid,
+    flush_logging,
+    get_logger,
+)
+from aicore.core.trace import (
+    TRACE_ID_HEADER,
+    TRACE_SOURCE_FIELD,
+    TRACE_SOURCE_GENERATED,
+    TRACE_SOURCE_PROPAGATED,
+    reset_trace_id,
+)
+from aicore.main import create_app
+
+#: `core/config.py` 的 stdlib 日志器名（取自模块本身，避免与实现漂移）。
+CONFIG_MODULE: Final = config_module.__name__
+
+#: 组合根 lifespan 的 stdlib 日志器名（拒绝启动的那条 ERROR 记录来自它）。
+LIFESPAN_MODULE: Final = "aicore.main"
+
+#: 探针模块名：本文件发出的日志都挂在它下面，便于把「第三方库的日志行」滤掉。
+PROBE_MODULE: Final = "aicore.__probe__.logging"
+
+#: 探针路由：请求内写一行日志，用于验证 traceId 从请求头走到日志字段。
+PROBE_PATH: Final = "/__probe__/logging"
+
+TRACE_ID_PATTERN: Final = re.compile(r"^[0-9a-f]{16}$")
+
+#: `_common` 的示例 traceId，同时也是合法的注入值。
+INJECTED_TRACE_ID: Final = "3f2a1b9c8d7e6f50"
+
+#: 形状像 18 位居民身份证号的**测试哨兵**（非真实证件号，校验位无意义）。
+CERT_NUMBER_SENTINEL: Final = "110101199003070011"
+CERT_NUMBER_MASKED: Final = "110***********0011"
+
+#: 秘密哨兵：任何一条出现在日志输出里都说明脱敏防线失守。
+PASSWORD_SENTINEL: Final = "SENTINEL_PASSWORD_DO_NOT_LEAK"
+TOKEN_SENTINEL: Final = "SENTINEL_INTERNAL_TOKEN_DO_NOT_LEAK"
+CHANNEL_KEY_SENTINEL: Final = "SENTINEL_DEEPSEEK_KEY_DO_NOT_LEAK"
+SECRET_SENTINELS: Final = (PASSWORD_SENTINEL, TOKEN_SENTINEL, CHANNEL_KEY_SENTINEL)
+
+#: PDD §8.5.1 L1747 的必含字段**字面量**（不是从实现里的常量派生出来的）。
+#: 两边独立写死：实现改常量、或本文件改字面量，都必须有人同时改另一处。
+MANDATED_FIELDS_LITERAL: Final = frozenset(
+    {
+        "time",
+        "level",
+        "app",
+        "service",
+        "module",
+        "traceId",
+        "spanId",
+        "uid",
+        "bizType",
+        "opCode",
+        "code",
+        "message",
+    }
+)
+
+
+def _test_settings(**overrides: object) -> Settings:
+    """测试用配置：只给 `test_*` 占位值、不读 `.env`，且默认组合**不触发**规则 3 告警。
+
+    默认走 `dev + deepseek + 占位密钥`：真实通道有密钥即不告警、`provider != mock` 也不告警，
+    于是构造本身不会往日志里多写一行（本文件多处断言「捕获到的每一行都是 JSON 且属于本次调用」）。
+    """
+    base: dict[str, object] = {
+        "env": "dev",
+        "provider": "deepseek",
+        "deepseek_api_key": "test_deepseek_placeholder",
+        "mysql_host": "127.0.0.1",
+        "mysql_user": "test_user",
+        "mysql_password": "test_password",
+        "mysql_database": "aicore_test",
+        "redis_host": "127.0.0.1",
+        "internal_token": "test_internal_token",
+        "daily_quota_per_account": 1000,
+        "daily_budget_total": 100000,
+    }
+    base.update(overrides)
+    return Settings(_env_file=None, **base)
+
+
+def _probe_app() -> FastAPI:
+    """全新应用 + 探针路由：请求内按业务代码的方式写一行结构化日志。"""
+    app = create_app()
+
+    @app.get(PROBE_PATH, include_in_schema=False)
+    async def _probe() -> dict[str, str]:
+        get_logger(PROBE_MODULE).info(
+            "探针：请求内日志",
+            bizType="probe",
+            opCode="logging.probe",
+            code=0,
+        )
+        return {"ok": "1"}
+
+    return app
+
+
+@pytest.fixture(autouse=True)
+def _isolated_global_logging_state() -> Iterator[None]:
+    """用例隔离：本任务改动的是**进程级**日志状态，必须在每个用例后还原。
+
+    ① traceId 上下文（ContextVar 在 pytest 主线程里跨用例存活）；
+    ② root 上的处理器：只移除本用例新增的，并还原 root 与服务命名空间的级别；
+    ③ `get_settings()` 缓存：用例可能改过环境变量，缓存清掉以免串味。
+    """
+    root = logging.getLogger()
+    service_logger = logging.getLogger(SERVICE_NAME)
+    handlers_before = list(root.handlers)
+    root_level_before = root.level
+    service_level_before = service_logger.level
+    reset_trace_id()
+    yield
+    reset_trace_id()
+    for handler in list(root.handlers):
+        if handler not in handlers_before:
+            root.removeHandler(handler)
+            handler.close()
+    root.setLevel(root_level_before)
+    service_logger.setLevel(service_level_before)
+    clear_settings_cache()
+
+
+@pytest.fixture
+def settings() -> Settings:
+    return _test_settings()
+
+
+@pytest.fixture
+def probe_logger(settings: Settings) -> structlog.stdlib.BoundLogger:
+    """配置好日志后的探针日志器（每次用例都重新配置，互不继承）。"""
+    configure_logging(settings)
+    return get_logger(PROBE_MODULE)
+
+
+def _json_records(text: str) -> list[dict[str, Any]]:
+    """把捕获到的输出逐行解析成 JSON 对象；**任何一行不是 JSON 都会让用例失败**。"""
+    records: list[dict[str, Any]] = []
+    for line in text.splitlines():
+        if not line.strip():
+            continue
+        parsed = json.loads(line)
+        assert isinstance(parsed, dict), f"日志行不是 JSON 对象：{line!r}"
+        records.append(parsed)
+    return records
+
+
+def _probe_records(text: str) -> list[dict[str, Any]]:
+    """只保留探针模块发出的记录（root 处理器会连带收编 httpx 等第三方日志）。"""
+    return [record for record in _json_records(text) if record.get("module") == PROBE_MODULE]
+
+
+def _assert_every_line_is_json(text: str) -> list[dict[str, Any]]:
+    """逐行断言 `text` 里**每一行**都是 JSON 对象（不是抽查某一行），返回解析结果。
+
+    `pytest` 的 `capsys` 抓不住直接写 `sys.stderr` 的字节，故不能拿「`sys.stderr` 被替换过」
+    当判据；这里改用 `json.loads` 作为判据并在失败时报出原始行——修复前的那一行
+    （`[告警：env-mock] …` 纯文本）会当场被点出来。
+    """
+    records: list[dict[str, Any]] = []
+    for line in text.splitlines():
+        if not line.strip():
+            continue
+        try:
+            parsed = json.loads(line)
+        except json.JSONDecodeError as exc:
+            raise AssertionError(f"日志行不是合法 JSON（{exc.msg}）：{line!r}") from exc
+        assert isinstance(parsed, dict), f"日志行不是 JSON 对象：{line!r}"
+        records.append(parsed)
+    return records
+
+
+def _only_probe_record(text: str) -> dict[str, Any]:
+    records = _probe_records(text)
+    assert len(records) == 1, f"探针记录应恰好一条，实际 {len(records)} 条：{records}"
+    return records[0]
+
+
+def _added_handlers(handlers_before: list[logging.Handler]) -> list[logging.Handler]:
+    return [handler for handler in logging.getLogger().handlers if handler not in handlers_before]
+
+
+def _config_module_records(text: str) -> list[dict[str, Any]]:
+    """只保留 stdlib 告警所在的 `core/config.py` 日志器发出的记录。"""
+    return [record for record in _json_records(text) if record.get("module") == CONFIG_MODULE]
+
+
+# ---------------------------------------------------------------------------
+# 1. 必含字段 schema
+# ---------------------------------------------------------------------------
+
+
+def test_required_log_fields_match_the_mandated_schema() -> None:
+    """字段名与 PDD §8.5.1 L1747 **逐字一致**，12 项一个不多一个不少。
+
+    `REQUIRED_LOG_FIELDS` 是给后续任务与评审比对用的公开常量；本用例把它与字面量集合钉在
+    一起，故「实现里删掉一个字段」或「本文件手滑改字面量」都必须有人同时改另一处。
+    """
+    assert REQUIRED_LOG_FIELDS == MANDATED_FIELDS_LITERAL
+    assert len(REQUIRED_LOG_FIELDS) == 12
+    assert isinstance(REQUIRED_LOG_FIELDS, frozenset)
+
+
+def test_emitted_record_carries_every_mandated_field(capsys: pytest.CaptureFixture[str]) -> None:
+    """调用方只给 message，必含字段也一个不少（其余由处理器补齐）。
+
+    这是「schema 完整」的承重用例：任何一项缺失都会被点名，而不是只报一个 not-in。
+    """
+    configure_logging(_test_settings())
+    get_logger(PROBE_MODULE).info("探针：只给 message")
+
+    record = _only_probe_record(capsys.readouterr().err)
+
+    missing = REQUIRED_LOG_FIELDS - set(record)
+    assert not missing, f"日志缺少必含字段：{sorted(missing)}"
+    assert all(record[field] is not None for field in REQUIRED_LOG_FIELDS)
+
+
+def test_error_record_with_traceback_stays_one_json_line(
+    capsys: pytest.CaptureFixture[str],
+) -> None:
+    """带异常堆栈的 ERROR 记录**仍是一行一个 JSON 对象**，堆栈落进 `exception` 字段。
+
+    PDD §8.5.1 L1748 要求「ERROR 必须携带可定位上下文」，而堆栈是多行文本——若渲染时
+    不转义，一行日志会裂成几十行，采集侧按行解析的假设当场失效（整条记录报废）。
+    `format_exc_info` + JSON 字符串转义把堆栈压进一个字段，两个要求同时满足。
+    """
+    configure_logging(_test_settings())
+    try:
+        raise RuntimeError("探针：模拟通道失败")
+    except RuntimeError:
+        get_logger(PROBE_MODULE).exception("通道调用失败", bizType="ocr", opCode="ocr.recognize")
+
+    text = capsys.readouterr().err
+    lines = [line for line in text.splitlines() if line.strip()]
+    assert len(lines) == 1, f"带堆栈的记录裂成了 {len(lines)} 行"
+
+    record = _json_records(text)[0]
+    assert set(record) >= REQUIRED_LOG_FIELDS
+    assert record["level"] == "ERROR"
+    assert "RuntimeError" in str(record["exception"]), "堆栈未落进 exception 字段"
+    assert record["code"] == 0  # 调用方没给错误码，取平台默认值
+
+
+def test_caller_structured_fields_round_trip(capsys: pytest.CaptureFixture[str]) -> None:
+    """业务代码只传结构化字段（不手工拼字符串），字段原样出现在记录里。"""
+    configure_logging(_test_settings())
+    get_logger(PROBE_MODULE).info(
+        "探针：结构化字段",
+        bizType="ocr",
+        opCode="ocr.recognize",
+        code=4003,
+        uid="test_uid_0001",
+    )
+
+    record = _only_probe_record(capsys.readouterr().err)
+
+    assert record["bizType"] == "ocr"
+    assert record["opCode"] == "ocr.recognize"
+    assert record["code"] == 4003
+    assert record["message"] == "探针：结构化字段"
+
+
+def test_output_is_one_json_object_per_line(capsys: pytest.CaptureFixture[str]) -> None:
+    """输出为「一行一个 JSON 对象」：三次调用三行，且捕获到的每一行都可解析。"""
+    configure_logging(_test_settings())
+    logger = get_logger(PROBE_MODULE)
+    for sequence in range(3):
+        logger.info("探针：逐行 JSON", seq=sequence)
+
+    text = capsys.readouterr().err
+    lines = [line for line in text.splitlines() if line.strip()]
+    assert len(lines) >= 3, f"三次调用至少要三行，实际 {len(lines)} 行"
+    # 逐行解析（含第三方库经 root 处理器输出的行）：任何一行不是 JSON 都失败
+    assert len(_json_records(text)) == len(lines)
+    assert [record["seq"] for record in _probe_records(text)] == [0, 1, 2]
+
+
+def test_span_id_is_present_and_empty_because_skywalking_is_not_wired(
+    capsys: pytest.CaptureFixture[str],
+) -> None:
+    """`spanId` **存在且恒为空**，这是刻意的，不是漏填，MUST NOT 当死字段清掉。
+
+    依据：`design.md` D9 明确**不接 SkyWalking agent**（链路追踪后端留给平台级变更），
+    而 PDD §8.5.1 要求日志必含 `spanId`。故输出该字段但值为空——schema 完整、不假装有埋点。
+
+    调用方显式传入也不放行：否则一旦有人「顺手」填个假 spanId，日志就反过来骗人了。
+    """
+    configure_logging(_test_settings())
+    get_logger(PROBE_MODULE).info("探针：spanId 留空", spanId="fake-span-must-not-leak-through")
+
+    record = _only_probe_record(capsys.readouterr().err)
+
+    assert "spanId" in record, "spanId 字段必须存在（PDD 必含字段，缺了就是 schema 断裂）"
+    assert record["spanId"] == "", "不接 SkyWalking，spanId 必须为空且不可被调用方填充"
+
+
+def test_schema_identity_fields_cannot_be_spoofed(capsys: pytest.CaptureFixture[str]) -> None:
+    """app / service / spanId / traceId 由处理器强制赋值，调用方覆盖无效。"""
+    configure_logging(_test_settings(app_name="aicore-under-test"))
+    get_logger(PROBE_MODULE).info(
+        "探针：伪造身份字段",
+        app="evil-app",
+        service="evil-service",
+        spanId="evil-span",
+        traceId="evil-trace",
+    )
+
+    record = _only_probe_record(capsys.readouterr().err)
+
+    assert record["app"] == "aicore-under-test"
+    assert record["service"] == "aicore"
+    assert record["spanId"] == ""
+    assert record["traceId"] != "evil-trace"
+
+
+@pytest.mark.parametrize(
+    ("method", "expected"),
+    [
+        ("debug", "DEBUG"),
+        ("info", "INFO"),
+        ("warning", "WARNING"),
+        ("warn", "WARNING"),  # structlog 的别名：不归一就会写出 WARN（不在级别词表里）
+        ("error", "ERROR"),
+        ("critical", "CRITICAL"),
+    ],
+)
+def test_level_reflects_the_call(
+    capsys: pytest.CaptureFixture[str], method: str, expected: str
+) -> None:
+    """`level` 取大写（与 Java 侧 Logback `%level` 同口径），且如实反映调用级别。
+
+    带别名的方法（`warn`）必须归一成词表里的名字：采集侧按级别过滤时，`WARN` 这种词表外的
+    取值会被整批漏掉。`exception` 的归一见「带堆栈的记录」用例（它同时要验堆栈）。
+    """
+    configure_logging(_test_settings(log_level="DEBUG"))
+    getattr(get_logger(PROBE_MODULE), method)("探针：级别")
+
+    assert _only_probe_record(capsys.readouterr().err)["level"] == expected
+
+
+def test_message_keeps_the_original_text(capsys: pytest.CaptureFixture[str]) -> None:
+    """event → `message`：字段名换成 schema 要的名字，内容不变（中文可完整还原）。"""
+    configure_logging(_test_settings())
+    get_logger(PROBE_MODULE).info("识别失败：图片模糊", code=4003)
+
+    record = _only_probe_record(capsys.readouterr().err)
+
+    assert record["message"] == "识别失败：图片模糊"
+    assert "event" not in record, "schema 用 message；同时留 event 会造成两套字段名"
+
+
+def test_time_is_utc_iso8601(capsys: pytest.CaptureFixture[str]) -> None:
+    """`time` 为 UTC ISO-8601（与信封 timestamp 同口径），可被运维直接排序比较。"""
+    configure_logging(_test_settings())
+    get_logger(PROBE_MODULE).info("探针：时间戳")
+
+    record = _only_probe_record(capsys.readouterr().err)
+
+    parsed = datetime.fromisoformat(str(record["time"]))
+    assert parsed.tzinfo is not None, f"time 必须带时区：{record['time']!r}"
+    assert parsed.utcoffset() == timedelta(0), f"time 必须是 UTC：{record['time']!r}"
+
+
+def test_app_name_comes_from_settings(capsys: pytest.CaptureFixture[str]) -> None:
+    """`app` 取配置里的 `app_name`（换部署名不必改代码），`service` 是固定服务身份。"""
+    configure_logging(_test_settings(app_name="aicore-under-test"))
+    get_logger(PROBE_MODULE).info("探针：app 名")
+
+    record = _only_probe_record(capsys.readouterr().err)
+
+    assert record["app"] == "aicore-under-test"
+    assert record["service"] == "aicore"
+
+
+def test_log_level_from_settings_is_honoured(capsys: pytest.CaptureFixture[str]) -> None:
+    """`log_level` 被真正采纳：低于阈值的记录既不输出、也不落盘。"""
+    configure_logging(_test_settings(log_level="WARNING"))
+    logger = get_logger(PROBE_MODULE)
+    logger.info("探针：低于阈值")
+    logger.error("探针：达到阈值")
+
+    records = _probe_records(capsys.readouterr().err)
+
+    assert [record["message"] for record in records] == ["探针：达到阈值"]
+
+
+def test_log_level_is_scoped_to_the_service_namespace(
+    capsys: pytest.CaptureFixture[str],
+) -> None:
+    """级别只落在 `aicore` 命名空间上，**不动 root**；第三方库的告警仍进同一 schema。
+
+    这条是实测教训的固化：把 root 设成 INFO 之后，httpx 会把**完整请求 URL**（含 query 里的
+    用户输入）写成一条 INFO 日志，`test_errors.py` 里「用户原值不得进日志」的用例当场变红
+    ——即「顺手把第三方库的日志一起打开」本身就是一条泄漏面。
+
+    处理器仍挂在 root 上：第三方库 WARNING 及以上的记录照样渲染成同一 schema（处理器与级别
+    是两件事）。
+    """
+    root = logging.getLogger()
+    root_level_before = root.level
+
+    configure_logging(_test_settings(log_level="DEBUG"))
+
+    assert root.level == root_level_before, "root 级别被改动：第三方库的日志会被顺手打开"
+    assert logging.getLogger(SERVICE_NAME).level == logging.DEBUG
+    get_logger(PROBE_MODULE).debug("探针：服务自身的 DEBUG 记录")
+    logging.getLogger("httpx").warning("[告警：探针] 第三方库的告警")
+
+    records = _json_records(capsys.readouterr().err)
+
+    assert [record["module"] for record in records if record["level"] == "DEBUG"] == [PROBE_MODULE]
+    third_party = [record for record in records if record["module"] == "httpx"]
+    assert len(third_party) == 1, f"第三方库的告警未被同一管线渲染：{records}"
+    assert set(third_party[0]) >= REQUIRED_LOG_FIELDS
+
+
+def test_unknown_log_level_is_rejected_without_touching_live_configuration(
+    capsys: pytest.CaptureFixture[str], settings: Settings
+) -> None:
+    """非法 `log_level` 当场报错（不静默退回 INFO），且**不改动**已生效的配置。
+
+    静默兜底正是「以为配了其实没配」那类故障；已经配置好的日志器必须原样可用。
+    """
+    configure_logging(settings)
+    handlers_before = list(logging.getLogger().handlers)
+
+    with pytest.raises(ValueError) as excinfo:
+        configure_logging(_test_settings(log_level="VERBOSE"))
+
+    assert "VERBOSE" in str(excinfo.value)
+    assert list(logging.getLogger().handlers) == handlers_before, "非法级别不应动已生效的处理器"
+    get_logger(PROBE_MODULE).info("探针：配置未被破坏")
+    assert _only_probe_record(capsys.readouterr().err)["message"] == "探针：配置未被破坏"
+
+
+def test_get_logger_binds_module_and_yields_a_stdlib_bound_logger(
+    capsys: pytest.CaptureFixture[str], settings: Settings
+) -> None:
+    """`get_logger(module)` 把模块名绑进 schema，并接到 stdlib `logging` 上。
+
+    接到 stdlib 上意味着：级别过滤、`caplog`、root 处理器都照常工作（见 stdlib 记录用例）。
+    """
+    configure_logging(settings)
+
+    logger = get_logger(PROBE_MODULE)
+
+    bound = logger.bind()
+    assert isinstance(bound, structlog.stdlib.BoundLogger)
+    # 接在 stdlib logging 上（而不是 structlog 的 PrintLogger）：caplog / 级别过滤照常工作
+    assert isinstance(bound._logger, logging.Logger), "structlog 日志器必须接在 stdlib logging 上"
+    assert bound._logger.name == PROBE_MODULE
+    logger.info("探针：模块名")
+    assert _only_probe_record(capsys.readouterr().err)["module"] == PROBE_MODULE
+
+
+# ---------------------------------------------------------------------------
+# 2. stdlib logging 收编（Task 2.2 的规则 3 告警走这条通道）
+# ---------------------------------------------------------------------------
+
+
+def test_stdlib_record_is_rendered_in_the_same_schema(capsys: pytest.CaptureFixture[str]) -> None:
+    """`logging.getLogger(...).warning("%s", arg)` 与 structlog 记录**同一 schema**。
+
+    这是「不换掉 stdlib 日志」的正面证据：既有代码（`core/config.py` 的告警）不必改一行，
+    就自动获得 JSON 输出与全部必含字段。
+    """
+    configure_logging(_test_settings())
+    logging.getLogger(CONFIG_MODULE).warning("[告警：探针] stdlib 记录：%s", "带位置参数")
+
+    text = capsys.readouterr().err
+    records = _config_module_records(text)
+    assert len(records) == 1, f"stdlib 记录应恰好一条：{records}"
+
+    record = records[0]
+    assert set(record) >= REQUIRED_LOG_FIELDS, (
+        f"stdlib 记录缺少必含字段：{sorted(REQUIRED_LOG_FIELDS - set(record))}"
+    )
+    assert record["level"] == "WARNING"
+    assert record["message"] == "[告警：探针] stdlib 记录：带位置参数"  # %s 已渲染
+    assert record["module"] == CONFIG_MODULE  # 模块名取自 stdlib 日志器名
+    assert record["service"] == "aicore"
+
+
+def test_rule_three_warning_still_surfaces_in_json(capsys: pytest.CaptureFixture[str]) -> None:
+    """Task 2.2 规则 3 的告警（dev/test 降级 mock）必须仍然出现，且以 JSON 形式出现。
+
+    Task 2.2 选了 stdlib `logging` 而非 `warnings.warn`，正是为了被本任务的 JSON 管线收编；
+    本用例把这条接线端到端钉住：构造 `dev + mock` 的 `Settings` 即触发告警，输出必须是
+    带全部必含字段的 JSON 行，而不是纯文本或 stderr 兜底。
+    """
+    configure_logging(_test_settings())
+
+    _test_settings(env="dev", provider="mock")  # 构造即告警（规则 3），不阻断
+
+    text = capsys.readouterr().err
+    records = _config_module_records(text)
+    warnings = [record for record in records if "[告警：env-mock]" in str(record["message"])]
+    assert len(warnings) == 1, f"规则 3 告警未落进 JSON 输出：{records}"
+
+    warning = warnings[0]
+    assert set(warning) >= REQUIRED_LOG_FIELDS
+    assert warning["level"] == "WARNING"
+    assert "env=dev" in str(warning["message"])
+
+
+# ---------------------------------------------------------------------------
+# 3. traceId / traceIdSource（Task 2.5 遗留项的验收证据）
+# ---------------------------------------------------------------------------
+
+
+def test_request_trace_id_is_propagated_from_the_header(
+    capsys: pytest.CaptureFixture[str],
+) -> None:
+    """网关注入的 `X-Request-Id` 原样进日志，来源标记 `propagated`。
+
+    走**真实请求**（TestClient 触发 lifespan → 真实配置日志），不是直接调处理器。
+    """
+    with TestClient(_probe_app()) as client:
+        response = client.get(PROBE_PATH, headers={TRACE_ID_HEADER: INJECTED_TRACE_ID})
+
+    assert response.status_code == 200
+    record = _only_probe_record(capsys.readouterr().err)
+    assert record["traceId"] == INJECTED_TRACE_ID
+    assert record[TRACE_SOURCE_FIELD] == TRACE_SOURCE_PROPAGATED
+    assert TRACE_SOURCE_FIELD == "traceIdSource", "字段名是平台口径，改名即破坏主站 schema"
+
+
+def test_request_without_header_generates_trace_id_and_marks_generated(
+    capsys: pytest.CaptureFixture[str],
+) -> None:
+    """网关没注入时自行生成 16 位 hex，并标 `generated` —— 网关故障不被本地生成掩盖。
+
+    这正是 Task 2.5 评审留下的半截要求：没有 `traceIdSource`，「网关没注入」会被本地生成的
+    traceId 掩盖；本用例与上一条合起来，就是「生成行为在日志中可区分」的验收证据。
+    """
+    with TestClient(_probe_app()) as client:
+        response = client.get(PROBE_PATH)
+
+    assert response.status_code == 200
+    record = _only_probe_record(capsys.readouterr().err)
+    assert TRACE_ID_PATTERN.fullmatch(str(record["traceId"])), f"生成值不是 16 位 hex：{record}"
+    assert record[TRACE_SOURCE_FIELD] == TRACE_SOURCE_GENERATED
+    assert record[TRACE_SOURCE_FIELD] != TRACE_SOURCE_PROPAGATED
+
+
+def test_request_trace_id_is_carried_into_stdlib_records_too(
+    capsys: pytest.CaptureFixture[str],
+) -> None:
+    """请求上下文里的 traceId 同样进 stdlib 记录（告警与业务日志串得起来）。"""
+    app = create_app()
+
+    @app.get(PROBE_PATH, include_in_schema=False)
+    async def _probe() -> dict[str, str]:
+        logging.getLogger(CONFIG_MODULE).warning("[告警：探针] 请求内 stdlib 记录")
+        return {"ok": "1"}
+
+    with TestClient(app) as client:
+        client.get(PROBE_PATH, headers={TRACE_ID_HEADER: INJECTED_TRACE_ID})
+
+    records = _config_module_records(capsys.readouterr().err)
+    # 只取本用例自己写的那条：修复轮 1 起，lifespan 的引导配置让**读配置阶段的规则 3 告警**
+    # 也以 JSON 落在同一个模块（`test + mock` 是 conftest 的默认环境），故这里按消息来源收窄，
+    # 而不是断言「整个模块只有一行」——后者会把「规则 3 告警没进 JSON」这个缺陷当成前提。
+    own = [record for record in records if "[告警：探针]" in str(record["message"])]
+    assert len(own) == 1, f"本用例的 stdlib 记录应恰好一条：{records}"
+    assert own[0]["traceId"] == INJECTED_TRACE_ID
+    assert own[0][TRACE_SOURCE_FIELD] == TRACE_SOURCE_PROPAGATED
+
+
+# ---------------------------------------------------------------------------
+# 4. 敏感信息：uid 脱敏与密钥打码
+# ---------------------------------------------------------------------------
+
+
+def test_raw_certificate_like_value_never_reaches_the_output(
+    capsys: pytest.CaptureFixture[str],
+) -> None:
+    """`uid` 必含且**脱敏**：形似证件号的原始值不得出现在日志输出的任何位置。
+
+    断言针对**整段输出**（不只是那一条记录）：只要原始值在本用例的任何一行里露头即失败。
+    """
+    configure_logging(_test_settings())
+    get_logger(PROBE_MODULE).info(
+        "探针：实名认证",
+        uid=CERT_NUMBER_SENTINEL,
+        bizType="realname",
+        opCode="realname.verify",
+    )
+
+    text = capsys.readouterr().err
+
+    assert CERT_NUMBER_SENTINEL not in text, "未脱敏的证件号进入了日志输出"
+    record = _only_probe_record(text)
+    assert record["uid"] == CERT_NUMBER_MASKED
+    assert record["uid"] != CERT_NUMBER_SENTINEL
+
+
+@pytest.mark.parametrize(
+    ("raw", "expected"),
+    [
+        pytest.param("", "", id="空值保持空"),
+        pytest.param(CERT_NUMBER_SENTINEL, CERT_NUMBER_MASKED, id="18-位证件号"),
+        pytest.param("abc1234", "*******", id="长度不足时整串打码"),
+        pytest.param("test_uid_0001", "tes******0001", id="普通用户标识"),
+    ],
+)
+def test_desensitize_uid_keeps_only_head_and_tail(raw: str, expected: str) -> None:
+    """脱敏规则：保留首 3 位与末 4 位，中间打码；太短就整串打码（不靠截断蒙混）。"""
+    assert desensitize_uid(raw) == expected
+    if raw:
+        assert raw not in desensitize_uid(raw), "脱敏后仍能读到原值，等于没脱敏"
+
+
+def test_desensitize_uid_never_leaks_length_zero_input() -> None:
+    """空 uid 保持空串：字段存在但无值，不编造 `***` 之类假数据。"""
+    assert desensitize_uid("") == ""
+    assert desensitize_uid(None) == ""
+
+
+def test_secret_named_fields_are_redacted(capsys: pytest.CaptureFixture[str]) -> None:
+    """密钥类字段一律打码（PDD §8.5.1 L1748「禁止记录明文密钥」的兜底防线）。
+
+    这是**兜底**：真正的规矩是「不要把密钥传给日志」。这里再挡一层，是因为一次手滑的
+    `logger.info("配置", mysql_password=...)` 就会把口令永久写进日志文件。
+    """
+    configure_logging(_test_settings())
+    get_logger(PROBE_MODULE).info(
+        "探针：密钥字段",
+        mysql_password=PASSWORD_SENTINEL,
+        internal_token=TOKEN_SENTINEL,
+        deepseek_api_key=CHANNEL_KEY_SENTINEL,
+    )
+
+    text = capsys.readouterr().err
+
+    leaked = [sentinel for sentinel in SECRET_SENTINELS if sentinel in text]
+    assert not leaked, f"日志输出泄漏了凭据：{leaked}"
+    record = _only_probe_record(text)
+    assert record["mysql_password"] == "***"
+    assert record["internal_token"] == "***"
+    assert record["deepseek_api_key"] == "***"
+
+
+def test_non_secret_fields_are_not_redacted(capsys: pytest.CaptureFixture[str]) -> None:
+    """阴性对照：打码只认密钥类字段名，不能「见 key/token 就抹」。
+
+    LLM 的 token 计数字段是成本护栏的核心数据（`token_count` / `total_tokens` /
+    `max_tokens`），抹掉它们等于把可观测性一起抹掉。带 `_token` 后缀的字段才是密钥。
+    """
+    configure_logging(_test_settings())
+    get_logger(PROBE_MODULE).info(
+        "探针：token 计数",
+        token_count=42,
+        total_tokens=1024,
+        max_tokens=2048,
+        idempotency_key="test-idem-key",
+    )
+
+    record = _only_probe_record(capsys.readouterr().err)
+
+    assert record["token_count"] == 42
+    assert record["total_tokens"] == 1024
+    assert record["max_tokens"] == 2048
+    assert record["idempotency_key"] == "test-idem-key"
+
+
+# ---------------------------------------------------------------------------
+# 5. 全局状态：可重复配置、可刷盘
+# ---------------------------------------------------------------------------
+
+
+def test_second_configuration_does_not_double_emit(
+    capsys: pytest.CaptureFixture[str], settings: Settings
+) -> None:
+    """重复 `configure_logging` MUST NOT 重复挂处理器（否则每行日志会输出多份）。
+
+    这是测试自身的卫生要求：pytest 在同一进程里跑完全部用例，本任务又把日志配置成
+    进程级状态——第二次配置若只是「再加一个 handler」，日志就会成倍增长。
+    """
+    configure_logging(settings)
+    configure_logging(settings)
+
+    get_logger(PROBE_MODULE).info("探针：只应出现一次")
+
+    records = _probe_records(capsys.readouterr().err)
+    assert len(records) == 1, f"重复配置导致重复输出：{records}"
+
+
+def test_repeated_configuration_installs_exactly_one_handler(settings: Settings) -> None:
+    """三次配置后，本模块往 root 上新增的处理器恰好一个。"""
+    root = logging.getLogger()
+    handlers_before = list(root.handlers)
+
+    configure_logging(settings)
+    configure_logging(settings)
+    configure_logging(settings)
+
+    assert len(_added_handlers(handlers_before)) == 1
+
+
+def test_flush_logging_flushes_the_installed_handler(
+    settings: Settings, monkeypatch: pytest.MonkeyPatch
+) -> None:
+    """`flush_logging()` 刷的是本模块安装的处理器（关闭钩子的最小正确动作）。"""
+    root = logging.getLogger()
+    handlers_before = list(root.handlers)
+    configure_logging(settings)
+    installed = _added_handlers(handlers_before)
+    assert len(installed) == 1
+
+    flushed: list[str] = []
+    monkeypatch.setattr(installed[0], "flush", lambda: flushed.append("flush"))
+
+    flush_logging()
+
+    assert flushed == ["flush"]
+
+
+def test_lifespan_flushes_logging_on_shutdown(
+    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
+) -> None:
+    """关闭钩子调用 `flush_logging()`：先不刷，退出 `with` 时刷一次。"""
+    calls: list[str] = []
+    monkeypatch.setattr("aicore.main.flush_logging", lambda: calls.append("flush"))
+
+    with TestClient(_probe_app()) as client:
+        client.get("/health")
+        assert calls == [], "关闭前不应刷盘"
+
+    assert calls == ["flush"], "关闭钩子未刷盘"
+
+
+# ---------------------------------------------------------------------------
+# 6. 引导配置（修复轮 1：读配置阶段的第一行日志也必须是 JSON）
+# ---------------------------------------------------------------------------
+
+
+def test_bootstrap_emits_json_before_any_settings_are_read(
+    capsys: pytest.CaptureFixture[str],
+) -> None:
+    """`bootstrap_logging()` 之后写的每一行都是完整 schema 的 JSON —— 且它**不读配置**。
+
+    判别力的要害在顺序：修复前「读配置 → 装配日志」，而规则 3 的告警在 `Settings(...)` 构造
+    瞬间发出——那一行没有 JSON 处理器，落到 `logging.lastResort` 上变成纯文本。本用例在
+    **不构造任何 `Settings`** 的前提下断言 schema 完整，正是把「配置还没读到，日志已经合 schema」
+    这条要求钉死。
+    """
+    root = logging.getLogger()
+    handlers_before = list(root.handlers)
+
+    bootstrap_logging()
+    get_logger(PROBE_MODULE).info("探针：引导配置后的第一行")
+
+    record = _only_probe_record(capsys.readouterr().err)
+
+    missing = REQUIRED_LOG_FIELDS - set(record)
+    assert not missing, f"引导配置输出缺少必含字段：{sorted(missing)}"
+    assert all(record[field] is not None for field in REQUIRED_LOG_FIELDS)
+    assert record["level"] == "INFO"
+    assert record["module"] == PROBE_MODULE
+    assert len(_added_handlers(handlers_before)) == 1, "引导配置必须恰好装一个处理器"
+
+
+def test_bootstrap_writes_to_the_same_schema_as_the_full_configuration(
+    capsys: pytest.CaptureFixture[str],
+) -> None:
+    """引导配置与正式配置产出**逐字相同**的字段集合（不是「另一套 JSON」）。
+
+    这条是修复的实质：把首行换成 JSON 还不够，若引导用的是另一套字段形状，问题只是搬了家。
+    只允许 `app` 的**取值**不同（引导读不到配置，取 `DEFAULT_APP_NAME`），字段集合必须一致。
+    """
+    bootstrap_logging()
+    get_logger(PROBE_MODULE).info("探针：引导配置")
+    bootstrap_record = _only_probe_record(capsys.readouterr().err)
+
+    configure_logging(_test_settings(app_name="aicore-under-test"))
+    get_logger(PROBE_MODULE).info("探针：正式配置")
+    configured_record = _only_probe_record(capsys.readouterr().err)
+
+    assert set(bootstrap_record) == set(configured_record)
+    assert set(bootstrap_record) >= REQUIRED_LOG_FIELDS
+    assert "event" not in bootstrap_record, "字段名必须是 message（两段配置同一口径）"
+    assert bootstrap_record["app"] == DEFAULT_APP_NAME
+    assert configured_record["app"] == "aicore-under-test"
+    assert bootstrap_record["level"] == "INFO" == BOOTSTRAP_LOG_LEVEL
+    assert bootstrap_record["service"] == configured_record["service"] == SERVICE_NAME
+
+
+def test_bootstrap_then_configure_does_not_double_emit(
+    capsys: pytest.CaptureFixture[str], settings: Settings
+) -> None:
+    """「引导 + 正式」是幂等序列：每行日志**只输出一份**，root 上只留一个本模块的处理器。
+
+    这是简报点名的延伸保证：既有用例只覆盖「两次 `configure_logging`」；lifespan 真正跑的
+    是「先 `bootstrap_logging()`、再 `configure_logging()`」，若正式配置没有先摘掉引导装的
+    处理器，启动后的每行日志都会打印两份（噪声翻倍，采集侧还会当成两条记录）。
+    """
+    root = logging.getLogger()
+    handlers_before = list(root.handlers)
+
+    bootstrap_logging()
+    configure_logging(settings)
+
+    installed = _added_handlers(handlers_before)
+    assert len(installed) == 1, f"引导 + 正式应只留一个处理器，实际 {len(installed)} 个"
+
+    get_logger(PROBE_MODULE).info("探针：引导 + 正式各配一次")
+
+    records = _probe_records(capsys.readouterr().err)
+    assert len(records) == 1, f"引导 + 正式导致重复输出：{records}"
+
+
+def test_repeated_bootstrap_installs_exactly_one_handler(
+    capsys: pytest.CaptureFixture[str],
+) -> None:
+    """`bootstrap_logging()` 自身幂等：连调两次仍只装一个处理器、只输出一份。"""
+    root = logging.getLogger()
+    handlers_before = list(root.handlers)
+
+    bootstrap_logging()
+    bootstrap_logging()
+
+    assert len(_added_handlers(handlers_before)) == 1
+
+    get_logger(PROBE_MODULE).info("探针：引导两次")
+
+    records = _probe_records(capsys.readouterr().err)
+    assert len(records) == 1, f"引导配置重复调用导致重复输出：{records}"
+
+
+def test_bootstrap_default_level_does_not_silence_json_errors(
+    capsys: pytest.CaptureFixture[str],
+) -> None:
+    """引导默认级别 `INFO` 收得住告警与错误，且**不是**把级别设到 root 上。
+
+    `INFO` 的取舍：引导阶段只有启动校验的告警会说话，`INFO` 足够、又不会把正常启动刷成噪音。
+    同时核对级别只落在服务命名空间——root 被调松会把第三方库的 INFO 一起打开（泄漏面）。
+    """
+    root = logging.getLogger()
+    root_level_before = root.level
+
+    bootstrap_logging()
+
+    assert root.level == root_level_before, "引导配置改动了 root 级别：第三方库日志会被顺手打开"
+    assert logging.getLogger(SERVICE_NAME).level == logging.INFO
+
+    logging.getLogger(CONFIG_MODULE).warning("[告警：探针] 引导阶段的告警")
+    assert len(_config_module_records(capsys.readouterr().err)) == 1
+
+
+def test_bootstrap_after_configure_is_idempotent_too(
+    capsys: pytest.CaptureFixture[str], settings: Settings
+) -> None:
+    """反序也幂等：`configure_logging` 之后再调 `bootstrap_logging`，仍只留一个处理器、一份输出。
+
+    真实启动顺序是「引导 → 正式」，但幂等是被公开承诺的性质（重载、测试隔离、将来多入口），
+    故反序也钉住：两个函数都走同一套「先摘旧的再挂新的」，顺序不该改变结论。
+    """
+    root = logging.getLogger()
+    handlers_before = list(root.handlers)
+
+    configure_logging(settings)
+    bootstrap_logging()
+
+    assert len(_added_handlers(handlers_before)) == 1
+
+    get_logger(PROBE_MODULE).info("探针：正式 + 引导")
+
+    records = _probe_records(capsys.readouterr().err)
+    assert len(records) == 1, f"正式 + 引导导致重复输出：{records}"
+    # 引导把 app 换回默认值（它读不到配置）——这条同时说明「后调用的那次配置说了算」。
+    assert records[0]["app"] == DEFAULT_APP_NAME
+
+
+# ---------------------------------------------------------------------------
+# 7. lifespan 接线（本任务收口第 2 组）
+# ---------------------------------------------------------------------------
+
+
+def test_lifespan_configures_logging_so_records_are_json(
+    capsys: pytest.CaptureFixture[str],
+) -> None:
+    """启动钩子真的配置了日志：应用起来后业务代码写日志即得 JSON（无需测试手动配置）。"""
+    with TestClient(_probe_app()) as client:
+        client.get(PROBE_PATH)
+
+    record = _only_probe_record(capsys.readouterr().err)
+    assert set(record) >= REQUIRED_LOG_FIELDS
+    assert record["level"] == "INFO"
+
+
+def test_startup_first_emitted_line_is_json_with_every_mandated_field(
+    monkeypatch: pytest.MonkeyPatch,
+    capsys: pytest.CaptureFixture[str],
+) -> None:
+    """**真实启动路径**下的第一行日志就是 JSON：规则 3 的告警不再落成纯文本（修复轮 1 的验收位）。
+
+    走 `create_app()` + `TestClient`（真的进 lifespan，不是直接调处理器），环境配成
+    `dev + mock`——`Settings(...)` 构造瞬间就会发规则 3 的降级告警，**那正是修复前唯一
+    不合 schema 的那一行**。
+
+    「首行是 JSON」由三步合起来证明：① 输出里**每一行**都可 `json.loads`（逐行解析，不是抽查）；
+    ② 第一行就是规则 3 的告警，且必含字段齐全；③ 首行的 `app` 取引导默认值（此刻还没读到配置），
+    后续行由正式配置的 `app_name` 覆盖——两段配置的差别只在取值，不在 schema。
+    """
+    for name in [name for name in os.environ if name.upper().startswith("AICORE_")]:
+        monkeypatch.delenv(name)
+    monkeypatch.setenv("AICORE_MYSQL_HOST", "127.0.0.1")
+    monkeypatch.setenv("AICORE_MYSQL_USER", "test_user")
+    monkeypatch.setenv("AICORE_MYSQL_PASSWORD", "test_password")
+    monkeypatch.setenv("AICORE_MYSQL_DATABASE", "aicore_test")
+    monkeypatch.setenv("AICORE_REDIS_HOST", "127.0.0.1")
+    monkeypatch.setenv("AICORE_PROVIDER", "mock")
+    monkeypatch.setenv("AICORE_ENV", "dev")  # 规则 3：dev + mock → 告警（不阻断）
+    monkeypatch.setenv("AICORE_INTERNAL_TOKEN", "test_internal_token")
+    monkeypatch.setenv("AICORE_DAILY_QUOTA_PER_ACCOUNT", "1000")
+    monkeypatch.setenv("AICORE_DAILY_BUDGET_TOTAL", "100000")
+    clear_settings_cache()
+
+    with TestClient(_probe_app()) as client:
+        client.get(PROBE_PATH)
+
+    text = capsys.readouterr().err
+    records = _assert_every_line_is_json(text)
+    assert records, "启动一条日志都没写（本用例会静默变绿，故显式失败）"
+
+    first = records[0]
+    assert "[告警：env-mock]" in str(first["message"]), f"规则 3 的告警不是第一行：{first}"
+    assert first["level"] == "WARNING"
+    assert set(first) >= REQUIRED_LOG_FIELDS, (
+        f"启动首行缺少必含字段：{sorted(REQUIRED_LOG_FIELDS - set(first))}"
+    )
+    assert first["app"] == DEFAULT_APP_NAME, "首行由引导配置产出，app 取引导默认值"
+    assert first["service"] == SERVICE_NAME
+    assert [record for record in records if record["module"] == CONFIG_MODULE] == [first], (
+        f"规则 3 的告警应恰好一条：{records}"
+    )
+
+
+def test_rejected_startup_still_logs_json(
+    monkeypatch: pytest.MonkeyPatch,
+    capsys: pytest.CaptureFixture[str],
+) -> None:
+    """被**拒绝**的启动同样产出 JSON：阻断项清单以结构化 ERROR 行落进日志管线。
+
+    uvicorn 的启动失败栈是框架的 stderr 明文输出，**不进**本服务的 JSON 管线；拒绝启动恰恰
+    是最该被采集器看见的事件，故 lifespan 在抛出前把阻断项清单写成一条结构化 ERROR 记录。
+    四条断言：① 异常类型仍是 `ConfigRejected`（不是裸 `ValidationError`）；② `from None` 仍成立；
+    ③ 输出里**每一行**都可解析成 JSON（逐行解析，不是抽查）；④ 那一条记录 schema 完整、
+    逐条列出阻断项，且不带口令哨兵。
+    """
+    monkeypatch.setenv("AICORE_ENV", "prod")
+    monkeypatch.setenv("AICORE_PROVIDER", "mock")  # 规则 1：prod + mock → 拒绝启动
+    monkeypatch.setenv("AICORE_MYSQL_PASSWORD", PASSWORD_SENTINEL)
+    clear_settings_cache()
+
+    with pytest.raises(ConfigRejected) as excinfo, TestClient(_probe_app()):
+        pass  # pragma: no cover —— 启动即被拒，进不来
+
+    text = capsys.readouterr().err
+    assert excinfo.value.__cause__ is None, "from None 未生效：拒绝路径会带出原始 ValidationError"
+    rendered = "".join(traceback.format_exception(excinfo.value))
+    assert PASSWORD_SENTINEL not in rendered, "异常链泄漏了口令"
+    assert PASSWORD_SENTINEL not in text, "拒绝日志泄漏了口令"
+
+    records = _assert_every_line_is_json(text)
+    assert len(records) == 1, f"拒绝启动应恰好写一条记录：{records}"
+    record = records[0]
+    assert set(record) >= REQUIRED_LOG_FIELDS, (
+        f"拒绝记录缺少必含字段：{sorted(REQUIRED_LOG_FIELDS - set(record))}"
+    )
+    assert record["level"] == "ERROR"
+    assert record["module"] == LIFESPAN_MODULE, "记录应来自组合根的 lifespan"
+    assert "[跨字段：env-mock]" in str(record["message"])
+    assert "共 1 项阻断项" in str(record["message"])
+
+
+def test_logging_survives_a_rejected_startup(
+    monkeypatch: pytest.MonkeyPatch,
+    capsys: pytest.CaptureFixture[str],
+) -> None:
+    """拒绝启动之后，日志管线仍然可用：改成放行环境重启，第一行依旧是完整 schema 的 JSON。
+
+    这条防的是「拒绝路径把全局日志配置搞坏」（半装状态、处理器被摘掉却没补上）：若引导配置
+    装到一半就异常退出，第二次启动的首行又会退回纯文本，而 §6 的用例只跑成功路径，抓不到。
+    """
+    monkeypatch.setenv("AICORE_ENV", "prod")
+    monkeypatch.setenv("AICORE_PROVIDER", "mock")
+    clear_settings_cache()
+    with pytest.raises(ConfigRejected), TestClient(_probe_app()):
+        pass  # pragma: no cover —— 启动即被拒，进不来
+    capsys.readouterr()  # 丢弃第一次的输出，下面只断言第二次
+
+    monkeypatch.setenv("AICORE_ENV", "dev")  # 同一份配置改成放行组合
+    clear_settings_cache()
+
+    with TestClient(_probe_app()) as client:
+        client.get(PROBE_PATH)
+
+    records = _assert_every_line_is_json(capsys.readouterr().err)
+    assert records, "拒绝之后重新启动没有产生任何日志行"
+    first = records[0]
+    assert "[告警：env-mock]" in str(first["message"]), f"第二轮的规则 3 告警不是首行：{first}"
+    assert set(first) >= REQUIRED_LOG_FIELDS
+
+
+def test_startup_rejects_invalid_configuration_with_config_rejected(
+    monkeypatch: pytest.MonkeyPatch,
+) -> None:
+    """配置非法 → 启动抛 `ConfigRejected`（**不是**裸 `ValidationError`），且不带口令。
+
+    走真实启动路径（TestClient 进入 lifespan）。三条断言各管一件事：
+
+    ① 异常类型：运维看到的是「逐条阻断项」的 `ConfigRejected`，不是 pydantic 的报错；
+    ② `__cause__ is None` + `__suppress_context__`：`from None` 真的写上了。`from exc` 会把
+       `ValidationError` 挂成 cause，异常链因此成为绕过「只用 loc/msg」的泄漏通道
+       （见 `core/config.py` 模块 docstring）；
+    ③ 渲染后的异常链里没有任何秘密哨兵。
+    """
+    monkeypatch.setenv("AICORE_ENV", "prod")
+    monkeypatch.setenv("AICORE_PROVIDER", "mock")
+    monkeypatch.setenv("AICORE_MYSQL_PASSWORD", PASSWORD_SENTINEL)
+    clear_settings_cache()  # 缓存里可能还留着上一个用例的配置
+
+    with pytest.raises(ConfigRejected) as excinfo, TestClient(create_app()):
+        pass  # pragma: no cover —— 启动即被拒，进不来
+
+    message = str(excinfo.value)
+    assert "[跨字段：env-mock]" in message
+    assert excinfo.value.__cause__ is None, "from None 未生效：异常链会带上原始 ValidationError"
+    assert excinfo.value.__suppress_context__ is True
+    rendered = "".join(traceback.format_exception(excinfo.value))
+    assert PASSWORD_SENTINEL not in rendered
+    assert PASSWORD_SENTINEL not in message
+
+
+def test_raw_validation_error_carries_the_password_in_its_untruncated_input() -> None:
+    """阴性对照：泄漏通道**真实存在** —— 原始 `ValidationError` 的 input 原样带口令。
+
+    pydantic 2.13 在 `str(exc)` 里把 `input_value` 的**中段**省略，故这里 `str()` 未必看得见
+    口令；但 `errors()[i]["input"]` 是**未截断**的，任何遍历它的代码（或未来版本调整截断口径）
+    都会把口令写出去。本用例固定这个事实，使上一条用例不是「防一个不存在的风险」。
+    """
+    with pytest.raises(ValidationError) as excinfo:
+        _test_settings(env="prod", provider="mock", mysql_password=PASSWORD_SENTINEL)
+
+    payload = repr(excinfo.value.errors())
+    assert PASSWORD_SENTINEL in payload, (
+        "原始 ValidationError 不再携带口令：上一条用例的判别力需要重新评估"
+    )
+
+
+def test_create_app_still_builds_without_any_aicore_configuration(
+    monkeypatch: pytest.MonkeyPatch,
+) -> None:
+    """组合根仍是**纯装配函数**：清空全部 `AICORE_*` 后 `create_app()` 依然可建实例。
+
+    与 `test_config_startup.py` 的同名用例分工：那条守的是「工厂不读配置」，这条守的是
+    **本任务没有把配置读取搬进工厂**（启动接线只允许出现在 lifespan 里）。
+    """
+    for name in [name for name in os.environ if name.upper().startswith("AICORE_")]:
+        monkeypatch.delenv(name)
+    clear_settings_cache()
+
+    assert create_app() is not None

```
