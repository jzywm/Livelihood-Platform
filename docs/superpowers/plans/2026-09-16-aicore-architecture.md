# AICORE 架构地基 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付 `services/aicore/` 的架构地基——可安装可启动的 Python 工程、可强制执行的分层契约、启动即校验的配置与横切关注点、以及带真实 MySQL 验证的数据层与分表路由，为第 4 组起的业务实现提供不会返工的边界。

**Architecture:** 单一 Python 服务（FastAPI + SQLAlchemy 2.x 同步会话 + 线程池），`core` / `api` / `service` / `provider` / `repository` / `port` 六层严格分层，分层规则由 `import-linter` 契约 + AST 结构断言固化为会变红的检查；`main.py` 是唯一装配点。

**Tech Stack:** Python 3.12+（本机 3.14.6）· FastAPI 0.141 · Pydantic 2.13 + pydantic-settings 2.15 · SQLAlchemy 2.0.54 · PyMySQL · Alembic · structlog · pytest 9 + pytest-asyncio + pytest-cov · import-linter 2.15 · ruff · mypy · MySQL 8.0.35

**Spec:** `docs/superpowers/specs/2026-09-16-aicore-architecture-design.md`（本计划的所有取值、口径校正与验收证据均出自该文档；执行者须同时阅读两者）

## Global Constraints

以下约束作用于**每一个任务**，逐条抄自 spec 已核实的权威口径，不得凭记忆改动：

- **成功码 = `0`**（`_common/openapi.yaml` L122「前端可用 `code === 0` 判断成功」）；**MUST NOT** 使用 `200`。
- **`Envelope` 必填四字段**：`code` / `message` / `traceId` / `timestamp`；`data` 可选；字段名 **camelCase**（`traceId`，非 `trace_id`）；`timestamp` 为 **UTC ISO 8601**。
- **限流的业务码是 `2004`**，不是 `429`——`429` 是 HTTP 状态码，**不在平台码表内**。
- **错误码只能取 `_common/openapi.yaml` `ErrorCode` 枚举内的值**：`0` `1001` `1002` `1003` `2001` `2002` `2003` `2004` `3001`–`3011` `4001`–`4004` `5000` `5001` `5002` `5003`。AICORE 用到：`1001`/`1002`/`1003`/`2001`/`2002`/`2004`/`3006`/`4003`/`5000`/`5002`。
- **traceId 请求头 = `X-Request-Id`**（`PDD` §8.5.1 L1750）；**MUST NOT** 使用 `X-Trace-Id`。
- **内部凭据请求头 = `X-Internal-Token`**；服务端间接口 **MUST NOT** 接受终端用户 JWT。
- **日志必含 12 字段**（PDD §8.5.1 L1747 逐字）：`time` / `level` / `app` / `service` / `module` / `traceId` / `spanId` / `uid` / `bizType` / `opCode` / `code` / `message`；**MUST NOT** 记录明文密钥、支付敏感信息、原始图像、未脱敏证件字段。
- **AI 超时 5s**（高并发 §7.6 L423）。
- **数据库**：独立库 `aicore`，MySQL 8，InnoDB，`utf8mb4`，时间 `datetime(3)`（UTC 存储、输出 Asia/Shanghai），置信度 `decimal(3,2)`，风险分 `decimal(5,2)`，数组用 JSON 列，**MUST NOT** 存原始图像或证件明文。**枚举值与 `openapi.yaml` `components.schemas` 一一对应**。
- **ID 策略**：`前缀 + UUID`，**总长 ≤32**（所有 ID 列均 `varchar(32)`）；前缀集 `task_` / `cor_` / `rev_` / `marker_` / `kan_` / `qa_`；**MUST NOT** 引入雪花 ID 或 workerId。
- **分片**：仅 `ai_task` / `ocr_result` / `ocr_correction` 三张按月分表（`_YYYYMM`）；查询 **MUST** 携带分片键下推；**MUST NOT** 跨分片 JOIN / 聚合 / 事务。
- **写后立即读强制走主库**（`er.md` §5.5）。
- **合规红线**：AI 只标记不决策（C8）；脱敏失败即拒绝外发（D4）；无人工复核结论不得回写权威数据（D5）；画像权重不进定价（R-07）。涉及处须在代码注释中同步标注。
- **提交规范**：Conventional Commits，type 英文 + 描述中文，**不带 `[AI]` 前缀**；提交前过 `commit-check` 门禁。
- **测试内 MUST NOT 出现任意 `sleep`**；等待走可控时钟或轮询断言。
- **覆盖率门禁 ≥80%**（`pytest --cov src/aicore`），`main.py` 与 `provider/` 真实通道骨架允许排除。

---

## 文件结构

先锁定职责，再据此拆任务。

```
services/aicore/
├── pyproject.toml                     依赖 + ruff/mypy/pytest/coverage 工具链配置
├── .importlinter                      import-linter 分层契约（INI 形式，UTF-8 无 BOM）
├── .gitignore                         Python 产物忽略
├── .env.example                       配置模板（仅占位符，无真实密钥）
├── src/aicore/
│   ├── __init__.py                    __version__
│   ├── main.py                        组合根：应用装配、生命周期、路由挂载（唯一注入具体实现处）
│   ├── core/
│   │   ├── config.py                  Settings 模型 + 启动校验（任务 2.1 / 2.2）
│   │   ├── errors.py                  异常层次 + 错误码常量 + 全局处理器（任务 2.3）
│   │   ├── envelope.py                统一响应信封（任务 2.4）
│   │   ├── trace.py                   traceId 上下文与传播（任务 2.5）
│   │   ├── logging.py                 结构化 JSON 日志（任务 2.6）
│   │   ├── idgen.py                   前缀化 ID（任务 3.8）
│   │   ├── security.py                内部 Token 校验（第 4 组，本阶段仅建空壳）
│   │   ├── ratelimit.py               Redis 令牌桶（第 4/9 组，空壳）
│   │   ├── budget.py                  成本三层护栏（第 9 组，空壳）
│   │   └── task_runner.py             任务执行器内核（第 4 组，空壳）
│   ├── api/
│   │   ├── health.py                  存活/就绪（任务 1.4）
│   │   ├── deps.py                    依赖注入提供者（任务 1.4）
│   │   ├── ocr.py / tasks.py / habit.py   空壳（第 4 组起实现）
│   ├── service/                       空壳目录（含 habit/ 子包与 task/registry.py）
│   ├── provider/
│   │   ├── base.py                    TextProvider / VisionProvider / OcrProvider Protocol
│   │   ├── selector.py / mock.py / deepseek.py / cloud_vision.py / cloud_ocr.py   空壳
│   ├── repository/
│   │   ├── sharding.py                分表路由（任务 3.3）
│   │   ├── session.py                 会话与连接池（任务 3.4）
│   │   ├── models.py                  SQLAlchemy 模型（任务 3.2）
│   │   ├── base.py                    repository 基类 + 跨分片守卫（任务 3.7）
│   │   ├── task_repo.py / ocr_repo.py / correction_repo.py / verdict_repo.py   （任务 3.7）
│   └── port/
│       ├── cred.py / dash.py / events.py    空壳（第 7 组）
├── tests/
│   ├── conftest.py                    夹具：配置 / ASGI 客户端 / 应用装配
│   ├── structural/                    结构断言专项（分层规则、AST 扫描）
│   │   ├── test_layering.py           import-linter + 分层守卫
│   │   └── test_source_guards.py      规则 5、6 的 AST 扫描
│   ├── unit/                          纯函数单测
│   ├── contract/                      契约测试
│   ├── repository/                    仓储测试（分表、迁移、er.md 比对）
│   └── api/                           接口测试
├── scripts/
│   └── compare_schema.py              三源交叉校验器（任务 3.6）
└── deploy/
    ├── Dockerfile                     多阶段、非 root、HEALTHCHECK
    └── sql/
        ├── ddl/                       11 个 DDL 文件（任务 3.1）
        └── migration/                 Alembic 环境（任务 3.5）
```

