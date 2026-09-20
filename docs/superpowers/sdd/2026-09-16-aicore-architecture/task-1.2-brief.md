### Task 1.2: 分层目录与模块契约

**Files:**
- Create: `services/aicore/src/aicore/` 下六层共 30 个模块文件（全部为空壳：仅模块文档串 + 类型签名）
- Create: `services/aicore/tests/structural/test_layering.py`（本任务仅建目录与占位用例，Task 1.3 填实）

**Interfaces:**
- Consumes: `aicore.__version__`（Task 1.1）
- Produces: 六层包结构；`aicore.provider.base` 的 `TextProvider` / `VisionProvider` / `OcrProvider` 三个 `Protocol`；每层 `__init__.py`

**为什么全部建空壳**：分层规则要**从第一天起可检查**。若等有业务代码再建目录，规则会在最需要它的时候缺席。

- [ ] **Step 1: 写 `src/aicore/core/__init__.py`**

```python
"""横切关注点。本层 MUST NOT 依赖 service / provider / repository（见 .importlinter 契约）。"""
```

- [ ] **Step 2: 写 `src/aicore/core/config.py` 空壳（Task 2.1 填实）**

```python
"""配置模型。Task 2.1 实现 Pydantic Settings 与启动四条校验。"""
```

- [ ] **Step 3: 写 `core/errors.py`、`core/envelope.py`、`core/trace.py`、`core/logging.py` 空壳**

四个文件，每个内容为一行模块文档串：

```python
"""异常层次与错误码常量。Task 2.3 实现。"""
```

```python
"""统一响应信封（code/message/traceId/timestamp）。Task 2.4 实现。"""
```

```python
"""traceId 上下文变量与传播（请求头 X-Request-Id）。Task 2.5 实现。"""
```

```python
"""结构化 JSON 日志（11 必含字段）。Task 2.6 实现。"""
```

- [ ] **Step 4: 写 `core/idgen.py`、`core/security.py`、`core/ratelimit.py`、`core/budget.py`、`core/task_runner.py` 空壳**

```python
"""前缀化分布式 ID（前缀 + UUID，总长 ≤32）。Task 3.8 实现。"""
```

```python
"""内部 Token 校验（请求头 X-Internal-Token）。第 4 组实现。"""
```

```python
"""Redis 令牌桶限流（业务码 2004）。第 4/9 组实现。"""
```

```python
"""成本三层护栏（日配额 / 全局预算 / 调用方归因）。第 9 组实现。"""
```

```python
"""任务执行器内核（领取 / 租约 / 重试 / 线程池边界）。第 4 组实现。"""
```

- [ ] **Step 5: 写 `src/aicore/api/__init__.py` 与 `api/deps.py`**

```python
"""协议适配层。仅做入参校验与协议转换，MUST NOT 直接访问 repository / provider。"""
```

`api/deps.py`：

```python
"""依赖注入提供者（FastAPI Depends 装配点）。Task 1.4 填实。"""
```

- [ ] **Step 6: 写 `api/health.py`、`api/ocr.py`、`api/tasks.py`、`api/habit.py` 空壳**

```python
"""存活与就绪检查。Task 1.4 实现。"""
```

```python
"""证照 OCR 提交与结果。第 4 组实现。"""
```

```python
"""任务查询回执。第 4 组实现。"""
```

```python
"""习惯与购买影响因素无状态计算（服务端间）。第 10 组实现。"""
```

- [ ] **Step 7: 写 `src/aicore/service/__init__.py` 与业务编排空壳**

```python
"""业务编排层。只依赖 provider 的 Protocol、repository 与 port，MUST NOT 依赖具体 Provider 实现。"""
```

`service/ocr_service.py` / `ocr_match.py` / `accuracy.py` / `verdict.py` 各写一行文档串，例如：

```python
"""OCR 任务编排。第 4 组实现。"""
```

```python
"""有效期与经营类目比对（纯函数）。第 4 组实现。"""
```

```python
"""纠错回流与固定评估集回归。第 5 组实现。"""
```

```python
"""C8 权威回写前置条件。

【合规红线 D5 / C8】无人工复核结论则 MUST NOT 存在回写入口，MUST NOT 出现绕过人工结论的
回写分支——本文件受 tests/structural/test_source_guards.py 的 AST 扫描强制。
确需吞掉异常时，必须在该 except 行加 `# ai-allow-swallow: <理由>` 显式豁免（理由必填，见修复轮 1 更正）。

第 8 组实现具体回写入口；本任务仅建文件以保证结构检查从第一天起生效。
"""
```

- [ ] **Step 8: 写 `service/desensitize.py`（规则 6 的受检文件，本任务必须建）**

```python
"""图像脱敏前置阶段。

【合规红线 D4 / R-03】脱敏失败或超时 MUST 拒绝外发，MUST NOT 出现「异常后继续执行」
的降级分支——本文件受 tests/structural/test_source_guards.py 的 AST 扫描强制。
确需吞掉异常时，必须在该 except 行加 `# ai-allow-swallow: <理由>` 显式豁免（理由必填，见修复轮 1 更正）。

