"""外部模型通道 Protocol。

service 层 MUST 只依赖本文件的 Protocol，MUST NOT 导入任何具体实现
（mock / deepseek / cloud_vision / cloud_ocr）——由 .importlinter 的 import-linter 契约强制。
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class TextProvider(Protocol):
    """文本模型通道。"""

    name: str
    model_version: str

    async def complete(self, *, prompt: str, payload: dict[str, Any]) -> dict[str, Any]:
        """返回 {text, confidence, modelVersion, promptVersion}。"""
        ...


@runtime_checkable
class VisionProvider(Protocol):
    """视觉模型通道。"""

    name: str
    model_version: str

    async def analyze(self, *, image_key: str, labels: list[str]) -> dict[str, Any]:
        """返回 {markers, confidence, modelVersion}。"""
        ...


@runtime_checkable
class OcrProvider(Protocol):
    """证照 OCR 通道。"""

    name: str
    model_version: str

    async def recognize(self, *, image_key: str, doc_type: str) -> dict[str, Any]:
        """返回 {fields, confidence, modelVersion, promptVersion}。"""
        ...
