"""云 OCR 通道（Task 4.3 骨架）。

`OcrProvider` 的真实实现骨架：请求构造 + 响应解析 + 值脱敏 + 超时 / 重试 / 熔断 / 合规门。
**外部模型 HTTP 调用只发生在 `provider/` 包内**（tasks.md 4.3 的结构性要求），
且包内唯一的 httpx 构造点是 `provider/_http.py`。

## 本通道在 M1 **不可用于真实调用**（合规门默认关闭）

`COMPLIANCE_READY = False`，依据 `docs/design/产品设计文档.md:1832`
「云视觉 API 合规（K）… ✅ 已评审（签数据合规协议（不用于训练）+ 图像脱敏前置…）；
**已完成（协议:M2 前签署）**」——M1 阶段协议尚未签署；`spec.md:86`「未取得协议时
系统 MUST NOT 调用该通道」、`spec.md:95-96`「拒绝调用该通道并告警，不以外发图像的方式
继续处理」。OCR 与云视觉共用同一份图像外发合规口径（`产品设计文档.md:1623` 的 §7.9
把两者写在同一条 AC-C8 下）。

**故本文件存在的意义是「契约与护栏可测」，不是「可用」**：请求构造、响应解析、脱敏、
三类失败归一、护栏与合规门都能以假密钥 + `httpx.MockTransport` 完整验证，
且**不发出任何真实计费调用**。合规门打开需要「协议已签署 + 密钥字段已落地」两件事，
都不在 Task 4.3 的范围里。不存在「异常后继续执行」的降级分支（`design.md:171` 禁止项 6 同向）。

## 解析出的字段值 MUST 就地脱敏（本文件的第二条硬要求）

- `er.md` §6.2：`ocr_result.fields_json` 的 `OcrField` 三项是
  `{fieldName, value(**脱敏**), confidence}`；
- `spec.md:100`：「系统 MUST NOT 以任何形式向外部模型供应商上传用户数据以改进其模型」，
  `spec.md:243-246`：日志与审计中 MUST NOT 出现未脱敏的证件字段值；
- `er.md` §6.3 的示例给出了本平台脱敏后的形状：`911301**********1234`（首 6 位 + 打星 + 末 4 位）。

故 `recognize()` 在**放进 `OcrField.value` 之前**调用 `mask_long_digit_runs()`：
连续 15 位以上的数字串一律中间打星。**这是「落地即脱敏」而不是「调用方自己记得脱敏」**——
后者只要有一个调用点忘了，未脱敏的证件号就进了库与日志。

## 两个尚未落地的注入点（同 `cloud_vision.py`）

- `DEFAULT_CLOUD_OCR_BASE_URL`：现状是 RFC 2606 的 `.invalid` 保留域（**不可能解析**）。
  厂商未定（同云视觉，`产品设计文档.md:1832`），选定后改这一处；保持 `.invalid` 是纵深防御。
- `API_KEY`：现状是空串。`core/config.py` 的 `_REAL_PROVIDERS_WITHOUT_KEY_FIELD` 标注
  云通道「尚未声明密钥字段」；真实接入时经 KMS / 环境变量注入，并按该映射上方的
  三处同步登记后，启动校验的规则 2 才会开始核验它。

## 其他已知边界（逐条列在 Task 4.3 报告里）

- `ProviderResult.raw` **一定**不回填：原始响应里就是未脱敏的证件值，落库即违规
  （`results.py` 对该字段的硬约束「MUST NOT 含未脱敏的证件值」）。
- `thresholds` 取空 dict：阈值所有者是 Task 4.10。
- 一次调用一个 httpx 客户端（无连接复用），理由见 `_http.py`。
- 脱敏只覆盖「连续 15 位以上数字」这一种最强形态（身份证 / 银行卡 / 统一社会信用代码
  的纯数字部分）。姓名、地址之类的非数字 PII 不在本函数覆盖范围内——那属于
  `service/desensitize.py` 的实体识别职责，本层只做**最后一道**防「PII 落库」的兜底。
"""

from __future__ import annotations

import logging
import re
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
from aicore.provider.results import Channel, OcrField, ProviderIdentity, ProviderResult

__all__ = [
    "COMPLIANCE_READY",
    "DEFAULT_CLOUD_OCR_BASE_URL",
    "OCR_RECOGNIZE_PATH",
    "CloudOcrProvider",
    "mask_long_digit_runs",
]

_logger = logging.getLogger(__name__)

#: 通道实现名。逐字对齐 `core/config.py` 的 `provider` 字面量与 `.env.example` 的注释。
NAME = "cloud_ocr"

