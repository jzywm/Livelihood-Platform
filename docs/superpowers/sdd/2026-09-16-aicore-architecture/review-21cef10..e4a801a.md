# Review package 21cef10..e4a801a

## Commits

e4a801a feat: 实现 AICORE 组合根与存活检查

## Stat

 services/aicore/src/aicore/api/deps.py   | 18 ++++++++++++-
 services/aicore/src/aicore/api/health.py | 21 ++++++++++++++-
 services/aicore/src/aicore/main.py       | 44 ++++++++++++++++++++++++++++++++
 services/aicore/tests/api/__init__.py    |  0
 services/aicore/tests/api/test_health.py | 37 +++++++++++++++++++++++++++
 services/aicore/tests/conftest.py        | 18 +++++++++++++
 6 files changed, 136 insertions(+), 2 deletions(-)

## Diff

```diff
diff --git a/services/aicore/src/aicore/api/deps.py b/services/aicore/src/aicore/api/deps.py
index b1eaa28..b868765 100644
--- a/services/aicore/src/aicore/api/deps.py
+++ b/services/aicore/src/aicore/api/deps.py
@@ -1 +1,17 @@
-"""依赖注入提供者（FastAPI Depends 装配点）。Task 1.4 填实。"""
+"""依赖注入提供者（FastAPI Depends 装配点）。
+
+设计要点：本模块只暴露**抽象依赖**（从 app.state 取已装配好的对象），
+MUST NOT 在此构造具体 Provider / repository —— 具体实现只在 main.py 组合根注入，
+否则 service 层会通过依赖注入间接依赖具体实现，分层契约形同虚设。
+"""
+
+from __future__ import annotations
+
+from typing import Any
+
+from fastapi import Request
+
+
+def get_settings(request: Request) -> Any:
+    """返回组合根装配的 Settings 实例。Task 2.1 定类型。"""
+    return request.app.state.settings
diff --git a/services/aicore/src/aicore/api/health.py b/services/aicore/src/aicore/api/health.py
index fc26a10..a3369ff 100644
--- a/services/aicore/src/aicore/api/health.py
+++ b/services/aicore/src/aicore/api/health.py
@@ -1 +1,20 @@
-"""存活与就绪检查。Task 1.4 实现。"""
+"""存活与就绪检查。
+
+两个端点都必须返回**裸响应、不进信封**（信封由 core/envelope.py 在业务路由上落地）：
+一旦被信封包裹，容器存活探针与负载均衡就绪判定都会失效。
+Task 1.4 只实现进程存活；依赖就绪（MySQL / Redis / Provider 可达性）在 Task 11.1 扩展。
+"""
+
+from __future__ import annotations
+
+from typing import Any
+
+from fastapi import APIRouter
+
+router = APIRouter(tags=["health"])
+
+
+@router.get("/health")
+async def health() -> dict[str, Any]:
+    """进程存活探针。不检查外部依赖。"""
+    return {"status": "ok"}
diff --git a/services/aicore/src/aicore/main.py b/services/aicore/src/aicore/main.py
new file mode 100644
index 0000000..e0e6b23
--- /dev/null
+++ b/services/aicore/src/aicore/main.py
@@ -0,0 +1,44 @@
+"""AICORE 组合根。
+
+**唯一允许把具体 Provider / repository 实现注入 service 的位置。**
+其余各层 MUST NOT 自行构造具体实现（由 `.importlinter` 的 import-linter 契约强制）。
+
+路由路径不含 `/api/v1` 前缀：GATEWAY 已用 RewritePath 去前缀，
+故本服务路由与 openapi.yaml 一致，为 `/aicore/**` 与 `/health`。
+"""
+
+from __future__ import annotations
+
+from collections.abc import AsyncIterator
+from contextlib import asynccontextmanager
+
+from fastapi import FastAPI
+
+from aicore import __version__
+from aicore.api import health
+
+
+@asynccontextmanager
+async def lifespan(app: FastAPI) -> AsyncIterator[None]:
+    """启动与关闭钩子。
+
+    启动即校验配置（Task 2.2）、装配依赖（Task 3.4 起）、
+    启动任务执行器（第 4 组）都将挂在这里。
+    """
+    yield
+
+
+def create_app() -> FastAPI:
+    """应用工厂。测试与部署共用，保证装配路径唯一。"""
+    app = FastAPI(
+        title="AI 能力中心服务（AICORE）",
+        version=__version__,
+        lifespan=lifespan,
+        docs_url="/docs",
+        openapi_url="/openapi.json",
+    )
+    app.include_router(health.router)
+    return app
+
+
+app = create_app()
diff --git a/services/aicore/tests/api/__init__.py b/services/aicore/tests/api/__init__.py
new file mode 100644
index 0000000..e69de29
diff --git a/services/aicore/tests/api/test_health.py b/services/aicore/tests/api/test_health.py
new file mode 100644
index 0000000..3889775
--- /dev/null
+++ b/services/aicore/tests/api/test_health.py
@@ -0,0 +1,37 @@
+"""健康检查接口用例。"""
+
+from __future__ import annotations
+
+from fastapi.routing import iter_route_contexts
+from fastapi.testclient import TestClient
+
+from aicore.main import create_app
+
+
+def test_health_returns_200(client: TestClient) -> None:
+    resp = client.get("/health")
+    assert resp.status_code == 200
+    assert resp.json()["status"] == "ok"
+
+
+def test_health_is_not_wrapped_in_envelope(client: TestClient) -> None:
+    """存活探针必须是裸响应：被信封包住会让探针判定失效。"""
+    body = client.get("/health").json()
+    assert "code" not in body
+    assert "traceId" not in body
+
+
+def test_repeated_assembly_does_not_duplicate_routes() -> None:
+    """重复装配 MUST NOT 产生重复注册。
+
+    路由枚举用 fastapi.routing.iter_route_contexts()，不用 `for r in app.routes`：
+    FastAPI 0.141 起 include_router 是**惰性**的——app.routes 里放的是 _IncludedRouter
+    包装对象（无 .path 属性），真正的路由要经它展平后才拿得到。直接遍历 app.routes
+    会抛 AttributeError（实测 fastapi 0.141.1 / starlette 1.6.0）。
+    """
+    first = create_app()
+    second = create_app()
+    paths_first = sorted({c.path for c in iter_route_contexts(first.routes)})
+    paths_second = sorted({c.path for c in iter_route_contexts(second.routes)})
+    assert paths_first == paths_second
+    assert len(paths_first) == len(set(paths_first))
diff --git a/services/aicore/tests/conftest.py b/services/aicore/tests/conftest.py
index f66bf05..e9af55b 100644
--- a/services/aicore/tests/conftest.py
+++ b/services/aicore/tests/conftest.py
@@ -1,13 +1,31 @@
 """全局测试夹具。

 约定：测试内 MUST NOT 出现任意 sleep；等待一律走轮询断言或注入的时钟。
 """

 from __future__ import annotations

+from collections.abc import Iterator
+
 import pytest
+from fastapi import FastAPI
+from fastapi.testclient import TestClient
+
+from aicore.main import create_app


 @pytest.fixture(scope="session")
 def anyio_backend() -> str:
     return "asyncio"
+
+
+@pytest.fixture
+def app() -> FastAPI:
+    return create_app()
+
+
+@pytest.fixture
+def client(app: FastAPI) -> Iterator[TestClient]:
+    # 用 with 语句进入上下文，才会真正触发 lifespan（启动钩子）；直接构造不会触发。
+    with TestClient(app) as c:
+        yield c

```