**已完成的准备**：探测用的 `.probe-venv/` 已存在且装好全部依赖（见任务 1.1 步骤 1 的迁移命令），**不要重新下载依赖**。

---

### Task 1.1: 工程骨架与工具链

**Files:**
- Create: `services/aicore/pyproject.toml`, `services/aicore/.gitignore`, `services/aicore/.env.example`
- Create: `services/aicore/src/aicore/__init__.py`, `services/aicore/tests/__init__.py`
- Create: `services/aicore/tests/conftest.py`

**Interfaces:**
- Consumes: 无（首个任务）
- Produces: 可 `import aicore` 的包；`aicore.__version__: str`；pytest 可收集 `tests/` 且 `pythonpath = ["src"]`

- [ ] **Step 1: 建立项目虚拟环境**

**MUST NOT 直接重命名 `.probe-venv`**（已实测：`lint-imports.exe` / `pytest.exe` 等控制台脚本内嵌了旧绝对路径，
改名后失效）。改为**新建**环境；pip 本地缓存已有 305 MB / 1169 个文件，安装无需重新下载。

```powershell
$root = "D:\progrom\services\aicore"
# 探测环境已完成使命，可整目录删除（185.7 MB）
if (Test-Path "$root\.probe-venv") { cmd /c "rmdir /s /q `"$root\.probe-venv`"" }
python -m venv "$root\.venv"
& "$root\.venv\Scripts\python.exe" --version
```

Expected: `Python 3.14.6`

> **沙箱注意**：`pip install` 需要创建 `0700` 权限的临时目录，本会话沙箱禁止写入此类目录，
> 故 pip 相关命令在沙箱下会报 `PermissionError: [Errno 13]`。执行者遇此报错时，
> **按规范对该条命令发起一次带授权的重试**（`sandbox_permissions: danger-full-access` + 一句话理由），
> 不要改用其他方式绕过。

- [ ] **Step 2: 写 `pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=69"]
build-backend = "setuptools.build_meta"

[project]
name = "aicore"
version = "0.1.0"
description = "AI 能力中心服务（AICORE）· 民生甄选平台"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.141",
    "uvicorn[standard]>=0.53",
    "pydantic>=2.13",
    "pydantic-settings>=2.15",
    "sqlalchemy>=2.0.54",
    "pymysql>=1.2",
    "redis>=8.1",
    "httpx>=0.28",
    "alembic>=1.20",
    "structlog>=24.0",
    "cryptography>=50.0",
    "pillow>=12.3",
]

[project.optional-dependencies]
dev = [
    "pytest>=9.1",
    "pytest-asyncio>=1.4",
    "pytest-cov>=7.1",
    "import-linter>=2.15",
    "ruff>=0.16",
    "mypy>=2.3",
]

[tool.setuptools.packages.find]
where = ["src"]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "W", "I", "N", "UP", "B", "C4", "SIM", "RUF"]

[tool.mypy]
python_version = "3.12"
strict = true
files = ["src"]

[[tool.mypy.overrides]]
module = ["tests.*"]
strict = false

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
asyncio_mode = "auto"
addopts = "-q"
markers = [
    "integration: 需要真实 MySQL / Redis 的端到端用例，默认不执行",
]

[tool.coverage.run]
source = ["src/aicore"]
omit = ["src/aicore/main.py", "src/aicore/provider/deepseek.py", "src/aicore/provider/cloud_vision.py", "src/aicore/provider/cloud_ocr.py"]

[tool.coverage.report]
fail_under = 80
```

**注意**：`structlog` 在探测环境中未安装，需在此步补装（见 Step 3）。

- [ ] **Step 3: 安装为可编辑包并补装 structlog**

```powershell
$root = "D:\progrom\services\aicore"
& "$root\.venv\Scripts\python.exe" -m pip install -e "$root[dev]" --quiet
& "$root\.venv\Scripts\python.exe" -m pip install structlog --quiet
& "$root\.venv\Scripts\python.exe" -c "import structlog; print('structlog', structlog.__version__)"
```

Expected: 打印 `structlog <版本>`，无报错

- [ ] **Step 4: 写 `.gitignore`**

```gitignore
__pycache__/
*.py[cod]
*.egg-info/
.venv/
venv/
.pytest_cache/
.mypy_cache/
.ruff_cache/
.import_linter_cache/
.coverage
htmlcov/
.env
.env.*
!.env.example
```

- [ ] **Step 5: 写 `.env.example`（仅占位符，MUST NOT 含真实密钥）**

```dotenv
# AICORE 环境变量模板 · 复制为 .env 后填写真实值（.env 已被 .gitignore 覆盖）
AICORE_APP_NAME=aicore
AICORE_ENV=dev
AICORE_LOG_LEVEL=INFO

# 数据库（独立库 aicore；本机测试库 aicore_test）
AICORE_MYSQL_HOST=127.0.0.1
AICORE_MYSQL_PORT=3306
AICORE_MYSQL_USER=<用户名>
AICORE_MYSQL_PASSWORD=<口令>
AICORE_MYSQL_DATABASE=aicore

# Redis（第 4 组起使用）
AICORE_REDIS_HOST=127.0.0.1
AICORE_REDIS_PORT=6379
AICORE_REDIS_DB=0

# 模型通道：mock | deepseek
AICORE_PROVIDER=mock
AICORE_DEEPSEEK_API_KEY=<密钥>

# 服务端间内部凭据（请求头 X-Internal-Token）
AICORE_INTERNAL_TOKEN=<内部凭据>
```

- [ ] **Step 6: 写 `src/aicore/__init__.py`**

```python
"""AI 能力中心服务（AICORE）· 民生甄选平台。

分层：core（横切）/ api（协议适配）/ service（业务编排）/ provider（外部模型通道）
     / repository（自有库访问）/ port（跨服务出向端口）。
分层依赖规则见 `.importlinter` 的 import-linter 契约与 tests/structural/。
"""

__version__ = "0.1.0"
```

- [ ] **Step 7: 写 `tests/conftest.py`（本任务仅最小可运行版本，Task 1.4 扩展）**

```python
"""全局测试夹具。

约定：测试内 MUST NOT 出现任意 sleep；等待一律走轮询断言或注入的时钟。
"""

