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
