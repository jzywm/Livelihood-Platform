# Review package b98f251..305112d

## Commits

305112d chore: 建立 AICORE 六层目录与模块契约空壳

## Stat

 services/aicore/src/aicore/api/__init__.py         |  1 +
 services/aicore/src/aicore/api/deps.py             |  1 +
 services/aicore/src/aicore/api/habit.py            |  1 +
 services/aicore/src/aicore/api/health.py           |  1 +
 services/aicore/src/aicore/api/ocr.py              |  1 +
 services/aicore/src/aicore/api/tasks.py            |  1 +
 services/aicore/src/aicore/core/__init__.py        |  1 +
 services/aicore/src/aicore/core/budget.py          |  1 +
 services/aicore/src/aicore/core/config.py          |  1 +
 services/aicore/src/aicore/core/envelope.py        |  1 +
 services/aicore/src/aicore/core/errors.py          |  1 +
 services/aicore/src/aicore/core/idgen.py           |  1 +
 services/aicore/src/aicore/core/logging.py         |  1 +
 services/aicore/src/aicore/core/ratelimit.py       |  1 +
 services/aicore/src/aicore/core/security.py        |  1 +
 services/aicore/src/aicore/core/task_runner.py     |  1 +
 services/aicore/src/aicore/core/trace.py           |  1 +
 services/aicore/src/aicore/port/__init__.py        |  1 +
 services/aicore/src/aicore/port/cred.py            |  1 +
 services/aicore/src/aicore/port/dash.py            |  1 +
 services/aicore/src/aicore/port/events.py          |  1 +
 services/aicore/src/aicore/provider/__init__.py    |  1 +
 services/aicore/src/aicore/provider/base.py        | 45 ++++++++++++++++++++++
 services/aicore/src/aicore/provider/cloud_ocr.py   |  1 +
 .../aicore/src/aicore/provider/cloud_vision.py     |  1 +
 services/aicore/src/aicore/provider/deepseek.py    |  1 +
 services/aicore/src/aicore/provider/mock.py        |  1 +
 services/aicore/src/aicore/provider/selector.py    |  1 +
 services/aicore/src/aicore/repository/__init__.py  |  1 +
 services/aicore/src/aicore/repository/base.py      |  1 +
 .../src/aicore/repository/correction_repo.py       |  1 +
 services/aicore/src/aicore/repository/models.py    |  1 +
 services/aicore/src/aicore/repository/ocr_repo.py  |  1 +
 services/aicore/src/aicore/repository/session.py   |  1 +
 services/aicore/src/aicore/repository/sharding.py  |  1 +
 services/aicore/src/aicore/repository/task_repo.py |  1 +
 .../aicore/src/aicore/repository/verdict_repo.py   |  1 +
 services/aicore/src/aicore/service/__init__.py     |  1 +
 services/aicore/src/aicore/service/accuracy.py     |  1 +
 services/aicore/src/aicore/service/desensitize.py  |  8 ++++
 .../aicore/src/aicore/service/habit/__init__.py    |  1 +
 services/aicore/src/aicore/service/habit/decay.py  |  1 +
 services/aicore/src/aicore/service/habit/engine.py |  1 +
 .../aicore/src/aicore/service/habit/evidence.py    |  1 +
 services/aicore/src/aicore/service/ocr_match.py    |  1 +
 services/aicore/src/aicore/service/ocr_service.py  |  1 +
 .../aicore/src/aicore/service/task/__init__.py     |  1 +
 .../aicore/src/aicore/service/task/registry.py     |  1 +
 services/aicore/src/aicore/service/verdict.py      |  1 +
 services/aicore/tests/structural/test_layering.py  |  1 +
 50 files changed, 101 insertions(+)

## Diff