#: 通道**类别**（`er.md` §6.1 的 `model_meta.channel`）。注解用 `results.py` 的 `Channel`，
#: 写错类别在 `mypy --strict` 就报错（理由见 `deepseek.py` 的同名常量）。
CHANNEL: Channel = "OCR"

#: 操作名（进 `ProviderError.operation`）。
OPERATION_RECOGNIZE = "recognize"

#: 合规状态：**关闭**（依据见模块 docstring）。真实接入前 MUST NOT 改成 `True`。
COMPLIANCE_READY: bool = False

#: 默认 base URL：RFC 2606 的 `.invalid` 保留域（**不可能解析**，见模块 docstring）。
DEFAULT_CLOUD_OCR_BASE_URL = "https://cloud-ocr.vendor.invalid"

#: 证照识别路径。骨架占位：真实厂商的路径选定后改这一处。
OCR_RECOGNIZE_PATH = "/ocr/recognize"

#: 模型版本。**带通道前缀**（工单 §3.1）。
MODEL_VERSION = "cloud_ocr-generic-v1"

#: Prompt 版本。OCR 的字段抽取依赖 prompt 模板，故这里是真实版本号而非「不适用」。
PROMPT_VERSION = "cloud_ocr-fields-prompt-v1"

#: 密钥注入点（现状为空串，见模块 docstring 的注入点表）。
API_KEY: str = ""

#: 需要脱敏的连续数字位数下限。
#:
#: 取 15 的依据：平台涉及的证件号都在这条线以上——身份证 18 位、银行卡 16~19 位、
#: 统一社会信用代码 18 位（纯数字段）；而正常业务数字（金额、有效期的年月日、
#: 类目代码、置信度百分数）都远在 15 位以下。取小会把正常值打成星号（信息损失），
#: 取大会漏掉真实的证件号（合规风险），15 是两者的分界。
_MASK_MIN_DIGITS = 15

#: 连续数字串（`\d{15,}`）。
_LONG_DIGIT_RUN = re.compile(rf"\d{{{_MASK_MIN_DIGITS},}}")

#: 脱敏时保留的首部位数：统一社会信用代码前 6 位是行政区划、身份证前 6 位是地址码，
#: 保留它们才能让「这号码看上去属于哪个地区」可核对（`er.md` §6.3 的示例同样是首 6 位）。
_MASK_KEEP_HEAD = 6

#: 保留的尾部位数（4 位足够人工肉眼比对，且不足以致命——见 `er.md` §6.3 的同形示例）。
_MASK_KEEP_TAIL = 4