第 4 组实现具体算法；本任务仅建文件以保证结构检查从第一天起生效。
"""
```

- [ ] **Step 9: 写 `service/habit/` 与 `service/task/` 子包空壳**

- `service/habit/__init__.py`：`"""习惯计算纯函数包（无 IO、无写库路径）。第 10 组实现。"""`
- `service/habit/engine.py` / `decay.py` / `evidence.py`：各一行文档串
- `service/task/__init__.py`：`"""任务类型策略注册表。第 4 组实现。"""`
- `service/task/registry.py`：`"""任务类型 → 处理器注册表（OCR 已实现，其余预留）。第 4 组实现。"""`

- [ ] **Step 10: 写 `src/aicore/provider/__init__.py` 与 `provider/base.py`（本层唯一被 service 依赖的文件）**

`provider/__init__.py`：

```python
"""外部模型通道边界。唯一允许发起外部模型 HTTP 调用的层。"""
```

`provider/base.py`：

```python
"""外部模型通道 Protocol。

service 层 MUST 只依赖本文件的 Protocol，MUST NOT 导入任何具体实现
（mock / deepseek / cloud_vision / cloud_ocr）——由 `.importlinter` 的 import-linter 契约强制。
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class TextProvider(Protocol):
    """文本模型通道。"""

    name: str
    model_version: str

    async def complete(self, *, prompt: str, payload: dict[str, Any]) -> dict[str, Any]:
        """返回 {text, confidence, modelVersion, promptVersion}。"""
        ...


@runtime_checkable
class VisionProvider(Protocol):
    """视觉模型通道。"""

    name: str
    model_version: str

    async def analyze(self, *, image_key: str, labels: list[str]) -> dict[str, Any]:
        """返回 {markers, confidence, modelVersion}。"""
        ...


@runtime_checkable
class OcrProvider(Protocol):
    """证照 OCR 通道。"""

    name: str
    model_version: str

    async def recognize(self, *, image_key: str, doc_type: str) -> dict[str, Any]:
        """返回 {fields, confidence, modelVersion, promptVersion}。"""
        ...
```

- [ ] **Step 11: 写 `provider/selector.py`、`mock.py`、`deepseek.py`、`cloud_vision.py`、`cloud_ocr.py` 空壳**

```python
"""按配置选择模型通道。第 4 组实现。"""
```

```python
"""确定性 Mock 通道（离线测试与降级演练）。第 4 组实现。"""
```

```python
"""DeepSeek 文本通道骨架。Task 4.3 实现；覆盖率排除（见 pyproject.toml）。"""
```

```python
"""云视觉通道骨架。第 4 组实现；覆盖率排除。"""
```

```python
"""云 OCR 通道骨架。第 4 组实现；覆盖率排除。"""
```

- [ ] **Step 12: 写 `src/aicore/repository/__init__.py` 与四个 repo 空壳**

```python
"""自有库数据访问层。MUST NOT 依赖 service（避免边界倒置使合规检查点失效）。"""
```

`repository/task_repo.py` / `ocr_repo.py` / `correction_repo.py` / `verdict_repo.py`：

```python
"""任务表数据访问。Task 3.7 实现。"""
```

```python
"""OCR 结果表数据访问。Task 3.7 实现。"""
```

```python
"""纠错回流表数据访问。Task 3.7 实现。"""
```

```python
"""复核结论表数据访问。Task 3.7 实现。"""
```

- [ ] **Step 13: 写 `repository/sharding.py`、`session.py`、`models.py`、`base.py` 空壳**

```python
"""按月分表路由（物理表名 xxx_YYYYMM）。Task 3.3 实现。"""
```

```python
"""会话与连接池（同步会话 + 线程池；写会话 / 只读会话分离）。Task 3.4 实现。"""
```

```python
"""SQLAlchemy 2.x 声明式模型（字段对齐 er.md §6）。Task 3.2 实现。"""
```

```python
"""repository 基类与跨分片操作守卫。Task 3.7 实现。"""
```

- [ ] **Step 14: 写 `src/aicore/port/__init__.py` 与端口空壳**

```python
"""跨服务出向端口。只在 service 中被依赖，实现由组合根注入。"""
```

`port/cred.py` / `dash.py` / `events.py`：

```python
"""CRED 权威数据回写端口（A-02 档案 / 信用分）。第 7 组实现。"""
```

```python
"""DASH 预警上报端口（A-08）。第 7 组实现。"""
```

```python
"""事件幂等键（authority_event_id）与每日对账。第 7 组实现。"""
```

- [ ] **Step 15: 写 `tests/structural/test_layering.py` 占位（Task 1.3 填实）**

```python
"""分层依赖规则检查。Task 1.3 填实。"""
```

- [ ] **Step 16: 验证目录树与模块可导入**

```powershell
$root = "D:\progrom\services\aicore"
Push-Location $root
# 逐模块导入，任一失败即报错
& "$root\.venv\Scripts\python.exe" -c @"
import importlib, pkgutil, aicore
mods = [m.name for m in pkgutil.walk_packages(aicore.__path__, prefix='aicore.')]
failed = []
for m in mods:
    try:
        importlib.import_module(m)
    except Exception as e:
        failed.append((m, repr(e)))
print(f'共 {len(mods)} 个模块')
for m, e in failed:
    print('导入失败:', m, e)
raise SystemExit(1 if failed else 0)
"@
Pop-Location
```

Expected: `共 30 个模块`（数量允许 ±2），退出码 0，无导入失败

- [ ] **Step 17: 验证目录树与 spec §3.2 清单逐项一致**

对照 `docs/superpowers/specs/2026-09-16-aicore-architecture-design.md` §3.2 表格逐行核对目录与文件是否齐备；缺项即补齐。

- [ ] **Step 18: 提交**

```bash
git add services/aicore/src/aicore services/aicore/tests/structural
git commit -m "chore: 建立 AICORE 六层目录与模块契约空壳"
```

---