from __future__ import annotations

import pytest


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"
```

- [ ] **Step 8: 写 `tests/__init__.py`（空文件）**

```python
```

- [ ] **Step 9: 验证安装与收集**

```powershell
$root = "D:\progrom\services\aicore"
& "$root\.venv\Scripts\python.exe" -c "import aicore; print('aicore', aicore.__version__)"
Push-Location $root
& "$root\.venv\Scripts\python.exe" -m pytest --collect-only -q
Pop-Location
```

Expected: 打印 `aicore 0.1.0`；pytest 退出码 5（未收集到用例）或 0，**不得出现导入错误**

- [ ] **Step 10: 验证无硬编码密钥**

```powershell
Push-Location D:\progrom\services\aicore
Select-String -Path "src\**\*.py","pyproject.toml",".env.example" -Pattern "password\s*=\s*['""][^<]" -ErrorAction SilentlyContinue
Pop-Location
```

Expected: 无输出（`.env.example` 中一律为 `<...>` 占位符）

- [ ] **Step 11: 提交**

```bash
git add services/aicore/pyproject.toml services/aicore/.gitignore services/aicore/.env.example services/aicore/src/aicore/__init__.py services/aicore/tests/__init__.py services/aicore/tests/conftest.py
git commit -m "chore: 搭建 AICORE 工程骨架与工具链"
```

---

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
"""结构化 JSON 日志（12 必含字段，PDD §8.5.1 L1747 逐字）。Task 2.6 实现。"""
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

### Task 1.3: 分层依赖规则固化为检查

**Files:**
- Create: `services/aicore/.importlinter`（import-linter 分层契约，INI 形式，**必须 UTF-8 无 BOM**）
- Modify: `services/aicore/tests/structural/test_layering.py`
- Create: `services/aicore/tests/structural/test_source_guards.py`

**Interfaces:**
- Consumes: Task 1.2 的六层包结构；`aicore.service.desensitize`、`aicore.service.verdict`（规则 6 的受检文件）
- Produces: `pytest` 可执行的分层契约检查；`tests/structural/test_source_guards.py` 提供 `iter_python_files() -> list[Path]` 与 `find_swallowed_exceptions(source: str) -> list[int]>` 两个可复用函数

**已实测的关键写法（不要改动）**：
1. import-linter 2.15 的公开入口是 `importlinter.application.use_cases.lint_imports`，且**必须先 `import importlinter.api`** 触发 `configuration.configure()`，否则 `USER_OPTION_READERS` 未注册、配置读不出来。
2. `forbidden_modules` 写 `aicore.provider` 会**连带禁止** `aicore.provider.base`；必须**精确列出具体实现模块**，并用 `ignore_imports` 放行 Protocol。
3. 配置文件中的中文契约名需要文件本身是 UTF-8；用 Python 写文件可确保编码。

- [ ] **Step 1: 先写阴性用例（验证检查会响）**

`tests/structural/test_layering.py`：

> **以仓库实际文件为准**：下面是首版参考模板，权威定义是
> `services/aicore/tests/structural/test_layering.py`。已落地的版本与本片段有三处差异，
> 照抄会把旧写法写回去：
> 1. 四条契约**各自**一条参数化阴性用例（`PROBES`），不是一条笼统的"注入违规"用例；
> 2. 所有 lint 调用传 `cache_dir=None` 关缓存，**不再**用 `shutil.rmtree` 清
>    `.import_linter_cache/`；
> 3. 另有「放行正例」与「抽掉 ignore_imports 必变红」两条反证用例。

```python
"""分层依赖规则检查。

对应 design.md「依赖方向规则」的 6 条禁止项，其中规则 1~4 由 import-linter 契约承载，
规则 5、6 见 tests/structural/test_source_guards.py。

阳性/阴性双向验证：契约在干净代码上必须通过；故意注入违规导入后必须失败。
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG = PROJECT_ROOT / ".importlinter"


@pytest.fixture(scope="module")
def lint() -> object:
    # 必须先 import importlinter.api：它调用 configuration.configure()，
    # 注册 USER_OPTION_READERS；只 import use_cases 会报 'USER_OPTION_READERS' KeyError。
    import importlinter.api  # noqa: F401
    from importlinter.application.use_cases import lint_imports

    return lint_imports


def test_layering_contracts_pass(lint: object) -> None:
    """干净代码上，全部分层契约必须通过。"""
    assert lint(config_filename=str(CONFIG), no_logo=True) is True


def test_violation_is_detected(lint: object) -> None:
    """阴性用例：往 api 层注入一处违规导入，契约必须变红。"""
    target = PROJECT_ROOT / "src" / "aicore" / "api" / "routes_probe.py"
    target.write_text(
        "from aicore.repository import task_repo  # 故意违规：api 不得直连 repository\n",
        encoding="utf-8",
    )
    try:
        importlib.invalidate_caches()
        assert lint(config_filename=str(CONFIG), no_logo=True) is False
    finally:
        target.unlink()
        importlib.invalidate_caches()
        # 缓存：shipped 版本所有 lint 调用都传 cache_dir=None，不再需要 rmtree 清理
        # （.import_linter_cache/ 根本不会生成）。

    assert lint(config_filename=str(CONFIG), no_logo=True) is True
```

- [ ] **Step 2: 运行，确认第一步失败（`.importlinter` 尚不存在）**

```powershell
$root = "D:\progrom\services\aicore"
Push-Location $root
& "$root\.venv\Scripts\python.exe" -m pytest tests/structural/test_layering.py -v
Pop-Location
```

Expected: FAIL —— `FileNotFoundError` 或 `lint_imports` 读配置报错

- [ ] **Step 3: 写 `.importlinter`（用 Python 写以确保 UTF-8）**

```powershell
# 注意：以下为参考模板。**权威定义是仓库中的 services/aicore/.importlinter 本身**——
# 该文件含多处实测得出的关键设置（allow_indirect_imports、递归通配 ignore_imports、
# unmatched_ignore_imports_alerting、aicore.provider 整包禁止），每处都带注释说明依据。
# 若本模板与之不一致，以实际文件为准；不要照抄本模板覆盖它。
$root = "D:\progrom\services\aicore"
& "$root\.venv\Scripts\python.exe" -c @"
from pathlib import Path
cfg = '''[importlinter]
root_package = aicore

[importlinter:contract:api-no-repo-provider]
name = api 层不得直接依赖 repository / provider
type = forbidden
# 必须显式写 true：forbidden 默认 false 会沿调用链报**传递**依赖，
# 而 api -> service -> repository 正是本设计的分层路径，实测会被误判为违规。
allow_indirect_imports = true
source_modules =
    aicore.api
forbidden_modules =
    aicore.repository
    aicore.provider

[importlinter:contract:service-provider-impl]
name = service 层只可与 provider.base 交互，不得依赖具体通道实现
type = forbidden
source_modules =
    aicore.service
forbidden_modules =
    aicore.provider
    aicore.provider.mock
    aicore.provider.selector
    aicore.provider.deepseek
    aicore.provider.cloud_vision
    aicore.provider.cloud_ocr
ignore_imports =
    aicore.service.** -> aicore.provider.base
# 必须写递归通配 `aicore.service.**`，不能写 `aicore.service`：实测（grimp 3.17）
# 非通配的 importer 名只精确匹配该模块自身、不覆盖子模块，而 service 的代码都在子模块里，
# 故非通配写法恒匹配不到任何边，是一条永远失效的放行声明。三种写法的实测对照：
#   aicore.service     -> aicore.provider.base  => 0 命中
#   aicore.service.*   -> aicore.provider.base  => 命中
#   aicore.service.**  -> aicore.provider.base  => 命中
# 另：forbidden 契约默认 unmatched_ignore_imports_alerting=error，放行表达式匹配不到真实
# 导入即判契约失败；当前各模块仍是空壳（尚无 service -> provider.base 的实际导入），用默认值
# 会让干净代码的正例直接变红。故设为 warn：正例通过，且放行写错时仍会留下警告线索。
unmatched_ignore_imports_alerting = warn

[importlinter:contract:no-reverse-dependency]
name = repository / provider / port 不得反向依赖 service
type = forbidden
source_modules =
    aicore.repository
    aicore.provider
    aicore.port
forbidden_modules =
    aicore.service

[importlinter:contract:core-independent]
name = core 不得依赖任何业务层
type = forbidden
source_modules =
    aicore.core
forbidden_modules =
    aicore.api
    aicore.service
    aicore.provider
    aicore.repository
    aicore.port
'''
Path(r'$root\.importlinter').write_text(cfg, encoding='utf-8')
print('.importlinter 已写入（UTF-8）')
"@
```

- [ ] **Step 4: 运行，确认全部用例通过（用例数以仓库实际文件为准，见 Step 1 提示）**

```powershell
$root = "D:\progrom\services\aicore"
Push-Location $root
& "$root\.venv\Scripts\python.exe" -m pytest tests/structural/test_layering.py -v
Pop-Location
```

Expected: 全部 passed。用例数以仓库实际文件为准：shipped 版本是四条契约的参数化阴性用例
（每条注入一处违规，并逐条确认其余三条契约仍 KEPT）+ 两条放行反证，不再是首版的 2 个。

- [ ] **Step 5: 写规则 5、6 的 AST 扫描用例**

> **修复轮 1 提示**：下面这段代码块是首版写法，规则 6 的扫描函数已被修复轮改写
> （不再下探嵌套 def/lambda/class/内层 except）。以
> `services/aicore/tests/structural/test_source_guards.py` 的实际内容为准，勿照抄本片段。**
>
> 豁免指令也以实际文件为准：shipped 实现是 `SWALLOW_EXEMPT_PATTERNS`（正式写法
> `# ai-allow-swallow: <理由>` + 兼容写法 `# noqa: ai-allow-swallow: <理由>`，两条正则、理由必填）
> 与 `has_swallow_exemption()`，而本片段只有一条只认正式写法的 `SWALLOW_EXEMPT`。

`tests/structural/test_source_guards.py`：

```python
"""结构扫描专项：import-linter 表达不了的两条合规红线。

