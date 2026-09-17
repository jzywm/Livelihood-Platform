"""依赖注入提供者（FastAPI Depends 装配点）。

设计要点：本模块只暴露**抽象依赖**（从 app.state 取已装配好的对象），
MUST NOT 在此构造具体 Provider / repository —— 具体实现只在 main.py 组合根注入，
否则 service 层会通过依赖注入间接依赖具体实现，分层契约形同虚设。
"""

from __future__ import annotations

from typing import Any

from fastapi import Request


def get_settings(request: Request) -> Any:
    """返回组合根装配的 Settings 实例。Task 2.1 定类型。

    注意：`app.state.settings` 由 Task 2.1 装配，在那之前调用本函数会抛 AttributeError
    （Starlette `State.__getattr__` 在属性缺失时即抛）。此处刻意不做兜底取值：
    配置缺失必须在启动/装配期暴露，用 getattr 默认值掩盖只会把误配置推迟到运行期。
    """
    return request.app.state.settings
