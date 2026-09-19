"""DeepSeek 文本通道（Task 4.3 骨架）。

`TextProvider` 的第一个真实实现：请求构造 + 响应解析 + 超时 / 重试 / 熔断 + 合规门。
**外部模型 HTTP 调用只发生在 `provider/` 包内**（tasks.md 4.3 的结构性要求），
且包内唯一的 httpx 构造点是 `provider/_http.py`。

## 合规门（`COMPLIANCE_READY = True`）

- `cloud_vision` / `cloud_ocr` = `False`：`产品设计文档.md:1832` 逐字
  「已完成（协议:M2 前签署）」——M1 尚未签署，理由见另两个文件的模块 docstring。
- `deepseek` = `True`，**但这是本实现里证据最弱的一处，如实登记**：

  **它没有直接的可引用出处。** 控制者与 P 阶段独立评审分别核对过：

  - `产品设计文档.md:1618`（7.4 大模型对话合规）把「M0 确认数据合规条款（不用于训练 /
    留存策略）、数据不出域」写进条款，状态栏未见；
  - `产品设计文档.md:1832` 的「签数据合规协议」讲的是**云视觉 API**，与文本通道无关；
  - `产品设计文档.md:1623`（7.9 AI 辅助边界）同样只提云视觉；
  - **`产品设计文档.md:1826` 的状态栏逐字是「用户+运营 / M0」**——即
    「DeepSeek 数据合规条款」这一项**尚未完成**。

  初版本文件的 docstring 把 `:1623` 当作 DeepSeek 对话侧的合规依据，
  **那是误读**（该行主语是云视觉），由独立评审指出、控制者复核后确认。

  **为什么不因此把它改成 `False`**（控制者的裁定 + 需要用户注意）：
  `spec.md:86` 的合规前置条款**明确只针对「送往云视觉 API 的图像」**；
  文本通道送的是**脱敏后的文本**（`产品设计文档.md:1618` 的「输入脱敏前置」），
  不在该条覆盖范围内。把 `False` 套到文本通道上是把一条"图像出域"的条款
  扩张到"文本调用"上，等于自造约束；而 `False` 会让 `provider=deepseek` 的每一次
  调用都以 4003 失败——那是把一个真实可用的通道锁死。
  **故行为保持 `True`，但把「无出处」这件事写在代码里**，而不是继续引用一行不相关的文档。
  真正的合规确认属平台侧动作（`产品设计文档.md:1826` 的 M0 项），
  本层只负责「状态可核对、未就绪拒绝」这个机制。

`spec.md:86` 逐字：「送往云视觉 API 的图像 MUST 处于已签署的数据合规协议之下……
合规协议状态 MUST 可被核对，**未取得协议时系统 MUST NOT 调用该通道**」；`spec.md:95-96`
要求「拒绝调用该通道并告警」。故本常量是**可核对的合规状态**，方法在构造请求之前查它。

**MUST NOT 用「异常后继续执行」的分支去兼容合规未就绪**：`design.md:171` 禁止项 6 的形态
正是「异常后继续执行」（它硬约束 `service/desensitize.py` 与 `service/verdict.py`，
本处取向相同）。合规未就绪就是拒绝调用，没有降级路径。

## 已知边界（有意取舍，逐条列在 Task 4.3 报告里）

- `ProviderResult.raw` 不回填：`results.py` 对该字段的硬约束是「MUST NOT 含未脱敏的证件值」，
  而本层是最靠近外部通道的一层、**没有能力判断**返回内容是否已脱敏。排障以 taskId 对齐通道侧日志。
- `ProviderIdentity.thresholds` 取空 dict：判定阈值的所有者是 Task 4.10（「阈值可配并留痕」），
  `Settings` 里尚无对应字段；在 provider 里硬编码 0.9 / 0.7 会与 4.10 的可配阈值形成
  两份会漂移的口径（`results.py` 已明确「默认空字典是合法的」）。
- 一次调用一个 httpx 客户端（无连接复用），理由见 `_http.py` 模块 docstring。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from typing import Any, Never

from aicore.core.config import Settings
from aicore.provider import _http
from aicore.provider.errors import ProviderChannelFailureError
from aicore.provider.guard import (
    CircuitBreaker,
    GuardConfig,
    StepClock,
    guard_config_from,
    guarded_call,
)
from aicore.provider.results import Channel, ProviderIdentity, ProviderResult

__all__ = [
    "CHAT_COMPLETIONS_PATH",
    "COMPLIANCE_READY",
    "DEFAULT_DEEPSEEK_BASE_URL",
    "DeepSeekTextProvider",
]

_logger = logging.getLogger(__name__)

#: 通道实现名。逐字对齐 `core/config.py` 的 `provider` 字面量与 `.env.example` 的注释
#: （`mock | deepseek | cloud_vision | cloud_ocr`）——落 `model_meta.provider`。
NAME = "deepseek"

#: 通道**类别**（`er.md` §6.1 的 `model_meta.channel`）。注解用 `results.py` 的 `Channel`：
#: 它是 `Literal["TEXT", "VISION", "OCR"]`，写错类别在 `mypy --strict` 就报错，
#: 而不是等到 `ProviderIdentity.__post_init__` 在运行期抛。
CHANNEL: Channel = "TEXT"

#: 操作名（进 `ProviderError.operation`，用于把「哪个操作坏了」说清楚）。
OPERATION_COMPLETE = "complete"

#: 合规状态（依据见模块 docstring）。云通道为 `False`。
COMPLIANCE_READY: bool = True

#: 默认 base URL。**只在调用时读取**（模块全局查找）：用例用 `monkeypatch` 把它指到
#: RFC 2606 的 `.invalid` 假地址，故它 MUST NOT 在任何模块级结构里被提前固化。
DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"

#: chat 补全路径。
CHAT_COMPLETIONS_PATH = "/chat/completions"

#: 模型版本。**带通道前缀**（工单 §3.1）：跨通道血缘里只看到 `v1` 是无法定位模型的。
MODEL_VERSION = "deepseek-chat-v1"

#: Prompt 版本。同带通道前缀。
PROMPT_VERSION = "deepseek-chat-prompt-v1"


class DeepSeekTextProvider:
    """DeepSeek 文本通道（`TextProvider` 的结构子类型实现之一）。

    本类是**骨架**：请求 / 响应契约、三类失败归一、护栏与合规门都已落地并被用例覆盖。
    M1 阶段它是三个真实通道里**唯一**合规门为开的一个（云视觉 / 云 OCR 依据
    `产品设计文档.md:1832`「协议:M2 前签署」保持关闭）。
    """

    name: str = NAME
    model_version: str = MODEL_VERSION
    prompt_version: str = PROMPT_VERSION

    def __init__(
        self,
        config: Settings,
        *,
        breaker: CircuitBreaker | None = None,
        clock: StepClock | None = None,
    ) -> None:
        """`config` 提供四项护栏参数与密钥；`breaker` / `clock` 可注入（用例注入假时钟）。

        未注入 `breaker` 时本实例自建一个（键是 `(provider, operation)`，见 `guard.py`）；
        注入的 `breaker` 与 `config` 的护栏参数**各自独立生效**：前者决定「什么时候熔断」，
        后者决定「超时多久、最多重试几次」。
        """
        self._config = config
        self._guard_config: GuardConfig = guard_config_from(config)
        self._breaker: CircuitBreaker = (
            CircuitBreaker(self._guard_config, clock=clock) if breaker is None else breaker
        )
        self._clock = clock
        self._call_count = 0

    @property
    def call_count(self) -> int:
        """通道方法被调用的次数（Task 4.9「幂等重提不重复调用」的断言口径）。

        **数的是「方法被调用」，不是「真的发出了 HTTP」**：被合规门或熔断挡下的调用同样 +1
        ——Task 4.9 要回答的是「服务层有没有又调了一次通道」，那正是计数目标。
        「真实外发了几次」另有独立可核证据：`httpx.MockTransport` 的 handler 计数（见用例）。
        """
        return self._call_count

    async def complete(
        self,
        *,
        prompt: str,
        payload: Mapping[str, Any],
        timeout_s: float,
    ) -> ProviderResult:
        """文本补全：`POST /chat/completions` → 解析 `choices[0].message.content`。

        失败一律抛 `provider/errors.py` 的三类异常，MUST NOT 返回空结果
        （`base.py` 对该方法的逐字要求）。
        """
        self._call_count += 1
        _require_compliance(OPERATION_COMPLETE)
        effective_timeout = self._effective_timeout_s(
            _http.require_positive_timeout(
                timeout_s,
                provider=NAME,
                operation=OPERATION_COMPLETE,
            )
        )
        body: dict[str, Any] = {
            "model": MODEL_VERSION,
            "messages": _build_messages(prompt, payload),
        }
        result: ProviderResult = await guarded_call(
            provider=NAME,
            operation=OPERATION_COMPLETE,
            config=self._guard_config,
            breaker=self._breaker,
            send=lambda: self._exchange(body, timeout_s=effective_timeout),
            clock=self._clock,
        )
        return result

    def model_meta(self) -> dict[str, Any]:
        """渲染 `ai_task.model_meta`（`er.md` §6.1）——**委托** `ProviderIdentity.as_model_meta()`。

        MUST NOT 手拼 dict：键名是跨文档契约（camelCase），三通道各拼一次迟早分叉
        （`base.py` 的 `model_meta` docstring 逐字要求委托）。
        """
        return self._identity().as_model_meta()

    def _identity(self) -> ProviderIdentity:
        """本次调用的血缘：`channel` 是**类别**、`provider` 是**实现名**，两者不可合并。

        `thresholds` 走默认空 dict（理由见模块 docstring 的已知边界）。
        """
        return ProviderIdentity(
            channel=CHANNEL,
            provider=NAME,
            model_version=MODEL_VERSION,
            prompt_version=PROMPT_VERSION,
        )

    def _effective_timeout_s(self, declared_s: float) -> float:
        """调用侧声明的超时与平台护栏 `ai_call_timeout_s` 取**较小值**。

        两者都是上限、都要成立：任务级（Task 4.6「处理器声明自身超时」）不能突破通道级
        护栏，通道级护栏也不该把任务声明的更短预算拉长。取小是同时满足两者的唯一口径。
        """
        return min(declared_s, self._config.ai_call_timeout_s)

    async def _exchange(self, body: Mapping[str, Any], *, timeout_s: float) -> ProviderResult:
        """一次 HTTP 交换 + 解析（作为 `guarded_call` 的 `send`：**每次重试都重跑它**）。

        用 `async with client` 保证异常路径也会关闭连接（骨架阶段一次调用一个客户端，
        见 `_http.py` 的取舍说明）。
        """
        client = _http.build_client(
            base_url=DEFAULT_DEEPSEEK_BASE_URL,
            api_key=self._config.deepseek_api_key or "",
            timeout_s=timeout_s,
        )
        async with client:
            response = await client.post(CHAT_COMPLETIONS_PATH, json=dict(body))
            response.raise_for_status()
            decoded = _http.decode_json(response, provider=NAME, operation=OPERATION_COMPLETE)
        text, confidence = _parse_completion(decoded)
        return ProviderResult(identity=self._identity(), text=text, confidence=confidence)


def _build_messages(prompt: str, payload: Mapping[str, Any]) -> list[dict[str, str]]:
    """把「模板 + 变量」拼成 chat 消息。

    - `prompt` → `system` 消息。`base.py` 说它是「模板标识或模板文本」，两种形态都直接
      作为 system 内容：本层**不做模板渲染**（渲染与 prompt 版本管理属 service 层；
      渲染放这里会让「prompt 版本」与「模板内容」在通道层各留一份副本）；
    - `payload` → `user` 消息，`json.dumps(..., sort_keys=True, ensure_ascii=False)`。
      **key 排序是刻意的**：同一 payload 必须产生逐字节相同的请求体，否则幂等重提在通道侧
      看起来是两次不同的请求（Task 4.9 的口径），排障时也无法用请求体与日志对账。
      MUST NOT 用 `default=str` 兜底：那会把「payload 里有不可序列化的值」这种调用方 bug
      悄悄变成一条正常的模型请求（`guard.py` 的分类表：编程错误 MUST 原样上抛）。

    **送出的内容是否已脱敏由调用方负责**（`service/desensitize.py`），本层不校验——
    校验放这里等于给「跳过脱敏」留了一个可以通过的入口（`base.py` 对 VISION 的同一条口径）。
    """
    return [
        {"role": "system", "content": prompt},
        {"role": "user", "content": json.dumps(dict(payload), ensure_ascii=False, sort_keys=True)},
    ]


def _parse_completion(payload: Any) -> tuple[str, float | None]:
    """解析 `choices[0].message.content` → `(text, confidence)`。

    `confidence` **取通道返回值，缺失则为 `None`**（MUST NOT 补 0：`results.py` 明确
    「没有置信度」与「置信度为 0」是两回事，补 0 会在 Task 4.10 被判成 `LOW` 并误触人工复核）。
    畸形响应一律 `malformed-response` 显式失败，MUST NOT 静默返回空结果。
    """
    if not isinstance(payload, Mapping):
        _malformed("响应体不是 JSON 对象")
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        _malformed("choices 缺失或不是非空数组")
    first = choices[0]
    if not isinstance(first, Mapping):
        _malformed("choices[0] 不是对象")
    message = first.get("message")
    if not isinstance(message, Mapping):
        _malformed("choices[0].message 缺失或不是对象")
    content = message.get("content")
    if not isinstance(content, str):
        _malformed("choices[0].message.content 缺失或不是字符串")
    return content, _optional_confidence(payload.get("confidence"))


def _optional_confidence(value: Any) -> float | None:
    """通道级置信度：缺失 / `None` → `None`；非数值 → `malformed-response`。

    `bool` 显式排除：JSON 的 `true` 在 Python 里是 `int` 的子类，不排除就会变成 `1.0`
    这个通道从未给过的置信度。
    """
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _malformed("confidence 不是数值")
    return float(value)


def _malformed(detail: str) -> Never:
    """记下**字段级**线索（只有字段路径，MUST NOT 带响应内容或字段值）后抛 `malformed-response`。"""
    _logger.debug("[%s] 响应畸形：%s", NAME, detail)
    raise _http.malformed_response(NAME, OPERATION_COMPLETE)


def _require_compliance(operation: str) -> None:
    """合规门：未取得数据合规协议时**在构造请求之前**拒绝调用（`spec.md:86` / `:95-96`）。

    拒绝即抛 `ProviderChannelFailureError(reason="compliance-missing")`（`4003`：
    `errors.py` 把「通道未就绪（缺凭据或合规前置）」归在「等到了失败」这一档），
    并**先记一条 WARNING**——`spec.md:95-96` 要求的是「拒绝调用**并告警**」，
    只拒绝不告警等于静默失败。日志只带通道名与操作名，MUST NOT 带调用参数。
    """
    if COMPLIANCE_READY:
        return
    _logger.warning(
        "[合规门] 通道 %s 的 %s 被拒绝：数据合规协议未签署（COMPLIANCE_READY=False）；"
        "spec.md:86/95-96 要求未取得协议时拒绝调用该通道并告警",
        NAME,
        operation,
    )
    raise ProviderChannelFailureError(NAME, operation, reason="compliance-missing")