规则 5：只有 provider/ 下的模块可以发起外部模型 HTTP 调用。
规则 6：service/desensitize.py 与 service/verdict.py MUST NOT 出现「异常后继续执行」
        的降级分支（D4 脱敏失败即拒绝、D5 无人工结论不回写）。

规则 6 取向为「偏严 + 显式豁免」：不含 raise 的 except 即判违规，
确需吞异常时必须写 `# ai-allow-swallow: <理由>` —— 宁可让人解释一次，也不漏掉。

> **修复轮 1 更正（评审 M9）**：豁免指令的正式写法是 `# ai-allow-swallow: <理由>`（不带 `noqa:` 前缀），
> 本文档下列片段已同步更新。早期口径 `# noqa: ai-allow-swallow: <理由>` 语法上仍被扫描接受，
> 但 ruff 会把 `ai-allow-swallow` 当成 noqa 规则码，每次使用都打印一条 `Invalid # noqa directive` 警告，
> 故新代码一律用不带前缀的正式写法。理由必填不变（裸指令不算豁免）。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC = PROJECT_ROOT / "src" / "aicore"

# 只允许在 provider/ 包内出现的模型调用库
MODEL_CALL_LIBS = ("httpx", "requests", "aiohttp")
HTTP_IMPORT_RE = re.compile(
    r"^\s*(?:import|from)\s+(" + "|".join(MODEL_CALL_LIBS) + r")\b", re.MULTILINE
)

GUARDED_FILES = ("service/desensitize.py", "service/verdict.py")
SWALLOW_EXEMPT = re.compile(r"#\s*ai-allow-swallow:\s*\S+")


def iter_python_files() -> list[Path]:
    return sorted(p for p in SRC.rglob("*.py") if "__pycache__" not in p.parts)


def find_swallowed_exceptions(source: str) -> list[int]:
    """返回「except 块内不含 raise」的行号列表（即静默降级点）。"""
    hits: list[int] = []
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        raises = any(isinstance(inner, ast.Raise) for stmt in node.body for inner in ast.walk(stmt))
        if not raises:
            hits.append(node.lineno)
    return hits


@pytest.mark.parametrize("path", iter_python_files(), ids=lambda p: str(p.relative_to(SRC)))
def test_model_http_calls_only_in_provider(path: Path) -> None:
    """规则 5：外部模型 HTTP 调用只允许出现在 provider/ 包内。"""
    if path.parts[len(SRC.parts)] == "provider":
        pytest.skip("provider 包是唯一允许发起外部模型调用的层")
    text = path.read_text(encoding="utf-8")
    found = HTTP_IMPORT_RE.findall(text)
    assert not found, f"{path.relative_to(PROJECT_ROOT)} 出现外部模型调用库 {found}，违反规则 5"


@pytest.mark.parametrize("relative", GUARDED_FILES)
def test_no_silent_degradation_in_guarded_files(relative: str) -> None:
    """规则 6：合规红线文件不得有「异常后继续执行」的分支。"""
    path = SRC / relative
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines()
    offenders = [
        lineno for lineno in find_swallowed_exceptions(source)
        if not SWALLOW_EXEMPT.search(lines[lineno - 1])
    ]
    assert not offenders, (
        f"{relative} 在第 {offenders} 行的 except 块中未重新抛出异常。"
        f"脱敏失败必须拒绝外发、无人工结论不得回写；确需吞异常请加 "
        f"`# ai-allow-swallow: <理由>` 显式豁免。"
    )


def test_guard_detects_swallowing(tmp_path: Path) -> None:
    """阴性用例：扫描函数必须能检出违规样本，且不误报合法样本。"""
    bad = "def f():\n    try:\n        return 1\n    except Exception:\n        return 2\n"
    good = "def f():\n    try:\n        return 1\n    except Exception as exc:\n        raise RuntimeError() from exc\n"
    assert find_swallowed_exceptions(bad) == [4]
    assert find_swallowed_exceptions(good) == []
