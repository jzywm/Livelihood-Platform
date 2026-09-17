"""api/deps.py 依赖提供者的契约用例。

覆盖目标：`get_settings` MUST 原样交出组合根装配到 `app.state` 上的对象——
不自行构造、不包装、不做类型转换。这条契约一旦被破坏（例如本模块偷偷 `Settings()`），
service 层就会通过依赖注入间接绑上具体实现，分层契约形同虚设。
"""

from __future__ import annotations

from types import SimpleNamespace

from aicore.api.deps import get_settings


def test_get_settings_returns_assembled_instance() -> None:
    """装配什么就返回什么：以 sentinel 断言**同一性**（is），而不是相等性。"""
    sentinel = object()
    # 桩请求：get_settings 只要求 request.app.state.settings 这一条取值路径。
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(settings=sentinel)))

    assert get_settings(request) is sentinel  # type: ignore[arg-type]
