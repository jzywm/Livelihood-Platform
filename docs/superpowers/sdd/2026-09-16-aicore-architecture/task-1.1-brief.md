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
分层依赖规则见 setup.cfg 的 import-linter 契约与 tests/structural/。
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