```

- [ ] **Step 6: 运行全部结构用例**

```powershell
$root = "D:\progrom\services\aicore"
Push-Location $root
& "$root\.venv\Scripts\python.exe" -m pytest tests/structural -v
Pop-Location
```

Expected: 全部 passed（规则 5 的 provider 用例被 skip 属正常）

- [ ] **Step 7: 阴性验证——故意让规则 5 变红，确认检查会响**

临时在 `src/aicore/service/ocr_match.py` 追加一行 `import httpx`，重跑 Step 6。

Expected: `test_model_http_calls_only_in_provider[service/ocr_match.py]` FAIL。**验证后必须删除该行**并重跑确认恢复绿。

- [ ] **Step 8: 阴性验证——故意让规则 6 变红，确认检查会响**

临时把 `src/aicore/service/desensitize.py` 改为含 `try/except: return None` 的函数，重跑 Step 6。

Expected: `test_no_silent_degradation_in_guarded_files[service/desensitize.py]` FAIL。**验证后必须还原**并重跑确认恢复绿。

- [ ] **Step 9: 提交**

```bash
git add services/aicore/.importlinter services/aicore/tests/structural
git commit -m "test: 固化 AICORE 分层依赖规则与合规红线结构检查"
```

---

### Task 1.4: 组合根与应用装配

**Files:**
- Modify: `services/aicore/src/aicore/main.py`（Task 1.2 未建，本任务创建）
- Modify: `services/aicore/src/aicore/api/health.py`
- Modify: `services/aicore/src/aicore/api/deps.py`
- Modify: `services/aicore/tests/conftest.py`
- Create: `services/aicore/tests/api/test_health.py`

**Interfaces:**
- Consumes: `aicore.api.health`、`aicore.api.deps`
- Produces: `aicore.main.create_app() -> FastAPI`（工厂，供测试与部署复用）；`aicore.main.app: FastAPI`（模块级实例，`uvicorn aicore.main:app` 可用）；`tests/conftest.py` 的 `client` 与 `app` 夹具

**本任务不引入配置依赖**：`create_app()` 在 Task 1.4 阶段 MUST 能在**无任何环境变量**下启动（`/health` 不依赖数据库）。
必填项拒绝启动的行为在 Task 2.1/2.2 引入——那时会新增独立用例，不会让本任务的用例失效。

- [ ] **Step 1: 写失败测试**

`tests/api/test_health.py`：

```python
"""健康检查接口用例。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from aicore.main import create_app


def test_health_returns_200(client: TestClient) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_health_is_not_wrapped_in_envelope(client: TestClient) -> None:
    """存活探针必须是裸响应：被信封包住会让探针判定失效。"""
    body = client.get("/health").json()
    assert "code" not in body
    assert "traceId" not in body


def test_repeated_assembly_does_not_duplicate_routes() -> None:
    """重复装配 MUST NOT 产生重复注册。"""
    first = create_app()
    second = create_app()
    paths_first = sorted({r.path for r in first.routes})
    paths_second = sorted({r.path for r in second.routes})
    assert paths_first == paths_second
    assert len(paths_first) == len(set(paths_first))
```

- [ ] **Step 2: 运行，确认失败**

```powershell
$root = "D:\progrom\services\aicore"
Push-Location $root
& "$root\.venv\Scripts\python.exe" -m pytest tests/api/test_health.py -v
Pop-Location
```

Expected: FAIL —— `ModuleNotFoundError: No module named 'aicore.main'`

- [ ] **Step 3: 写 `api/health.py`**

```python
"""存活与就绪检查。

两个端点都必须返回**裸响应、不进信封**（信封由 core/envelope.py 在业务路由上落地）：
一旦被信封包裹，容器存活探针与负载均衡就绪判定都会失效。
Task 1.4 只实现进程存活；依赖就绪（MySQL / Redis / Provider 可达性）在 Task 11.1 扩展。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, Any]:
    """进程存活探针。不检查外部依赖。"""
    return {"status": "ok"}
```

- [ ] **Step 4: 写 `api/deps.py`**

```python
"""依赖注入提供者（FastAPI Depends 装配点）。

设计要点：本模块只暴露**抽象依赖**（从 app.state 取已装配好的对象），
MUST NOT 在此构造具体 Provider / repository —— 具体实现只在 main.py 组合根注入，
否则 service 层会通过依赖注入间接依赖具体实现，分层契约形同虚设。
"""

from __future__ import annotations

from typing import Any

from fastapi import Request


def get_settings(request: Request) -> Any:
    """返回组合根装配的 Settings 实例。Task 2.1 定类型。"""
    return request.app.state.settings
```

- [ ] **Step 5: 写 `main.py`**

```python
"""AICORE 组合根。

**唯一允许把具体 Provider / repository 实现注入 service 的位置。**
其余各层 MUST NOT 自行构造具体实现（由 `.importlinter` 的 import-linter 契约强制）。

路由路径不含 `/api/v1` 前缀：GATEWAY 已用 RewritePath 去前缀，
故本服务路由与 openapi.yaml 一致，为 `/aicore/**` 与 `/health`。
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from aicore import __version__
from aicore.api import health


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """启动与关闭钩子。

    启动即校验配置（Task 2.2）、装配依赖（Task 3.4 起）、
    启动任务执行器（第 4 组）都将挂在这里。
    """
    yield


def create_app() -> FastAPI:
    """应用工厂。测试与部署共用，保证装配路径唯一。"""
    app = FastAPI(
        title="AI 能力中心服务（AICORE）",
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs",
        openapi_url="/openapi.json",
    )
    app.include_router(health.router)
    return app


app = create_app()
```

- [ ] **Step 6: 扩展 `tests/conftest.py`**

```python
"""全局测试夹具。

约定：测试内 MUST NOT 出现任意 sleep；等待一律走轮询断言或注入的时钟。
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from aicore.main import create_app


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def app() -> FastAPI:
    return create_app()


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    # 用 with 语句进入上下文，才会真正触发 lifespan（启动钩子）；直接构造不会触发。
    with TestClient(app) as c:
        yield c
```

- [ ] **Step 7: 运行，确认全部通过**

```powershell
$root = "D:\progrom\services\aicore"
Push-Location $root
& "$root\.venv\Scripts\python.exe" -m pytest tests/api -v
Pop-Location
```

Expected: `3 passed`

- [ ] **Step 8: 验证真实进程可启动并响应**

```powershell
$root = "D:\progrom\services\aicore"
$proc = Start-Process -FilePath "$root\.venv\Scripts\python.exe" `
  -ArgumentList "-m","uvicorn","aicore.main:app","--port","8083","--host","127.0.0.1" `
  -PassThru -WindowStyle Hidden -RedirectStandardOutput "$root\uvicorn.log" -RedirectStandardError "$root\uvicorn.err"
