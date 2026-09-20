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