```diff
diff --git a/services/aicore/src/aicore/api/__init__.py b/services/aicore/src/aicore/api/__init__.py
new file mode 100644
index 0000000..8d29ebb
--- /dev/null
+++ b/services/aicore/src/aicore/api/__init__.py
@@ -0,0 +1 @@
+"""协议适配层。仅做入参校验与协议转换，MUST NOT 直接访问 repository / provider。"""
diff --git a/services/aicore/src/aicore/api/deps.py b/services/aicore/src/aicore/api/deps.py
new file mode 100644
index 0000000..b1eaa28
--- /dev/null
+++ b/services/aicore/src/aicore/api/deps.py
@@ -0,0 +1 @@
+"""依赖注入提供者（FastAPI Depends 装配点）。Task 1.4 填实。"""
diff --git a/services/aicore/src/aicore/api/habit.py b/services/aicore/src/aicore/api/habit.py
new file mode 100644
index 0000000..a022851
--- /dev/null
+++ b/services/aicore/src/aicore/api/habit.py
@@ -0,0 +1 @@
+"""习惯与购买影响因素无状态计算（服务端间）。第 10 组实现。"""
diff --git a/services/aicore/src/aicore/api/health.py b/services/aicore/src/aicore/api/health.py
new file mode 100644
index 0000000..fc26a10
--- /dev/null
+++ b/services/aicore/src/aicore/api/health.py
@@ -0,0 +1 @@
+"""存活与就绪检查。Task 1.4 实现。"""
diff --git a/services/aicore/src/aicore/api/ocr.py b/services/aicore/src/aicore/api/ocr.py
new file mode 100644
index 0000000..c97f567
--- /dev/null
+++ b/services/aicore/src/aicore/api/ocr.py
@@ -0,0 +1 @@
+"""证照 OCR 提交与结果。第 4 组实现。"""
diff --git a/services/aicore/src/aicore/api/tasks.py b/services/aicore/src/aicore/api/tasks.py
new file mode 100644
index 0000000..0b6baa0
--- /dev/null
+++ b/services/aicore/src/aicore/api/tasks.py
@@ -0,0 +1 @@
+"""任务查询回执。第 4 组实现。"""
diff --git a/services/aicore/src/aicore/core/__init__.py b/services/aicore/src/aicore/core/__init__.py
new file mode 100644
index 0000000..f3d6eea
--- /dev/null
+++ b/services/aicore/src/aicore/core/__init__.py
@@ -0,0 +1 @@
+"""横切关注点。本层 MUST NOT 依赖 service / provider / repository（见 setup.cfg 契约）。"""
diff --git a/services/aicore/src/aicore/core/budget.py b/services/aicore/src/aicore/core/budget.py
new file mode 100644
index 0000000..a0e8c65
--- /dev/null
+++ b/services/aicore/src/aicore/core/budget.py
@@ -0,0 +1 @@
+"""成本三层护栏（日配额 / 全局预算 / 调用方归因）。第 9 组实现。"""
diff --git a/services/aicore/src/aicore/core/config.py b/services/aicore/src/aicore/core/config.py
new file mode 100644
index 0000000..e9040ee
--- /dev/null
+++ b/services/aicore/src/aicore/core/config.py
@@ -0,0 +1 @@
+"""配置模型。Task 2.1 实现 Pydantic Settings 与启动四条校验。"""
diff --git a/services/aicore/src/aicore/core/envelope.py b/services/aicore/src/aicore/core/envelope.py
new file mode 100644
index 0000000..d88be2e
--- /dev/null
+++ b/services/aicore/src/aicore/core/envelope.py
@@ -0,0 +1 @@
+"""统一响应信封（code/message/traceId/timestamp）。Task 2.4 实现。"""
diff --git a/services/aicore/src/aicore/core/errors.py b/services/aicore/src/aicore/core/errors.py
new file mode 100644
index 0000000..3a1542c
--- /dev/null
+++ b/services/aicore/src/aicore/core/errors.py
@@ -0,0 +1 @@
+"""异常层次与错误码常量。Task 2.3 实现。"""
diff --git a/services/aicore/src/aicore/core/idgen.py b/services/aicore/src/aicore/core/idgen.py
new file mode 100644
index 0000000..9b6f167
--- /dev/null
+++ b/services/aicore/src/aicore/core/idgen.py
@@ -0,0 +1 @@
+"""前缀化分布式 ID（前缀 + UUID，总长 ≤32）。Task 3.8 实现。"""
diff --git a/services/aicore/src/aicore/core/logging.py b/services/aicore/src/aicore/core/logging.py
new file mode 100644
index 0000000..9932206
--- /dev/null
+++ b/services/aicore/src/aicore/core/logging.py
@@ -0,0 +1 @@
+"""结构化 JSON 日志（11 必含字段）。Task 2.6 实现。"""
diff --git a/services/aicore/src/aicore/core/ratelimit.py b/services/aicore/src/aicore/core/ratelimit.py
new file mode 100644
index 0000000..8e69cf5
--- /dev/null
+++ b/services/aicore/src/aicore/core/ratelimit.py
@@ -0,0 +1 @@
+"""Redis 令牌桶限流（业务码 2004）。第 4/9 组实现。"""
diff --git a/services/aicore/src/aicore/core/security.py b/services/aicore/src/aicore/core/security.py
new file mode 100644
index 0000000..8b30ddb
--- /dev/null
+++ b/services/aicore/src/aicore/core/security.py
@@ -0,0 +1 @@
+"""内部 Token 校验（请求头 X-Internal-Token）。第 4 组实现。"""
diff --git a/services/aicore/src/aicore/core/task_runner.py b/services/aicore/src/aicore/core/task_runner.py
new file mode 100644
index 0000000..c26b3e7
--- /dev/null
+++ b/services/aicore/src/aicore/core/task_runner.py
@@ -0,0 +1 @@
+"""任务执行器内核（领取 / 租约 / 重试 / 线程池边界）。第 4 组实现。"""
diff --git a/services/aicore/src/aicore/core/trace.py b/services/aicore/src/aicore/core/trace.py
new file mode 100644
index 0000000..84da332
--- /dev/null
+++ b/services/aicore/src/aicore/core/trace.py
@@ -0,0 +1 @@
+"""traceId 上下文变量与传播（请求头 X-Request-Id）。Task 2.5 实现。"""
diff --git a/services/aicore/src/aicore/port/__init__.py b/services/aicore/src/aicore/port/__init__.py
new file mode 100644
index 0000000..d4c849a
--- /dev/null
+++ b/services/aicore/src/aicore/port/__init__.py
@@ -0,0 +1 @@
+"""跨服务出向端口。只在 service 中被依赖，实现由组合根注入。"""
diff --git a/services/aicore/src/aicore/port/cred.py b/services/aicore/src/aicore/port/cred.py
new file mode 100644
index 0000000..ad95a3c
--- /dev/null
+++ b/services/aicore/src/aicore/port/cred.py
@@ -0,0 +1 @@
+"""CRED 权威数据回写端口（A-02 档案 / 信用分）。第 7 组实现。"""
diff --git a/services/aicore/src/aicore/port/dash.py b/services/aicore/src/aicore/port/dash.py
new file mode 100644
index 0000000..7fd0466
--- /dev/null
+++ b/services/aicore/src/aicore/port/dash.py
@@ -0,0 +1 @@
+"""DASH 预警上报端口（A-08）。第 7 组实现。"""
diff --git a/services/aicore/src/aicore/port/events.py b/services/aicore/src/aicore/port/events.py
new file mode 100644
index 0000000..653945a
--- /dev/null
+++ b/services/aicore/src/aicore/port/events.py
@@ -0,0 +1 @@
+"""事件幂等键（authority_event_id）与每日对账。第 7 组实现。"""
diff --git a/services/aicore/src/aicore/provider/__init__.py b/services/aicore/src/aicore/provider/__init__.py
new file mode 100644
index 0000000..ce6608b
--- /dev/null
+++ b/services/aicore/src/aicore/provider/__init__.py
@@ -0,0 +1 @@
+"""外部模型通道边界。唯一允许发起外部模型 HTTP 调用的层。"""
diff --git a/services/aicore/src/aicore/provider/base.py b/services/aicore/src/aicore/provider/base.py
new file mode 100644
index 0000000..ab72412
--- /dev/null
+++ b/services/aicore/src/aicore/provider/base.py
@@ -0,0 +1,45 @@
+"""外部模型通道 Protocol。
+
+service 层 MUST 只依赖本文件的 Protocol，MUST NOT 导入任何具体实现
+（mock / deepseek / cloud_vision / cloud_ocr）——由 setup.cfg 的 import-linter 契约强制。
+"""
+
+from __future__ import annotations
+
+from typing import Any, Protocol, runtime_checkable
+
+
+@runtime_checkable
+class TextProvider(Protocol):
+    """文本模型通道。"""
+
+    name: str
+    model_version: str
+
+    async def complete(self, *, prompt: str, payload: dict[str, Any]) -> dict[str, Any]:
+        """返回 {text, confidence, modelVersion, promptVersion}。"""
+        ...
+
+
+@runtime_checkable
+class VisionProvider(Protocol):
+    """视觉模型通道。"""
+
+    name: str
+    model_version: str
+
+    async def analyze(self, *, image_key: str, labels: list[str]) -> dict[str, Any]:
+        """返回 {markers, confidence, modelVersion}。"""
+        ...
+
+
+@runtime_checkable
+class OcrProvider(Protocol):
+    """证照 OCR 通道。"""
+
+    name: str
+    model_version: str
+
+    async def recognize(self, *, image_key: str, doc_type: str) -> dict[str, Any]:
+        """返回 {fields, confidence, modelVersion, promptVersion}。"""
+        ...
diff --git a/services/aicore/src/aicore/provider/cloud_ocr.py b/services/aicore/src/aicore/provider/cloud_ocr.py
new file mode 100644
index 0000000..97d86a5
--- /dev/null
+++ b/services/aicore/src/aicore/provider/cloud_ocr.py
@@ -0,0 +1 @@
+"""云 OCR 通道骨架。第 4 组实现；覆盖率排除。"""
diff --git a/services/aicore/src/aicore/provider/cloud_vision.py b/services/aicore/src/aicore/provider/cloud_vision.py
new file mode 100644
index 0000000..dc36efd
--- /dev/null
+++ b/services/aicore/src/aicore/provider/cloud_vision.py
@@ -0,0 +1 @@
+"""云视觉通道骨架。第 4 组实现；覆盖率排除。"""
diff --git a/services/aicore/src/aicore/provider/deepseek.py b/services/aicore/src/aicore/provider/deepseek.py
new file mode 100644
index 0000000..9a3b4eb
--- /dev/null
+++ b/services/aicore/src/aicore/provider/deepseek.py
@@ -0,0 +1 @@
+"""DeepSeek 文本通道骨架。Task 4.3 实现；覆盖率排除（见 pyproject.toml）。"""
diff --git a/services/aicore/src/aicore/provider/mock.py b/services/aicore/src/aicore/provider/mock.py
new file mode 100644
index 0000000..ac4037c
--- /dev/null
+++ b/services/aicore/src/aicore/provider/mock.py
@@ -0,0 +1 @@
+"""确定性 Mock 通道（离线测试与降级演练）。第 4 组实现。"""
diff --git a/services/aicore/src/aicore/provider/selector.py b/services/aicore/src/aicore/provider/selector.py
new file mode 100644
index 0000000..e242fd2
--- /dev/null
+++ b/services/aicore/src/aicore/provider/selector.py
@@ -0,0 +1 @@
+"""按配置选择模型通道。第 4 组实现。"""
diff --git a/services/aicore/src/aicore/repository/__init__.py b/services/aicore/src/aicore/repository/__init__.py
new file mode 100644
index 0000000..9f3c73b
--- /dev/null
+++ b/services/aicore/src/aicore/repository/__init__.py
@@ -0,0 +1 @@
+"""自有库数据访问层。MUST NOT 依赖 service（避免边界倒置使合规检查点失效）。"""
diff --git a/services/aicore/src/aicore/repository/base.py b/services/aicore/src/aicore/repository/base.py
new file mode 100644
index 0000000..4704548
--- /dev/null
+++ b/services/aicore/src/aicore/repository/base.py
@@ -0,0 +1 @@
+"""repository 基类与跨分片操作守卫。Task 3.7 实现。"""
diff --git a/services/aicore/src/aicore/repository/correction_repo.py b/services/aicore/src/aicore/repository/correction_repo.py
new file mode 100644
index 0000000..9dfa5fc
--- /dev/null
+++ b/services/aicore/src/aicore/repository/correction_repo.py
@@ -0,0 +1 @@
+"""纠错回流表数据访问。Task 3.7 实现。"""
diff --git a/services/aicore/src/aicore/repository/models.py b/services/aicore/src/aicore/repository/models.py
new file mode 100644
index 0000000..4535c7a
--- /dev/null
+++ b/services/aicore/src/aicore/repository/models.py
@@ -0,0 +1 @@
+"""SQLAlchemy 2.x 声明式模型（字段对齐 er.md §6）。Task 3.2 实现。"""
diff --git a/services/aicore/src/aicore/repository/ocr_repo.py b/services/aicore/src/aicore/repository/ocr_repo.py
new file mode 100644
index 0000000..4235254
--- /dev/null
+++ b/services/aicore/src/aicore/repository/ocr_repo.py
@@ -0,0 +1 @@
+"""OCR 结果表数据访问。Task 3.7 实现。"""
diff --git a/services/aicore/src/aicore/repository/session.py b/services/aicore/src/aicore/repository/session.py
new file mode 100644
index 0000000..b936348
--- /dev/null
+++ b/services/aicore/src/aicore/repository/session.py
@@ -0,0 +1 @@
+"""会话与连接池（同步会话 + 线程池；写会话 / 只读会话分离）。Task 3.4 实现。"""
diff --git a/services/aicore/src/aicore/repository/sharding.py b/services/aicore/src/aicore/repository/sharding.py
new file mode 100644
index 0000000..877d610
--- /dev/null
+++ b/services/aicore/src/aicore/repository/sharding.py
@@ -0,0 +1 @@
+"""按月分表路由（物理表名 xxx_YYYYMM）。Task 3.3 实现。"""
diff --git a/services/aicore/src/aicore/repository/task_repo.py b/services/aicore/src/aicore/repository/task_repo.py
new file mode 100644
index 0000000..6ff8424
--- /dev/null
+++ b/services/aicore/src/aicore/repository/task_repo.py
@@ -0,0 +1 @@
+"""任务表数据访问。Task 3.7 实现。"""
diff --git a/services/aicore/src/aicore/repository/verdict_repo.py b/services/aicore/src/aicore/repository/verdict_repo.py
new file mode 100644
index 0000000..c811381
--- /dev/null
+++ b/services/aicore/src/aicore/repository/verdict_repo.py
@@ -0,0 +1 @@
+"""复核结论表数据访问。Task 3.7 实现。"""
diff --git a/services/aicore/src/aicore/service/__init__.py b/services/aicore/src/aicore/service/__init__.py
new file mode 100644
index 0000000..c312081
--- /dev/null
+++ b/services/aicore/src/aicore/service/__init__.py
@@ -0,0 +1 @@
+"""业务编排层。只依赖 provider 的 Protocol、repository 与 port，MUST NOT 依赖具体 Provider 实现。"""
diff --git a/services/aicore/src/aicore/service/accuracy.py b/services/aicore/src/aicore/service/accuracy.py
new file mode 100644
index 0000000..85bebf6
--- /dev/null
+++ b/services/aicore/src/aicore/service/accuracy.py
@@ -0,0 +1 @@
+"""纠错回流与固定评估集回归。第 5 组实现。"""
diff --git a/services/aicore/src/aicore/service/desensitize.py b/services/aicore/src/aicore/service/desensitize.py
new file mode 100644
index 0000000..504aafa
--- /dev/null
+++ b/services/aicore/src/aicore/service/desensitize.py
@@ -0,0 +1,8 @@
+"""图像脱敏前置阶段。
+
+【合规红线 D4 / R-03】脱敏失败或超时 MUST 拒绝外发，MUST NOT 出现「异常后继续执行」
+的降级分支——本文件受 tests/structural/test_source_guards.py 的 AST 扫描强制。
+确需吞掉异常时，必须在该 except 行加 `# noqa: ai-allow-swallow: <理由>` 显式豁免。
+
+第 4 组实现具体算法；本任务仅建文件以保证结构检查从第一天起生效。
+"""
diff --git a/services/aicore/src/aicore/service/habit/__init__.py b/services/aicore/src/aicore/service/habit/__init__.py
new file mode 100644
index 0000000..4cd329f
--- /dev/null
+++ b/services/aicore/src/aicore/service/habit/__init__.py
@@ -0,0 +1 @@
+"""习惯计算纯函数包（无 IO、无写库路径）。第 10 组实现。"""
diff --git a/services/aicore/src/aicore/service/habit/decay.py b/services/aicore/src/aicore/service/habit/decay.py
new file mode 100644
index 0000000..06d590b
--- /dev/null
+++ b/services/aicore/src/aicore/service/habit/decay.py
@@ -0,0 +1 @@
+"""证据时间衰减权重（纯函数，无 IO、无写库路径）。第 10 组实现。"""
diff --git a/services/aicore/src/aicore/service/habit/engine.py b/services/aicore/src/aicore/service/habit/engine.py
new file mode 100644
index 0000000..d3a4304
--- /dev/null
+++ b/services/aicore/src/aicore/service/habit/engine.py
@@ -0,0 +1 @@
+"""习惯计算引擎（纯函数，无 IO、无写库路径）。第 10 组实现。"""
diff --git a/services/aicore/src/aicore/service/habit/evidence.py b/services/aicore/src/aicore/service/habit/evidence.py
new file mode 100644
index 0000000..91d4ba8
--- /dev/null
+++ b/services/aicore/src/aicore/service/habit/evidence.py
@@ -0,0 +1 @@
+"""购买影响因素证据生成（纯函数，无 IO、无写库路径）。第 10 组实现。"""
diff --git a/services/aicore/src/aicore/service/ocr_match.py b/services/aicore/src/aicore/service/ocr_match.py
new file mode 100644
index 0000000..418bfb2
--- /dev/null
+++ b/services/aicore/src/aicore/service/ocr_match.py
@@ -0,0 +1 @@
+"""有效期与经营类目比对（纯函数）。第 4 组实现。"""
diff --git a/services/aicore/src/aicore/service/ocr_service.py b/services/aicore/src/aicore/service/ocr_service.py
new file mode 100644
index 0000000..f13b5b5
--- /dev/null
+++ b/services/aicore/src/aicore/service/ocr_service.py
@@ -0,0 +1 @@
+"""OCR 任务编排。第 4 组实现。"""
diff --git a/services/aicore/src/aicore/service/task/__init__.py b/services/aicore/src/aicore/service/task/__init__.py
new file mode 100644
index 0000000..a661297
--- /dev/null
+++ b/services/aicore/src/aicore/service/task/__init__.py
@@ -0,0 +1 @@
+"""任务类型策略注册表。第 4 组实现。"""
diff --git a/services/aicore/src/aicore/service/task/registry.py b/services/aicore/src/aicore/service/task/registry.py
new file mode 100644
index 0000000..c10510a
--- /dev/null
+++ b/services/aicore/src/aicore/service/task/registry.py
@@ -0,0 +1 @@
+"""任务类型 → 处理器注册表（OCR 已实现，其余预留）。第 4 组实现。"""
diff --git a/services/aicore/src/aicore/service/verdict.py b/services/aicore/src/aicore/service/verdict.py
new file mode 100644
index 0000000..0cb544a
--- /dev/null
+++ b/services/aicore/src/aicore/service/verdict.py
@@ -0,0 +1 @@
+"""C8 权威回写前置条件：无人工复核结论则不存在回写入口。第 8 组实现。"""
diff --git a/services/aicore/tests/structural/test_layering.py b/services/aicore/tests/structural/test_layering.py
new file mode 100644
index 0000000..6f0fa8e
--- /dev/null
+++ b/services/aicore/tests/structural/test_layering.py
@@ -0,0 +1 @@
+"""分层依赖规则检查。Task 1.3 填实。"""

```
