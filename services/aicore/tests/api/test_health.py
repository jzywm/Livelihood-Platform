"""健康检查接口用例。"""

from __future__ import annotations

from collections import Counter

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
    # 全等比较严格强于逐字段排查（原写法只看 code/traceId 两个字段）：
    # 信封的 code / message / traceId / timestamp / data 任一混入都会让本行变红。
    assert body == {"status": "ok"}


def test_repeated_assembly_does_not_duplicate_routes() -> None:
    """重复装配 MUST NOT 产生重复注册。

    路由枚举用 fastapi.routing.iter_route_contexts()，不用 `for r in app.routes`：
    FastAPI 0.141 起 include_router 是**惰性**的——app.routes 里放的是 _IncludedRouter
    包装对象（无 .path 属性），真正的路由要经它展平后才拿得到。直接遍历 app.routes
    会抛 AttributeError（实测 fastapi 0.141.1 / starlette 1.6.0）。

    断言取**去重前**的路径列表：集合比较对「重复注册」是瞎的——两次装配各注册两遍，
    两侧集合依然相等。module 级 health.router 是共享单例，任何在它身上累积状态的装配
    路径都会命中本用例，故这里必须逐条计数：

    - Counter 相等：两次装配互不累积（first 上多出来的注册不会出现在 second 上）；
    - `/health` 恰好一次：单次装配自身不重复注册，兼作**非空哨兵**——若上面的展平 API
      失效导致枚举为空，本行立刻变红，不会退化成 [] == [] 静默通过。

    不写成「任何路径都至多一次」（如 Counter(...).most_common(1)[0][1] == 1）：同一路径
    合法地可以承载多个方法/路由上下文（后续组的 GET+POST 同路径），那种写法会制造假失败；
    这里只对确定的单方法路径 /health 收紧。
    """
    first = create_app()
    second = create_app()
    paths_first = [c.path for c in iter_route_contexts(first.routes)]
    paths_second = [c.path for c in iter_route_contexts(second.routes)]
    assert Counter(paths_first) == Counter(paths_second)  # 两次装配互不累积
    assert paths_first.count("/health") == 1  # 单次装配不重复注册，兼作非空哨兵