Start-Sleep -Seconds 6
try {
  $r = Invoke-WebRequest -Uri "http://127.0.0.1:8083/health" -UseBasicParsing -TimeoutSec 5
  Write-Output "HTTP $($r.StatusCode)  body=$($r.Content)"
} finally {
  Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
  Remove-Item "$root\uvicorn.log","$root\uvicorn.err" -ErrorAction SilentlyContinue
}
```

Expected: `HTTP 200  body={"status":"ok"}`

- [ ] **Step 9: 提交**

```bash
git add services/aicore/src/aicore/main.py services/aicore/src/aicore/api services/aicore/tests
git commit -m "feat: 实现 AICORE 组合根与存活检查"
```

---

## 第 1 组验收（全部通过后方可进入第 2 组）

- [ ] `pip install -e .` 成功，`python -c "import aicore"` 无错
- [ ] `pytest --collect-only` 可收集全部测试，无导入错误
- [ ] `lint-imports` 全绿；**阴性用例证明注入违规即变红**
- [ ] 规则 5、6 的 AST 扫描各经一次阴性验证（故意违规 → 变红 → 还原 → 复绿）
- [ ] `uvicorn aicore.main:app` 启动成功，`GET /health` 返回 200
- [ ] 全量 `pytest` 通过
- [ ] 向用户展示上述命令的**原始输出**并取得确认

---

## 第 2 组：配置与横切关注点

> **粒度说明**：第 2 组的步骤级细节在**第 1 组验收通过后**补齐。原因：第 1 组会用真实运行结果校准若干实现细节
> （`Settings` 的实际字段类型、异常处理器与 FastAPI 校验错误的对接方式、structlog 的处理链配置），
> 提前写死具体代码会与刚刚验证过的实现产生冲突。每组接口与验收标准在此已固定，不会漂移。
> 这是分组交付的既定节奏（spec §1.2 / §8），不是遗漏。

### Task 2.1: 配置模型

**Files:**
- Modify: `services/aicore/src/aicore/core/config.py`
- Modify: `services/aicore/src/aicore/api/deps.py`（`get_settings` 定类型）
- Create: `services/aicore/tests/unit/test_config.py`

**Interfaces:**
- Consumes: 无
- Produces: `aicore.core.config.Settings`（Pydantic `BaseSettings` 子类，`env` 为 `dev|test|prod`）；
  `aicore.core.config.get_settings() -> Settings`（带缓存）；`Settings` 字段名与 `.env.example` 的 `AICORE_` 前缀变量一一对应

**关键取向**：必填项**不给默认值**（默认值会把配置错误隐藏到运行时）；`extra="forbid"`（写了不存在的项要报错）。

- [ ] Step 1~N：先写失败用例（字段级校验：必填缺失即抛 `ValidationError`），再实现 `Settings`，
  再验证 `grep` 无硬编码密钥、`.env` 被 `.gitignore` 覆盖

**验收**：配置加载用例通过；缺失必填项抛错；不存在配置项抛错；`get_settings()` 返回同一实例（缓存）

### Task 2.2: 启动四条校验

**Files:**
- Modify: `services/aicore/src/aicore/core/config.py`
- Create: `services/aicore/tests/unit/test_config_startup.py`

**Interfaces:**
- Consumes: `Settings`
- Produces: 跨字段校验逻辑（`model_post_init` 或 `model_validator(mode="after")`）；
  `aicore.core.config.ConfigRejected` 异常（启动校验失败时抛出，含阻断级错误清单）

**四条规则（已实测 4/4 可达）**：
1. `env=prod` + `provider=mock` → 拒绝启动
2. 真实通道被选中但密钥缺失 → 拒绝启动
3. `dev` / `test` 允许降级 `mock` 并**输出告警**（不阻断）
4. 数据库 / Redis / 配额与预算阈值等必填项缺失 → 拒绝启动，**不兜默认值**

**字段级错误与跨字段规则错误分开报告**（运维排查时最忌"哪错了"说不清）。

- [ ] Step 1~N：四类组合各写一条断言用例（`prod+mock`、`prod+缺密钥`、`dev+缺密钥`、`prod+必填缺失`）

**验收**：四类组合各有用例且行为符合预期；违规时**进程拒绝启动**（抛错而非仅告警）

### Task 2.3: 异常层次与错误码映射

**Files:**
- Modify: `services/aicore/src/aicore/core/errors.py`
- Create: `services/aicore/tests/unit/test_errors.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `AiCoreError(Exception)` 基类，含 `code: int` 与 `message: str`
  - 子类：`ParamError`（`1001`/`1002`/`1003`）、`UnauthorizedError`（`2001`）、`ForbiddenError`（`2002`）、
    `RateLimitedError`（`2004`）、`NotFoundError`（`3006`）、`ChannelFailureError`（`4003`）、
    `DependencyTimeoutError`（`5002`）
  - `register_exception_handlers(app: FastAPI) -> None`（在 `main.py` 中调用）
  - `AICORE_ERROR_CODES: frozenset[int]`（本服务用到的码值集合，供比对用例使用）

**硬约束（Global Constraints 复述）**：码值只能取 `_common/openapi.yaml` `ErrorCode` 枚举内的值；
限流用 `2004` **不是** `429`；FastAPI 默认 `422` **必须收编**为 `1001`/`1002`/`1003`；未预期异常归 `5000`，
**堆栈只进日志、不进响应体**。

- [ ] Step 1~N：先写每条异常 → 码值的映射用例，再写「未预期异常不泄露堆栈」用例，
  再写「`AICORE_ERROR_CODES` 与 `_common/openapi.yaml` 枚举逐项比对」用例（**阴性方向**：出现枚举外的码即失败）

**验收**：七类异常映射用例通过；未预期异常归 `5000` 且响应体不含堆栈/内部路径；
码值比对用例通过且能拦截枚举外的码

### Task 2.4: 统一信封

**Files:**
- Modify: `services/aicore/src/aicore/core/envelope.py`
- Modify: `services/aicore/src/aicore/main.py`（不必改，信封由 `response_model` 落地）
- Create: `services/aicore/tests/unit/test_envelope.py`

**Interfaces:**
- Consumes: `core/trace.py`（`traceId` 取值）
- Produces: `Envelope[T]` 泛型模型，必填 `code` / `message` / `traceId` / `timestamp`，可选 `data`；
  `Envelope.ok(data: T) -> Envelope[T]`（`code=0`）；`Envelope.fail(code: int, message: str) -> Envelope[None]`

**硬约束**：成功码 = **`0`**；`traceId` 为 **camelCase**；`timestamp` 为 **UTC ISO 8601**；
**MUST NOT** 用全局中间件包响应（会把 `/health`、`/metrics` 一起包住，使探针与 Prometheus 抓取失效）。

- [ ] Step 1~N：先写四必填字段序列化用例与 `code=0` 用例，再写
  「`/health` 与 `/metrics` 不被信封包裹」断言，最后写「业务代码无手工拼装信封」的结构性断言

**验收**：四必填字段齐全；成功响应 `code=0`；`/health`、`/metrics` 为裸响应；无手工拼装残留

### Task 2.5: traceId 上下文传播

**Files:**
- Modify: `services/aicore/src/aicore/core/trace.py`
- Modify: `services/aicore/src/aicore/main.py`（挂中间件）
- Create: `services/aicore/tests/unit/test_trace.py`

