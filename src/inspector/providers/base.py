"""VLM 供應商抽象層：統一的請求/回應介面 + factory。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from inspector.config import DEFAULT_MODELS
from inspector.schema import ImageAssessment


@dataclass(frozen=True)
class Usage:
    """單次 VLM 呼叫的實際 token 用量（來自 API 回傳，非估算）。"""

    model_id: str
    input_tokens: int
    output_tokens: int  # 含思考 tokens（若供應商有回報）


@dataclass
class VLMRequest:
    """一張影像的評估請求：編號標註整圖 + 局部裁切 + 偵測 JSON。"""

    annotated_jpeg: bytes
    crops: list[tuple[int, bytes]] = field(default_factory=list)  # (finding_id, jpeg bytes)
    findings_json: list[dict] = field(default_factory=list)


class VLMResponseError(RuntimeError):
    """VLM 回覆無法解析成 schema（結構化輸出失敗）。"""


class VLMProvider(ABC):
    name: str
    model_id: str

    @abstractmethod
    def assess_image(self, request: VLMRequest) -> tuple[ImageAssessment, Usage]:
        """評估一張影像；回傳結構化評估與實際 token 用量。"""


def create_provider(name: str, model_id: str | None = None) -> VLMProvider:
    if name == "gemini":
        from inspector.providers.gemini import GeminiProvider

        return GeminiProvider(model_id or DEFAULT_MODELS["gemini"])
    if name == "openai":
        from inspector.providers.openai_provider import OpenAIProvider

        return OpenAIProvider(model_id or DEFAULT_MODELS["openai"])
    raise ValueError(f"未知的供應商：{name}（可用：{sorted(DEFAULT_MODELS)}）")
