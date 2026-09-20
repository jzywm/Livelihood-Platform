"""云视觉通道（Task 4.3 骨架）。

`VisionProvider` 的真实实现骨架：请求构造 + 响应解析 + 超时 / 重试 / 熔断 / 合规门。
**外部模型 HTTP 调用只发生在 `provider/` 包内**（tasks.md 4.3 的结构性要求），
且包内唯一的 httpx 构造点是 `provider/_http.py`。

## 本通道在 M1 **不可用于真实调用**（合规门默认关闭）

`COMPLIANCE_READY = False`，依据 `docs/design/产品设计文档.md:1832` 逐字
「✅ 已评审（签数据合规协议（不用于训练）+ 图像脱敏前置；…）；**已完成（协议:M2 前签署）**」
——M1 阶段协议尚未签署。`spec.md:86` 逐字：「送往云视觉 API 的图像 MUST 处于已签署的
数据合规协议之下……合规协议状态 MUST 可被核对，**未取得协议时系统 MUST NOT 调用该通道**」，
`spec.md:95-96` 要求「拒绝调用该通道并告警，不以外发图像的方式继续处理」。

**故本文件存在的意义是「契约与护栏可测」，不是「可用」**：

- 请求构造、响应解析、三类失败归一、护栏与合规门**都可被用例以假密钥 + `httpx.MockTransport`
  完整验证**（不发出任何真实调用）；
- 合规门打开的条件是「协议已签署 + 密钥字段已落地」，两件事都不在 Task 4.3 的范围里；
- 在合规门打开之前，任何对该通道的调用都会得到 `4003 compliance-missing` + 一条 WARNING，
  **不存在「异常后继续执行」的降级分支**（`design.md:171` 禁止项 6 的同向取向）。

## 两个尚未落地的注入点（都在本文件内，各只有一处）

- `DEFAULT_CLOUD_VISION_BASE_URL`：现状是 RFC 2606 的 `.invalid` 保留域（**不可能解析**）。
  候选厂商未定（`产品设计文档.md:1832`「通义VL/GLM-4V 先小样测评；备选 DeepSeek-VL
  私有化」），选定后改这一处。保持 `.invalid` 的意义是**纵深防御**：即使合规门被误开，
  也发不到真实厂商。
- `API_KEY`：现状是空串。`core/config.py` 的 `_REAL_PROVIDERS_WITHOUT_KEY_FIELD` 明确标注
  云通道「尚未声明密钥字段」，凭空加字段等于假造接口契约（且要连带改 `.env.example`
  与字段表用例）。真实接入时密钥由 KMS / 环境变量注入，并按该映射上方的三处同步登记，
  启动校验的规则 2 才会开始核验它。

## 其他已知边界（同 `deepseek.py`，逐条列在 Task 4.3 报告里）

- `ProviderResult.raw` 不回填：可能含未脱敏的字段值（`results.py` 对它的硬约束）。
- `thresholds` 取空 dict：阈值所有者是 Task 4.10，`Settings` 里尚无对应字段。
- 一次调用一个 httpx 客户端（无连接复用），理由见 `_http.py`。
- `labels` / `image_key` 只做「是不是调用方传错了」的轻校验；**图像是否已脱敏由
  `service/desensitize.py` 承担**，本层不校验（`base.py` 对 VISION 的逐字口径：
  「校验放这里等于给『跳过脱敏』留了一个可以通过的入口」）。
"""

from __future__ import annotations

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
    "COMPLIANCE_READY",
    "DEFAULT_CLOUD_VISION_BASE_URL",
    "VISION_MARKERS_PATH",
    "CloudVisionProvider",
]

_logger = logging.getLogger(__name__)

#: 通道实现名。逐字对齐 `core/config.py` 的 `provider` 字面量与 `.env.example` 的注释。
NAME = "cloud_vision"

#: 通道**类别**（`er.md` §6.1 的 `model_meta.channel`）。注解用 `results.py` 的 `Channel`，
#: 写错类别在 `mypy --strict` 就报错（理由见 `deepseek.py` 的同名常量）。
CHANNEL: Channel = "VISION"

#: 操作名（进 `ProviderError.operation`）。
OPERATION_ANALYZE = "analyze"

#: 合规状态：**关闭**（依据见模块 docstring）。真实接入前 MUST NOT 改成 `True`——
#: 改它等于对外声明「协议已签署」，那是 M2 的里程碑，不是代码里的一个布尔值。
COMPLIANCE_READY: bool = False

