"""外部模型通道 Protocol（Task 4.1）。

`service` 层 MUST 只依赖本文件的 Protocol，MUST NOT 导入任何具体实现
（mock / deepseek / cloud_vision / cloud_ocr）——由 `.importlinter` 契约
`service-provider-impl` 强制，放行表达式仅 `aicore.service.** -> aicore.provider.base`。

## 相对 Task 1.2 空壳的三处**收紧**（都是「统一入参与返回结构」的落地）

1. 返回类型从 `dict[str, Any]` 改为 `ProviderResult`。dict 让「含置信度与血缘字段」
   只存在于 docstring 里，mypy 一个字都管不到；改成 dataclass 后
   `result.identity.channel` 是静态可核的。
2. 三个通道**都**声明 `prompt_version`。原空壳只有 TEXT / OCR 有，但 `er.md` §6.1 的
   `model_meta` 是**统一血缘结构**（`{channel, provider, modelVersion, promptVersion,
   thresholds}`），三通道落库都写这一份 JSON。**若某个通道不声明它**，血缘里就只能留空，
   会让「按版本维度统计结果质量」（spec.md:128）在该链路上无基准。
   （原文此处写作「VISION 没有 prompt 版本而血缘里留空」，措辞容易被读成
   「VISION 迄今仍没有」与现状矛盾；P 阶段独立评审按 N9 指出，已改为直陈后果。）
   三个通道取值都用带通道前缀的显式字面量而非空串——**空串不是「不适用」**，
   它会让「没配」与「配了但为空」重新混在一起（同 `core/config.py` 对只读地址的取向）。
3. 调用入参统一带 `timeout_s`：Task 4.6 要求处理器「声明自身超时」，超时必须能从
   调用侧传入而不是藏在实现里写死，否则任务级超时配置无处生效。

## 为什么用 `Protocol` 而不是抽象基类

design.md:54 逐字：「三个 Protocol（**结构子类型，不强制继承**）」。结构子类型让
真实通道可以包住任意第三方 SDK 客户端（不要求那个客户端继承我的基类），
也让测试替身不必进生产类的继承树。代价是 `isinstance` 只在运行期逐成员检查
（`@runtime_checkable` 的能力边界，见下方 `runtime_checkable` 的说明）。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol, runtime_checkable

from aicore.provider.results import ProviderResult

__all__ = ["OcrProvider", "TextProvider", "VisionProvider"]


@runtime_checkable
class TextProvider(Protocol):
    """文本模型通道（DeepSeek 等）。

    Task 4.1 的「统一入参」在本通道即 `prompt` + `payload`：
    `prompt` 是**模板标识或模板文本**，`payload` 是模板变量。两者分开是为了让
    prompt 版本可迭代（`prompt_version`）而调用方不必知道模板内容。
    """

    #: 通道实现名（`mock` / `deepseek` / …）。落 `model_meta.provider`。
    name: str

    #: 模型版本。落 `model_meta.modelVersion`。
    model_version: str

    #: Prompt 模板版本。落 `model_meta.promptVersion`。
    prompt_version: str

    async def complete(
        self,
        *,
        prompt: str,
        payload: Mapping[str, Any],
        timeout_s: float,
    ) -> ProviderResult:
        """文本补全。失败 MUST 抛 `provider/errors.py` 的异常，MUST NOT 返回空结果。"""
        ...

    def model_meta(self) -> dict[str, Any]:
        """渲染 `er.md` §6.1 的 `ai_task.model_meta`（键名 camelCase）。

        放在 Protocol 上而不是让调用方自己拼：血缘结构是**跨文档契约**，
        三个通道各拼一次迟早分叉。实现应直接委托
        `ProviderIdentity.as_model_meta()`。
        """
        ...


@runtime_checkable
class VisionProvider(Protocol):
    """视觉模型通道（云视觉 API 等）。"""

    name: str
    model_version: str
    prompt_version: str

    async def analyze(
        self,
        *,
        image_key: str,
        labels: list[str],
        timeout_s: float,
    ) -> ProviderResult:
        """按 `labels` 检测图像标记。

        `image_key` 是**对象存储键**而非图像字节：spec.md:90-91 要求「日志与审计中
        不留存脱敏前的原始图像」，传键让通道实现自取，图像字节不经过本层签名。
        **MUST 只接收已完成脱敏的对象**——该前置由 `service/desensitize.py` 承担，
        本层不校验（校验放这里等于给「跳过脱敏」留了一个可以通过的入口）。
        """
        ...

    def model_meta(self) -> dict[str, Any]:
        """同上。"""
        ...


@runtime_checkable
class OcrProvider(Protocol):
    """证照 OCR 通道（云 OCR / 轻量 OCR）。"""

    name: str
    model_version: str
    prompt_version: str

    async def recognize(
        self,
        *,
        image_key: str,
        doc_type: str,
        timeout_s: float,
    ) -> ProviderResult:
        """识别证照，返回 `ProviderResult.fields`（`tuple[OcrField, ...]`）。

        值 MUST 已脱敏（`er.md` §6.2 `fields_json`：「value(脱敏)」）；
        字段名用 openapi.yaml `OcrField` 的约定（`fieldName` / `value` / `confidence`）。
        """
        ...

    def model_meta(self) -> dict[str, Any]:
        """同上。"""
        ...