**Interfaces:**
- Consumes: 无
- Produces: `TRACE_ID_HEADER = "X-Request-Id"`；`get_trace_id() -> str`；
  `set_trace_id(value: str) -> None`；`new_trace_id() -> str`（16 位 hex）；
  `TraceIdMiddleware`（ASGI 中间件）；`copy_context_for_thread()`（跨线程池传递用）

**硬约束**：请求头是 **`X-Request-Id`**（不是 `X-Trace-Id`）；网关未注入时**自行生成**且该行为
**在日志中可区分**（加标记字段），以免掩盖网关故障；**跨线程池（`run_in_executor`）必须显式传递**
——丢失 traceId 是典型的静默故障。

- [ ] Step 1~N：先写「注入 → 透传」「未注入 → 自行生成且可区分」两条用例，
  再写「跨线程池后仍能取到同一 traceId」用例

**验收**：两条路径用例通过；跨线程池用例通过；生成行为在日志字段中可区分

### Task 2.6: 结构化 JSON 日志

**Files:**
- Modify: `services/aicore/src/aicore/core/logging.py`
- Modify: `services/aicore/src/aicore/main.py`（启动时初始化）
- Create: `services/aicore/tests/unit/test_logging.py`

**Interfaces:**
- Consumes: `core/trace.py` 的 `get_trace_id()`；`core/config.py` 的 `Settings.log_level`
- Produces: `configure_logging(settings: Settings) -> None`；`get_logger(module: str) -> structlog.BoundLogger`；
  `REQUIRED_LOG_FIELDS: frozenset[str]`（12 字段常量，供用例比对）

**硬约束**：必含 12 字段 `time` / `level` / `app` / `service` / `module` / `traceId` / `spanId` / `uid` /
`bizType` / `opCode` / `code` / `message`（字段名与 PDD §8.5.1 L1747 **逐字一致**）；
**`spanId` 输出字段但值为空**（`design.md` D9 明确不接 SkyWalking agent，不假装有埋点）；
**MUST NOT** 记录明文密钥、未脱敏证件字段、原始图像。

- [ ] Step 1~N：先写「输出为合法 JSON 且含全部 12 字段」用例，再写
  「`spanId` 存在且为空」用例，最后写「构造含证件号的输入，断言日志中不出现明文」用例

**验收**：12 字段 schema 用例通过；`spanId` 留空；敏感信息不出现在日志

---

## 第 3 组：数据层与分表路由

### Task 3.1: DDL

**Files:**
- Create: `services/aicore/deploy/sql/ddl/00_create_database.sql`
- Create: `services/aicore/deploy/sql/ddl/10_ai_task.template.sql`、`11_ocr_result.template.sql`、`12_ocr_correction.template.sql`
- Create: `services/aicore/deploy/sql/ddl/20_vision_review.sql` ~ `25_vision_qa_log.sql`（6 个）
- Create: `services/aicore/tests/repository/test_ddl_matches_er.py`

**Interfaces:**
- Consumes: 无
- Produces: 11 个 DDL 文件；分片表模板中的物理表名占位符统一为 `{table}`（供 Task 3.3 幂等建表套用）

**硬约束**：字段与类型**严格对齐 `er.md` v1.2 §6 数据字典**；InnoDB + `utf8mb4`；时间 `datetime(3)`；
置信度 `decimal(3,2)`；风险分 `decimal(5,2)`；**枚举值与 `openapi.yaml` `components.schemas` 一一对应**。

**外键（依 `er.md` FK 标注）**：`ocr_correction.task_id` → 当月 `ocr_result`（**同月同分片，模板内声明**）；
`vision_marker` / `review_verdict` / `kitchen_anomaly` 的 `review_id` → `vision_review.review_id`（不分片，声明物理外键）；
`ocr_result.task_id` → `ai_task.task_id` **不建物理外键**（跨月分片表间无法建），逻辑关联 + 幂等补偿。

**建表顺序**：当月 `ai_task` → `ocr_result` → `ocr_correction`（被引用表先建）。

- [ ] Step 1: 写 9 张表的 DDL（逐列对照 `er.md` §6）
- [ ] Step 2: 在真实 MySQL 上执行（连接信息见 spec §2.4 / §8.1），确认零错误
- [ ] Step 3: 写「DDL 与 `er.md` §6 逐列比对」用例（纯文本解析，无需数据库）

**验收**：DDL 在真实 MySQL 8 执行成功；与 `er.md` 逐列比对无缺项、无类型偏差

### Task 3.2: SQLAlchemy 模型

**Files:**
- Modify: `services/aicore/src/aicore/repository/models.py`
- Create: `services/aicore/tests/unit/test_models.py`

**Interfaces:**
- Consumes: 无
- Produces: 9 个声明式模型类 `AiTask` / `OcrResult` / `OcrCorrection` / `VisionReview` / `VisionMarker` /
  `ReviewVerdict` / `KitchenAnomaly` / `RiskPredictResult` / `VisionQaLog`；
  `Base`（`DeclarativeBase` 子类）；`LOGICAL_TABLE_NAMES: dict[type, str]`

**关键点**：分片表**不写死表名**（由 Task 3.3 动态绑定）；`Mapped[]` 风格且 mypy 通过。

**验收**：模型元数据导出字段与 `er.md` 数据字典比对一致；`mypy` 通过

### Task 3.3: 按月分表路由

**Files:**
- Modify: `services/aicore/src/aicore/repository/sharding.py`
- Create: `services/aicore/tests/repository/test_sharding.py`

**Interfaces:**
- Consumes: `repository/models.py` 的模型与 `LOGICAL_TABLE_NAMES`
- Produces:
  - `physical_table_name(logical: str, at: datetime) -> str`（→ `xxx_YYYYMM`）
  - `shard_month_of(task_id_or_created_at) -> str`（`YYYYMM`）
  - `ensure_month_tables(conn, month: str) -> None`（幂等建表，按 `ai_task → ocr_result → ocr_correction` 顺序）
  - `MissingShardKeyError(AiCoreError)`（缺分片键时抛出；`code=1001`）
  - `CrossShardOperationError(AiCoreError)`（跨分片操作被拒；`code=1003`）

**硬约束**：查询**必须携带分片键下推**——缺失时**直接抛错**，MUST NOT 退化为全表扫描；
**MUST NOT** 跨分片 JOIN / 聚合 / 事务。

- [ ] Step 1~N：先写跨月写入路由用例、跨月边界查询用例，再写
  「缺分片键 → 抛 `MissingShardKeyError`」用例、「跨分片 JOIN → 抛 `CrossShardOperationError`」用例，
  再实现，最后用**可控时钟**（非 sleep）验证跨月边界

**验收**：跨月路由与边界用例通过；缺分片键抛错；跨分片操作被拒；测试内无 `sleep`

### Task 3.4: 会话与连接池

**Files:**
- Modify: `services/aicore/src/aicore/repository/session.py`
- Create: `services/aicore/tests/repository/test_session.py`

**Interfaces:**
- Consumes: `core/config.py` 的 `Settings`
- Produces: `build_engine(settings, *, read_only: bool) -> Engine`；`write_session()` / `read_session()`
  上下文管理器；`SessionFactory` 装配类型（供 `main.py` 注入）

