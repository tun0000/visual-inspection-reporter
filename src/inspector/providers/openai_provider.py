"""OpenAI adapter：Responses API 的結構化輸出（text_format=Pydantic）。

API 用法核對日期 2026-07-08（openai 2.44.0）：
https://developers.openai.com/api/docs/guides/structured-outputs
金鑰由環境變數 OPENAI_API_KEY 提供（OpenAI() 自動讀取）。
"""

from __future__ import annotations

import base64
import json

from openai import OpenAI

from inspector.providers.base import Usage, VLMProvider, VLMRequest, VLMResponseError
from inspector.schema import ImageAssessment


def _image_block(jpeg: bytes) -> dict:
    b64 = base64.b64encode(jpeg).decode("ascii")
    return {"type": "input_image", "image_url": f"data:image/jpeg;base64,{b64}"}


class OpenAIProvider(VLMProvider):
    name = "openai"

    def __init__(self, model_id: str):
        self.model_id = model_id
        self.client = OpenAI()

    def assess_image(self, request: VLMRequest) -> tuple[ImageAssessment, Usage]:
        content: list[dict] = [
            {"type": "input_text", "text": request.prompt},
            {"type": "input_text", "text": "【編號標註整圖】"},
            _image_block(request.annotated_jpeg),
        ]
        for finding_id, crop_jpeg in request.crops:
            content.append({"type": "input_text", "text": f"【瑕疵 #{finding_id} 局部放大圖】"})
            content.append(_image_block(crop_jpeg))
        content.append(
            {
                "type": "input_text",
                "text": "【偵測 JSON】\n" + json.dumps(request.findings_json, ensure_ascii=False),
            }
        )

        response = self.client.responses.parse(
            model=self.model_id,
            input=[{"role": "user", "content": content}],
            text_format=ImageAssessment,
        )

        assessment = response.output_parsed
        if not isinstance(assessment, ImageAssessment):
            raise VLMResponseError(f"OpenAI 回覆無法解析為 ImageAssessment：{response.output_text[:500]}")

        usage = Usage(
            model_id=self.model_id,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,  # Responses API 的 output 已含 reasoning tokens
        )
        return assessment, usage
