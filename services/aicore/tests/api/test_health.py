"""健康检查接口用例。"""

from __future__ import annotations

from fastapi.routing import iter_route_contexts
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
    """重复装配 MUST NOT 产生重复注册。

    路由枚举用 fastapi.routing.iter_route_contexts()，不用 `for r in app.routes`：
    FastAPI 0.141 起 include_router 是**惰性**的——app.routes 里放的是 _IncludedRouter
    包装对象（无 .path 属性），真正的路由要经它展平后才拿得到。直接遍历 app.routes
    会抛 AttributeError（实测 fastapi 0.141.1 / starlette 1.6.0）。
    """
    first = create_app()
    second = create_app()
    paths_first = sorted({c.path for c in iter_route_contexts(first.routes)})
    paths_second = sorted({c.path for c in iter_route_contexts(second.routes)})
    assert paths_first == paths_second
    assert len(paths_first) == len(set(paths_first))