**硬约束**：**同步会话 + 线程池**（非 async driver）；写会话与只读会话**分离**；
**写后立即读强制走主库**；池大小**从配置读取，不写死**。

**验收**：会话生命周期用例通过；只读查询走只读会话；池大小随配置变化

### Task 3.5: Schema 迁移

**Files:**
- Create: `services/aicore/deploy/sql/migration/`（Alembic 环境：`env.py`、`script.py.mako`、`versions/`）
- Create: `services/aicore/alembic.ini`
- Create: `services/aicore/tests/repository/test_migration.py`

**Interfaces:**
- Consumes: `repository/models.py` 的 `Base.metadata`；`deploy/sql/ddl/**`
- Produces: `alembic upgrade head` 可从空库建出目标结构；迁移钩子承接分片物理表创建

**关键设计**：**纯 SQL DDL 是权威定义**；版本化迁移**从 `Base.metadata` 生成**，不手写第二份 DDL；
两条路径结果由 Task 3.6 的三源交叉校验强制一致。遵循 expand-migrate-contract（**禁止破坏性 DDL**）。

**验收**：空库从零迁移到目标结构可复现；重复执行幂等；`alembic upgrade head` 结果与直接执行 DDL 一致

### Task 3.6: 三源一致性自动比对

**Files:**
- Create: `services/aicore/scripts/compare_schema.py`
- Create: `services/aicore/tests/repository/test_schema_consistency.py`

**Interfaces:**
- Consumes: `deploy/sql/ddl/**`、`repository/models.py`、`../../docs/er.md`、可选 `information_schema`
- Produces:
  - `parse_ddl(text: str) -> dict[str, list[ColumnSpec]]`
  - `parse_er_md(text: str) -> dict[str, list[ColumnSpec]]`
  - `from_metadata(metadata) -> dict[str, list[ColumnSpec]]`
  - `from_information_schema(conn, database: str) -> dict[str, list[ColumnSpec]]`
  - `diff(a, b) -> list[str]`（人可读差异清单）
  - `main()`（有 MySQL 时跑三源，无则跑两源并打印说明）

**这是本组最值钱的一项**：tasks 原文只要求「DDL ↔ `er.md`」两方比对，那样**模型层写错了照样漏检**——
而模型才是业务代码真正使用的东西。三源之后，「文档改了代码没改」「代码改了文档没改」「模型与 DDL 走偏」
三类全部会被抓到。

- [ ] Step 1~N：先实现三个纯文本/元数据解析器（无需数据库），再实现 `diff`，
  再写**三个方向的阴性用例**（改 DDL、改 `er.md`、改模型，各自必须失败），最后接入 `information_schema` 第四路

**验收**：正常态通过；**三个方向各验一次单边改动皆失败**；有 MySQL 时叠加真实库结构校验通过

### Task 3.7: repository 层数据访问

**Files:**
- Modify: `services/aicore/src/aicore/repository/base.py`、`task_repo.py`、`ocr_repo.py`、`correction_repo.py`、`verdict_repo.py`
- Create: `services/aicore/tests/repository/test_repos.py`

**Interfaces:**
- Consumes: `repository/session.py`、`repository/sharding.py`、`repository/models.py`
- Produces: `TaskRepo` / `OcrRepo` / `CorrectionRepo` / `VerdictRepo`，各自提供
  `insert(session, entity)`、`get_by_id(session, id, *, shard_key)`、`update_status(...)` 等方法（**所有读取方法签名必须收分片键**）

**事务边界（`er.md` §5.3）**：单表一事务；同分片跨表可合并；**跨分片拆为多次独立事务 + 幂等补偿**，
**MUST NOT** 引入分布式事务。

**验收**：四类存取用例通过；跨分片操作断言**不开启**分布式事务

### Task 3.8: 前缀化 ID

**Files:**
- Modify: `services/aicore/src/aicore/core/idgen.py`
- Create: `services/aicore/tests/unit/test_idgen.py`

**Interfaces:**
- Consumes: 无
- Produces: `ID_PREFIXES: dict[str, str]`（`task`/`cor`/`rev`/`marker`/`kan`/`qa` 六种）；
  `new_id(kind: str) -> str`；`validate_id(value: str, kind: str | None = None) -> bool`

**硬约束**：`前缀 + UUID`，**总长 ≤32**；**MUST NOT** 引入雪花 ID 或 workerId（`er.md` §5.4 L247）。

**这是本组最容易写错的一项**：裸 UUID 是 36 字符，**超限 4 位**。故生成时**校验总长 ≤32，超限即抛错**
（而非静默截断）。

- [ ] Step 1~N：先写「六种前缀各生成一次并校验总长 ≤32」用例，再写
  「并发生成 1 万个 ID 无重复且全量通过正则」用例，再实现

**验收**：1 万个 ID 全过正则（总长 ≤32）且无重复；6 种前缀各验一次

---

## 第 3 组验收（全部通过后本阶段完成）

- [ ] DDL 在真实 MySQL 8 执行成功
- [ ] 三源交叉比对正常态通过；**三个方向单边改动各失败一次**
- [ ] 跨月写入与边界查询用例通过（可控时钟，无 `sleep`）
- [ ] 缺分片键抛错用例、跨分片操作被拒用例通过
- [ ] 只读会话分离用例通过；池大小随配置变化
- [ ] 空库零到目标结构可复现；重复执行幂等
- [ ] 1 万个 ID 全过正则且无重复
- [ ] 全量 `pytest` 通过；`pytest --cov src/aicore` **≥80%**
- [ ] `commit-check` 门禁通过；提交信息不带 `[AI]` 前缀
- [ ] 向用户展示上述命令的**原始输出**并取得确认

---

## Self-Review 记录

**1. Spec 覆盖**：spec §3（第 1 组 4 项）、§4（第 2 组 6 项）、§5（第 3 组 8 项）、§6（测试架构）
均有对应 Task；spec §2 的权威口径全部落入 Global Constraints；spec §7 的偏差项在相关 Task 中标注
（V1 落在 Task 1.1 的 `requires-python`，V2/V3 落在 Task 2.6 的 `spanId`，V4 在第 4 组起生效）。
**无遗漏**。

**2. 占位符扫描**：第 1 组为完整步骤级细节，无 TBD / "类似 Task N" / 无代码的代码步骤。
第 2、3 组为「接口 + 验收」级，已在组首**显式说明补全时机与原因**，不以占位符伪装完成。

**3. 类型一致性**：跨任务引用已核对——`Settings`（2.1）→ `configure_logging(settings)`（2.6）；
`AiCoreError`（2.3）→ `MissingShardKeyError(AiCoreError)`（3.3）；`LOGICAL_TABLE_NAMES`（3.2）→
`physical_table_name`（3.3）；`Base.metadata`（3.2）→ 迁移（3.5）与比对（3.6）；
`iter_python_files()` / `find_swallowed_exceptions()`（1.3）在 Task 1.3 内自洽。
**无命名漂移**。

