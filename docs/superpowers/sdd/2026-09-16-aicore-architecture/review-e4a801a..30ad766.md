# Review package e4a801a..30ad766

## Commits

30ad766 fix: 修复重复注册守卫的恒真断言并补依赖契约用例

## Stat

 services/aicore/src/aicore/api/deps.py   |  7 ++++++-
 services/aicore/tests/api/test_deps.py   | 21 +++++++++++++++++++++
 services/aicore/tests/api/test_health.py | 27 +++++++++++++++++++++------
 3 files changed, 48 insertions(+), 7 deletions(-)

## Diff

```diff
diff --git a/services/aicore/src/aicore/api/deps.py b/services/aicore/src/aicore/api/deps.py
index b868765..d4b9adc 100644
--- a/services/aicore/src/aicore/api/deps.py
+++ b/services/aicore/src/aicore/api/deps.py
@@ -6,12 +6,17 @@ MUST NOT 在此构造具体 Provider / repository —— 具体实现只在 main
 """

 from __future__ import annotations

 from typing import Any

 from fastapi import Request


 def get_settings(request: Request) -> Any:
-    """返回组合根装配的 Settings 实例。Task 2.1 定类型。"""
+    """返回组合根装配的 Settings 实例。Task 2.1 定类型。
+
+    注意：`app.state.settings` 由 Task 2.1 装配，在那之前调用本函数会抛 AttributeError
+    （Starlette `State.__getattr__` 在属性缺失时即抛）。此处刻意不做兜底取值：
+    配置缺失必须在启动/装配期暴露，用 getattr 默认值掩盖只会把误配置推迟到运行期。
+    """
     return request.app.state.settings
diff --git a/services/aicore/tests/api/test_deps.py b/services/aicore/tests/api/test_deps.py
new file mode 100644
index 0000000..0b87bd7
--- /dev/null
+++ b/services/aicore/tests/api/test_deps.py
@@ -0,0 +1,21 @@
+"""api/deps.py 依赖提供者的契约用例。
+
+覆盖目标：`get_settings` MUST 原样交出组合根装配到 `app.state` 上的对象——
+不自行构造、不包装、不做类型转换。这条契约一旦被破坏（例如本模块偷偷 `Settings()`），
+service 层就会通过依赖注入间接绑上具体实现，分层契约形同虚设。
+"""
+
+from __future__ import annotations
+
+from types import SimpleNamespace
+
+from aicore.api.deps import get_settings
+
+
+def test_get_settings_returns_assembled_instance() -> None:
+    """装配什么就返回什么：以 sentinel 断言**同一性**（is），而不是相等性。"""
+    sentinel = object()
+    # 桩请求：get_settings 只要求 request.app.state.settings 这一条取值路径。
+    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(settings=sentinel)))
+
+    assert get_settings(request) is sentinel  # type: ignore[arg-type]
diff --git a/services/aicore/tests/api/test_health.py b/services/aicore/tests/api/test_health.py
index 3889775..292751e 100644
--- a/services/aicore/tests/api/test_health.py
+++ b/services/aicore/tests/api/test_health.py
@@ -1,37 +1,52 @@
 """健康检查接口用例。"""

 from __future__ import annotations

+from collections import Counter
+
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
-    assert "code" not in body
-    assert "traceId" not in body
+    # 全等比较严格强于逐字段排查（原写法只看 code/traceId 两个字段）：
+    # 信封的 code / message / traceId / timestamp / data 任一混入都会让本行变红。
+    assert body == {"status": "ok"}


 def test_repeated_assembly_does_not_duplicate_routes() -> None:
     """重复装配 MUST NOT 产生重复注册。

     路由枚举用 fastapi.routing.iter_route_contexts()，不用 `for r in app.routes`：
     FastAPI 0.141 起 include_router 是**惰性**的——app.routes 里放的是 _IncludedRouter
     包装对象（无 .path 属性），真正的路由要经它展平后才拿得到。直接遍历 app.routes
     会抛 AttributeError（实测 fastapi 0.141.1 / starlette 1.6.0）。
+
+    断言取**去重前**的路径列表：集合比较对「重复注册」是瞎的——两次装配各注册两遍，
+    两侧集合依然相等。module 级 health.router 是共享单例，任何在它身上累积状态的装配
+    路径都会命中本用例，故这里必须逐条计数：
+
+    - Counter 相等：两次装配互不累积（first 上多出来的注册不会出现在 second 上）；
+    - `/health` 恰好一次：单次装配自身不重复注册，兼作**非空哨兵**——若上面的展平 API
+      失效导致枚举为空，本行立刻变红，不会退化成 [] == [] 静默通过。
+
+    不写成「任何路径都至多一次」（如 Counter(...).most_common(1)[0][1] == 1）：同一路径
+    合法地可以承载多个方法/路由上下文（后续组的 GET+POST 同路径），那种写法会制造假失败；
+    这里只对确定的单方法路径 /health 收紧。
     """
     first = create_app()
     second = create_app()
-    paths_first = sorted({c.path for c in iter_route_contexts(first.routes)})
-    paths_second = sorted({c.path for c in iter_route_contexts(second.routes)})
-    assert paths_first == paths_second
-    assert len(paths_first) == len(set(paths_first))
+    paths_first = [c.path for c in iter_route_contexts(first.routes)]
+    paths_second = [c.path for c in iter_route_contexts(second.routes)]
+    assert Counter(paths_first) == Counter(paths_second)  # 两次装配互不累积
+    assert paths_first.count("/health") == 1  # 单次装配不重复注册，兼作非空哨兵

```
