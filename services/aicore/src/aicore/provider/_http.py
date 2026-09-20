"""三个真实通道共用的 httpx 客户端工厂与请求/响应零件（Task 4.3）。

## 本模块的边界（三条硬约束，全部来自工单 §3.2）

1. **`build_client` 是 provider 包内唯一构造 httpx 客户端的地方**。三个通道 MUST NOT
   自己 `httpx.AsyncClient(...)`：那会让「超时 / 头 / base_url 的口径」出现三份实现，
   而 `tests/structural/test_source_guards.py` 的规则 5 只保证「HTTP 调用不越出
   provider 包」，管不到包内是否各写一套。
2. **密钥只经请求头传递**：MUST NOT 进 URL query、MUST NOT 进日志、MUST NOT 进异常消息。
   三条各有落点：
   - URL：`_reject_url_credentials()` 在构造客户端前拒绝带 query / fragment / userinfo
     的 `base_url`（那是「密钥被塞进 URL」的现实形态），且**异常消息不回显该 URL**
     ——否则校验器自己成了泄漏点；
   - 日志：本模块只记 `base_url` 与超时，MUST NOT 记 `api_key` 或整个请求头字典；
   - 异常消息：`provider/errors.py` 的 `reason` 只有 `http-503` / `transport-error`
     这类判别依据，不含 URL、不含头。
3. **MUST NOT 用真实计费地址做默认值**：`base_url` 由调用方给出，三个通道各有一个模块级
   默认常量（`DEFAULT_DEEPSEEK_BASE_URL` 等），且**常量在调用时读取**（模块全局查找），
   使用例可以用 `monkeypatch` 把它指到 RFC 2606 的 `.invalid` 假地址——即使打桩全部失效，
   `.invalid` 也解析不出来，不会产生一分钱计费。

## 为什么客户端是「一次调用一个」（而不是长驻连接池）

`build_client` 的签名（工单 §3.2 逐字）只接受 `timeout_s`，而超时**逐次可传**是
`provider/base.py` 的硬要求（「超时必须能从调用侧传入而不是藏在实现里写死」）。
一次调用一个客户端让「超时」与「客户端」一一对应，代价是没有连接复用。
**这是骨架阶段的有意取舍**：云通道在合规门打开前不可用（见 `cloud_ocr.py` 的
`COMPLIANCE_READY`），连接池要等真实接入、真实容量标定（《高并发》§4.4 的 ★ 项）
才有基准可调。已列入 Task 4.3 报告的「没做到的事」。
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlsplit

import httpx

from aicore.provider.errors import ProviderChannelFailureError

__all__ = [
    "AUTH_HEADER",
    "AUTH_SCHEME",
    "MALFORMED_REASON",
    "auth_headers",
    "build_client",
    "decode_json",
    "malformed_response",
    "require_positive_timeout",
]

_logger = logging.getLogger(__name__)

#: 密钥请求头名。三个通道共用一种形式（骨架阶段的统一口径）。
#:
#: 真实接入时若某厂商要求别的头（例如 `X-Api-Key` 或签名头），**只改这一处常量**：
#: 在通道里各写一份头构造，就等于把「密钥怎么传」这件事散成三份会漂移的实现。
AUTH_HEADER = "Authorization"

#: 密钥请求头的 scheme（`Authorization: Bearer <key>`）。
AUTH_SCHEME = "Bearer"

#: 畸形响应的 `reason`（工单 §3.3 逐字钉死的取值）。
MALFORMED_REASON = "malformed-response"


def auth_headers(api_key: str) -> dict[str, str]:
    """把通道密钥渲染成请求头——**密钥的唯一传递形式**。

    单独成函数（而不是塞进 `build_client`）是为了让用例能取到**同一份**头口径去
    断言「密钥确实在头里、且只在头里」，而不是在测试里另写一份 `Bearer ...` 字符串
    （那样测试验的是测试自己）。
    """
    return {AUTH_HEADER: f"{AUTH_SCHEME} {api_key}"}


def build_client(*, base_url: str, api_key: str, timeout_s: float) -> httpx.AsyncClient:
    """构造通道 HTTP 客户端（provider 包内**唯一**的构造点）。

    - `timeout=httpx.Timeout(timeout_s)`：四个维度（connect / read / write / pool）
      统一取该值。`Settings.ai_call_timeout_s` 是**单次模型调用**的总预算，
      分维度配置在骨架阶段没有依据（《高并发》L298 只写了「连接超时 / 读超时 / 写超时
      按依赖分」，没有给 AI 通道的分维度数值）；
    - 密钥只进请求头（见 `auth_headers`）；
    - **不校验密钥是否为空**：密钥的缺失由启动校验兜（`core/config.py` 规则 2，
      经 `_REAL_PROVIDER_KEY_FIELDS` 登记），工厂只负责「密钥怎么传」。
      云通道尚未登记密钥字段（`_REAL_PROVIDERS_WITHOUT_KEY_FIELD`），
      真实接入前它们本来就过不了合规门。
    """
    _reject_url_credentials(base_url)
    _logger.debug(
        "构造通道 HTTP 客户端：base_url=%s timeout_s=%s（密钥只经请求头传递，不进日志）",
        base_url,
        timeout_s,
    )
    return httpx.AsyncClient(
        base_url=base_url,
        timeout=httpx.Timeout(timeout_s),
        headers=auth_headers(api_key),
    )


def decode_json(
    response: httpx.Response,
    *,
    provider: str,
    operation: str,
) -> Any:
    """解析响应体 JSON；**不是 JSON 一律显式失败**（MUST NOT 静默返回空结果）。

    为什么必须在这里转成通道失败：`response.json()` 抛的是 `json.JSONDecodeError`
    （`ValueError` 子类）。它若原样上抛，`guard.guarded_call` 会按「编程错误」处理
    ——于是「对端返回了一个 HTML 错误页」会伪装成我方的 bug，而运维的处置动作
    完全不同（查通道 vs 改代码）。
    """
    try:
        return response.json()
    except ValueError as exc:
        raise malformed_response(provider, operation) from exc


def malformed_response(provider: str, operation: str) -> ProviderChannelFailureError:
    """畸形响应（缺字段 / 类型不对 / 不是 JSON）→ `4003`，`reason` 逐字 `malformed-response`。

    构造异常而**不抛出**：调用方用 `raise ... from exc` 保留因果链，也能在
    `except` 之外先记日志。`reason` MUST NOT 附带字段路径或响应片段——
    那是 `errors.py` 说的「给运维看的判别依据」字段，不是错误详情通道；
    详情走日志（且只记字段名，MUST NOT 记字段值）。
    """
    return ProviderChannelFailureError(provider, operation, reason=MALFORMED_REASON)


def require_positive_timeout(timeout_s: float, *, provider: str, operation: str) -> float:
    """校验调用侧声明的超时是正数，并原样返回。

    为什么按**编程错误**（`ValueError`，由 `guard.guarded_call` 原样上抛）而不是归到通道失败：
    `timeout_s=0`（或负数）会让 `asyncio.wait_for` 立刻超时，于是「调用方把超时算错了」
    会伪装成 `5002 依赖超时`——运维照着通道与网络方向排查，而真正的 bug 在调用点。
    与工单 §2.1.3「`ValueError` / `TypeError` 之类编程错误 MUST NOT 被吞成通道失败」同向。
    """
    if timeout_s <= 0:
        raise ValueError(
            f"{provider}.{operation} 的 timeout_s 必须为正数，收到 {timeout_s!r}："
            "这是调用方的编程错误，MUST NOT 被当成通道超时"
        )
    return timeout_s


def _reject_url_credentials(base_url: str) -> None:
    """拒绝携带 query / fragment / userinfo 的 `base_url`。

    这是约束 2 的**可执行形态**：只要 `base_url` 能带 query，「密钥进 URL」就只是一个
    约定；而它一旦进了 URL，就会同时出现在 httpx 的异常消息
    （`Server error '401' for url 'https://x?key=...'`）、访问日志与中间代理日志里。

    **异常消息刻意不回显该 URL**：`ValueError` 会进调用方的日志与测试输出，
    回显等于把要防的东西抄了一遍。判据只看「有没有这几段」，不解析参数名。
    """
    parts = urlsplit(base_url)
    if parts.query or parts.fragment or parts.username or parts.password:
        raise ValueError(
            "base_url MUST NOT 携带 query / fragment / userinfo："
            f"通道密钥只允许经请求头传递（provider/_http.py 的 {AUTH_HEADER}）；"
            "本异常刻意不回显该 URL"
        )
