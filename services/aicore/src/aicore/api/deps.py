"""依赖注入提供者（FastAPI Depends 装配点）。

设计要点：本模块只暴露**抽象依赖**（从 app.state 取已装配好的对象），
MUST NOT 在此构造具体 Provider / repository —— 具体实现只在 main.py 组合根注入，
否则 service 层会通过依赖注入间接依赖具体实现，分层契约形同虚设。
"""

from __future__ import annotations

from fastapi import Request

from aicore.core.config import Settings


def get_settings(request: Request) -> Settings:
    """返回组合根装配到 `app.state.settings` 的 Settings 实例。

    注意：`app.state.settings` 由组合根在启动期装配，在那之前调用本函数会抛 AttributeError
    （Starlette `State.__getattr__` 在属性缺失时即抛）。此处刻意不做兜底取值：
    配置缺失必须在启动/装配期暴露，用 getattr 默认值掩盖只会把误配置推迟到运行期。
    """
    # 显式落一个具名变量：`request.app.state` 是 Any，直接 return 会被 mypy 记为
    # 「returning Any from function declared to return Settings」；改回 `-> Any` 又会让
    # 类型注解失去意义。
    settings: Settings = request.app.state.settings
    return settings