#: 默认 base URL：RFC 2606 的 `.invalid` 保留域（**不可能解析**，见模块 docstring）。
DEFAULT_CLOUD_VISION_BASE_URL = "https://cloud-vision.vendor.invalid"

#: 视觉标记检测路径。骨架占位：真实厂商的路径选定后改这一处（厂商未定，见模块 docstring）。
VISION_MARKERS_PATH = "/vision/markers"

#: 模型版本。**带通道前缀**（工单 §3.1）。
MODEL_VERSION = "cloud_vision-vl-v1"

#: Prompt 版本：视觉通道**没有** prompt 版本，故取「不适用」的显式字面量。
#:
#: `base.py` 逐字要求：「取值用『不适用』的显式字面量而非空串」——空串在血缘里
#: 无法区分「没有 prompt」与「写漏了 prompt」，而 `er.md` §6.1 的 `model_meta` 是三通道
#: 统一写的一份 JSON，留空会让「按版本维度统计结果质量」（spec.md:128）在视觉链路上无基准。
PROMPT_VERSION = "cloud_vision-not-applicable"

#: 密钥注入点（现状为空串，见模块 docstring 的注入点表）。
API_KEY: str = ""


class CloudVisionProvider:
    """云视觉通道（`VisionProvider` 的结构子类型实现）。

    **M1 不可用于真实调用**（`COMPLIANCE_READY = False`，协议 M2 前签署）：
    本类的存在意义是让视觉通道的契约、护栏与合规门**可测**，而不是让视觉链路可用。
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
        """`config` 提供四项护栏参数；`breaker` / `clock` 可注入（用例注入假时钟）。"""
        self._config = config
        self._guard_config: GuardConfig = guard_config_from(config)
        self._breaker: CircuitBreaker = (
            CircuitBreaker(self._guard_config, clock=clock) if breaker is None else breaker
        )
        self._clock = clock
        self._call_count = 0

    @property
    def call_count(self) -> int:
        """通道方法被调用的次数（口径见 `deepseek.py` 的同名属性）。"""
        return self._call_count

    async def analyze(
        self,
        *,
        image_key: str,
        labels: list[str],
        timeout_s: float,
    ) -> ProviderResult:
        """按 `labels` 检测图像标记：`POST /vision/markers`，体含 `image_key` / `labels`。

        返回 `ProviderResult.markers`：每项**至少**含 `label` / `level` / `confidence`
        三个键（`openapi.yaml` 的 `VisionMarker`；缺失的 `confidence` 补 `None` 而不是 `0`，
        理由同 `deepseek.py`）。
        """
        self._call_count += 1
        _require_compliance(OPERATION_ANALYZE)
        _validate_analyze_args(image_key, labels)
        effective_timeout = self._effective_timeout_s(
            _http.require_positive_timeout(
                timeout_s,
                provider=NAME,
                operation=OPERATION_ANALYZE,
            )
        )
        body: dict[str, Any] = {"image_key": image_key, "labels": list(labels)}
        result: ProviderResult = await guarded_call(
            provider=NAME,
            operation=OPERATION_ANALYZE,
            config=self._guard_config,
            breaker=self._breaker,
            send=lambda: self._exchange(body, timeout_s=effective_timeout),
            clock=self._clock,
        )
        return result

    def model_meta(self) -> dict[str, Any]:
        """渲染 `ai_task.model_meta`（`er.md` §6.1）：**委托** `as_model_meta()`。

        MUST NOT 手拼 dict：键名是跨文档契约（camelCase），三通道各拼一次迟早分叉。
        """
        return self._identity().as_model_meta()

    def _identity(self) -> ProviderIdentity:
        """本次调用的血缘（`channel` 是类别、`provider` 是实现名）。"""
        return ProviderIdentity(
            channel=CHANNEL,
            provider=NAME,
            model_version=MODEL_VERSION,
            prompt_version=PROMPT_VERSION,
        )

    def _effective_timeout_s(self, declared_s: float) -> float:
        """调用侧声明的超时与 `ai_call_timeout_s` 取较小值（理由见 `deepseek.py`）。"""
        return min(declared_s, self._config.ai_call_timeout_s)

    async def _exchange(self, body: Mapping[str, Any], *, timeout_s: float) -> ProviderResult:
        """一次 HTTP 交换 + 解析（作为 `guarded_call` 的 `send`）。"""
        client = _http.build_client(
            base_url=DEFAULT_CLOUD_VISION_BASE_URL,
            api_key=API_KEY,
            timeout_s=timeout_s,
        )
        async with client:
            response = await client.post(VISION_MARKERS_PATH, json=dict(body))
            response.raise_for_status()
            decoded = _http.decode_json(response, provider=NAME, operation=OPERATION_ANALYZE)
        markers, confidence = _parse_markers(decoded)
        return ProviderResult(
            identity=self._identity(),
            markers=markers,
            confidence=confidence,
        )


def _validate_analyze_args(image_key: str, labels: list[str]) -> None:
    """轻校验调用方入参，**抛 `ValueError`（编程错误）而不是通道失败**。

    `image_key` 为空 / `labels` 为空或含非字符串，都是调用点拼错了参数：放行只会让
    「本地参数 bug」在通道侧表现为一次无意义的计费调用或 4xx，运维照着通道方向排查
    （与 `guard.py` 分类表最后一行同向）。**不校验**的是「图像是否已脱敏」——那由
    `service/desensitize.py` 承担（见模块 docstring）。
    """
    if not isinstance(image_key, str) or not image_key.strip():
        raise ValueError(f"{NAME}.{OPERATION_ANALYZE} 的 image_key 必须是非空对象存储键")
    if not labels:
        raise ValueError(
            f"{NAME}.{OPERATION_ANALYZE} 的 labels 不能为空：空 labels 的检测请求没有意义"
        )
    if not all(isinstance(label, str) and label.strip() for label in labels):
        raise ValueError(f"{NAME}.{OPERATION_ANALYZE} 的 labels 必须是非空字符串列表")


def _parse_markers(payload: Any) -> tuple[tuple[Mapping[str, Any], ...], float | None]:
    """解析 `markers` → `(markers, confidence)`；畸形一律 `malformed-response`。

    每一项都**归一化**成「三个键都在」的映射（`label` / `level` / `confidence`）：
    通道省略 `confidence` 时补 `None`（MUST NOT 补 0），额外键原样保留——下游
    （Task 4.10 置信度分级、`service/verdict.py`）因此可以直接索引 `marker["confidence"]`，
    不必各自处理 `KeyError`。
    """
    if not isinstance(payload, Mapping):
        _malformed("响应体不是 JSON 对象")
    raw_markers = payload.get("markers")
    if not isinstance(raw_markers, list):
        _malformed("markers 缺失或不是数组")
    markers: list[Mapping[str, Any]] = []
    for index, item in enumerate(raw_markers):
        if not isinstance(item, Mapping):
            _malformed(f"markers[{index}] 不是对象")
        marker: dict[str, Any] = {str(key): value for key, value in item.items()}
        label = marker.get("label")
        level = marker.get("level")
        if not isinstance(label, str) or not label:
            _malformed(f"markers[{index}].label 缺失或不是非空字符串")
        if not isinstance(level, str) or not level:
            _malformed(f"markers[{index}].level 缺失或不是非空字符串")
        marker["label"] = label
        marker["level"] = level
        marker["confidence"] = _optional_confidence(marker.get("confidence"), index=index)
        markers.append(marker)
    return tuple(markers), _optional_confidence(payload.get("confidence"), index=None)


def _optional_confidence(value: Any, *, index: int | None) -> float | None:
    """置信度：缺失 / `None` → `None`；非数值 → `malformed-response`（`bool` 显式排除）。"""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        where = "confidence" if index is None else f"markers[{index}].confidence"
        _malformed(f"{where} 不是数值")
    return float(value)


def _malformed(detail: str) -> Never:
    """记下**字段级**线索（只有字段路径，MUST NOT 带响应内容或字段值）后抛 `malformed-response`。"""
    _logger.debug("[%s] 响应畸形：%s", NAME, detail)
    raise _http.malformed_response(NAME, OPERATION_ANALYZE)


def _require_compliance(operation: str) -> None:
    """合规门：未取得数据合规协议时**在构造请求之前**拒绝调用（`spec.md:86` / `:95-96`）。

    拒绝即抛 `4003 compliance-missing` 并先记 WARNING——`spec.md:95-96` 要求的是
    「拒绝调用**并告警**」。日志只带通道名与操作名，MUST NOT 带 `image_key`
    （对象键虽不是图像本身，但没有进日志的必要）。
    """
    if COMPLIANCE_READY:
        return
    _logger.warning(
        "[合规门] 通道 %s 的 %s 被拒绝：数据合规协议未签署（COMPLIANCE_READY=False，"
        "产品设计文档.md:1832「协议:M2 前签署」）；spec.md:95-96 要求拒绝调用该通道并告警，"
        "不以外发图像的方式继续处理",
        NAME,
        operation,
    )
    raise ProviderChannelFailureError(NAME, operation, reason="compliance-missing")