class CloudOcrProvider:
    """云 OCR 通道（`OcrProvider` 的结构子类型实现）。

    **M1 不可用于真实调用**（`COMPLIANCE_READY = False`，协议 M2 前签署）。
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

    async def recognize(
        self,
        *,
        image_key: str,
        doc_type: str,
        timeout_s: float,
    ) -> ProviderResult:
        """识别证照：`POST /ocr/recognize`，体含 `image_key` / `doc_type`。

        返回 `ProviderResult.fields`（`tuple[OcrField, ...]`），其中 `value` **已脱敏**
        （`er.md` §6.2 的逐字要求：「value(脱敏)」）。
        """
        self._call_count += 1
        _require_compliance(OPERATION_RECOGNIZE)
        _validate_recognize_args(image_key, doc_type)
        effective_timeout = self._effective_timeout_s(
            _http.require_positive_timeout(
                timeout_s,
                provider=NAME,
                operation=OPERATION_RECOGNIZE,
            )
        )
        body: dict[str, Any] = {"image_key": image_key, "doc_type": doc_type}
        result: ProviderResult = await guarded_call(
            provider=NAME,
            operation=OPERATION_RECOGNIZE,
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
            base_url=DEFAULT_CLOUD_OCR_BASE_URL,
            api_key=API_KEY,
            timeout_s=timeout_s,
        )
        async with client:
            response = await client.post(OCR_RECOGNIZE_PATH, json=dict(body))
            response.raise_for_status()
            decoded = _http.decode_json(
                response, provider=NAME, operation=OPERATION_RECOGNIZE
            )
        fields, confidence = _parse_fields(decoded)
        return ProviderResult(
            identity=self._identity(),
            fields=fields,
            confidence=confidence,
        )


def mask_long_digit_runs(value: str) -> str:
    """把 `value` 里所有长度 >= 15 的连续数字串做「中间打星」脱敏并返回。

    保留首 6 位与末 4 位（依据见 `_MASK_KEEP_HEAD` / `_MASK_KEEP_TAIL`），中间等长替换成 `*`：
    `110101199003071234` -> `110101**********1234`（长度不变，便于人工核对与字段长度断言）。

    用 `re.sub` 扫描而不是 `value.isdigit()` 判断整串：真实证件字段常带前后缀
    （「统一社会信用代码：9113…」「有效期至 2027-12-31」），只判整串会漏掉**混在文本里**
    的证件号——那正是最容易漏的一种形态。
    """
    return _LONG_DIGIT_RUN.sub(_mask_match, value)


def _mask_match(match: re.Match[str]) -> str:
    """单个匹配的脱敏结果：首 6 + 星号 + 末 4。"""
    digits = match.group(0)
    head = digits[:_MASK_KEEP_HEAD]
    tail = digits[-_MASK_KEEP_TAIL:]
    stars = "*" * (len(digits) - _MASK_KEEP_HEAD - _MASK_KEEP_TAIL)
    return f"{head}{stars}{tail}"


def _validate_recognize_args(image_key: str, doc_type: str) -> None:
    """轻校验调用方入参，**抛 `ValueError`（编程错误）而不是通道失败**。

    `image_key` / `doc_type` 为空都是调用点拼错了参数：放行只会让本地 bug 在通道侧
    表现为一次无意义的计费调用或 4xx（与 `guard.py` 分类表最后一行同向）。
    **不校验**「图像是否已脱敏」——那由 `service/desensitize.py` 承担（见模块 docstring）。
    """
    if not isinstance(image_key, str) or not image_key.strip():
        raise ValueError(f"{NAME}.{OPERATION_RECOGNIZE} 的 image_key 必须是非空对象存储键")
    if not isinstance(doc_type, str) or not doc_type.strip():
        raise ValueError(f"{NAME}.{OPERATION_RECOGNIZE} 的 doc_type 必须是非空字符串")


def _parse_fields(payload: Any) -> tuple[tuple[OcrField, ...], float | None]:
    """解析 `fields` → `(fields, confidence)`；畸形一律 `malformed-response`。

    每个字段三项（`fieldName` / `value` / `confidence`，键名逐字取自 `openapi.yaml` 的
    `OcrField`）：`fieldName` 与 `value` 必填，`confidence` 缺失补 `None`（MUST NOT 补 0）。
    `value` **在放进结构之前**过 `mask_long_digit_runs()`。
    """
    if not isinstance(payload, Mapping):
        _malformed("响应体不是 JSON 对象")
    raw_fields = payload.get("fields")
    if not isinstance(raw_fields, list):
        _malformed("fields 缺失或不是数组")
    fields: list[OcrField] = []
    for index, item in enumerate(raw_fields):
        if not isinstance(item, Mapping):
            _malformed(f"fields[{index}] 不是对象")
        field_name = item.get("fieldName")
        value = item.get("value")
        if not isinstance(field_name, str) or not field_name:
            _malformed(f"fields[{index}].fieldName 缺失或不是非空字符串")
        if not isinstance(value, str):
            _malformed(f"fields[{index}].value 缺失或不是字符串")
        fields.append(
            OcrField(
                fieldName=field_name,
                value=mask_long_digit_runs(value),
                confidence=_optional_confidence(item.get("confidence"), index=index),
            )
        )
    return tuple(fields), _optional_confidence(payload.get("confidence"), index=None)


def _optional_confidence(value: Any, *, index: int | None) -> float | None:
    """置信度：缺失 / `None` → `None`；非数值 → `malformed-response`（`bool` 显式排除）。"""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        where = "confidence" if index is None else f"fields[{index}].confidence"
        _malformed(f"{where} 不是数值")
    return float(value)


def _malformed(detail: str) -> Never:
    """记下**字段级**线索后抛 `malformed-response`。

    只记字段路径（`fields[0].value`）而**不记字段值**：`spec.md:243-246` 要求
    「日志中不出现未脱敏的证件字段值」，而畸形响应里的值恰恰是**没脱敏**的那一份。
    """
    _logger.debug("[%s] 响应畸形：%s", NAME, detail)
    raise _http.malformed_response(NAME, OPERATION_RECOGNIZE)


def _require_compliance(operation: str) -> None:
    """合规门：未取得数据合规协议时**在构造请求之前**拒绝调用（`spec.md:86` / `:95-96`）。

    拒绝即抛 `4003 compliance-missing` 并先记 WARNING——`spec.md:95-96` 要求
    「拒绝调用**并告警**」。日志只带通道名与操作名，MUST NOT 带 `image_key`。
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
