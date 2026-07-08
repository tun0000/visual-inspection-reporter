"""Gemini adapter：google-genai SDK 的結構化輸出（response_schema=Pydantic）。

API 用法核對日期 2026-07-08（google-genai 2.10.0）：
https://ai.google.dev/gemini-api/docs/structured-output
金鑰由環境變數 GOOGLE_API_KEY 或 GEMINI_API_KEY 提供（genai.Client() 自動讀取，
兩者皆有時優先採用 GOOGLE_API_KEY，見 google/genai/_api_client.py）。
"""

from __future__ import annotations

import json

from google import genai
from google.genai import types

from inspector.providers.base import Usage, VLMProvider, VLMRequest, VLMResponseError
from inspector.schema import ImageAssessment


class GeminiProvider(VLMProvider):
    name = "gemini"

    def __init__(self, model_id: str):
        self.model_id = model_id
        self.client = genai.Client()

    def assess_image(self, request: VLMRequest) -> tuple[ImageAssessment, Usage]:
        parts: list[types.Part] = [
            types.Part.from_text(text=request.prompt),
            types.Part.from_text(text="【編號標註整圖】"),
            types.Part.from_bytes(data=request.annotated_jpeg, mime_type="image/jpeg"),
        ]
        for finding_id, crop_jpeg in request.crops:
            parts.append(types.Part.from_text(text=f"【瑕疵 #{finding_id} 局部放大圖】"))
            parts.append(types.Part.from_bytes(data=crop_jpeg, mime_type="image/jpeg"))
        parts.append(
            types.Part.from_text(
                text="【偵測 JSON】\n" + json.dumps(request.findings_json, ensure_ascii=False)
            )
        )

        response = self.client.models.generate_content(
            model=self.model_id,
            contents=parts,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=ImageAssessment,
                temperature=0.2,  # 巡檢輸出求穩定，不求發散
                seed=42,
            ),
        )

        assessment = response.parsed
        if not isinstance(assessment, ImageAssessment):
            raw = (response.text or "")[:500]
            raise VLMResponseError(f"Gemini 回覆無法解析為 ImageAssessment：{raw}")

        um = response.usage_metadata
        usage = Usage(
            model_id=self.model_id,
            input_tokens=um.prompt_token_count or 0,
            output_tokens=(um.candidates_token_count or 0) + (um.thoughts_token_count or 0),
        )
        return assessment, usage
