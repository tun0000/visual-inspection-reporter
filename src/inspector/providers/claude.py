"""Claude (Anthropic) adapter：Messages API 的結構化輸出（output_format=Pydantic）。

API 用法核對日期 2026-07-09（anthropic 0.116.0，實際安裝版本原始碼確認）：
https://platform.claude.com/docs/en/build-with-claude/structured-outputs
- client.messages.parse(..., output_format=PydanticModel) -> ParsedMessage
- 解析結果在 response.parsed_output（property，找不到會回傳 None）
- 用量在 response.usage.input_tokens / output_tokens
金鑰由環境變數 ANTHROPIC_API_KEY 提供（Anthropic() 自動讀取）。
"""

from __future__ import annotations

import base64
import json

from anthropic import Anthropic

from inspector.providers.base import Usage, VLMProvider, VLMRequest, VLMResponseError
from inspector.schema import ImageAssessment


def _image_block(jpeg: bytes) -> dict:
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/jpeg",
            "data": base64.b64encode(jpeg).decode("ascii"),
        },
    }


class ClaudeProvider(VLMProvider):
    name = "claude"

    def __init__(self, model_id: str):
        self.model_id = model_id
        self.client = Anthropic()

    def assess_image(self, request: VLMRequest) -> tuple[ImageAssessment, Usage]:
        content: list[dict] = [
            {"type": "text", "text": "【編號標註整圖】"},
            _image_block(request.annotated_jpeg),
        ]
        for finding_id, crop_jpeg in request.crops:
            content.append({"type": "text", "text": f"【瑕疵 #{finding_id} 局部放大圖】"})
            content.append(_image_block(crop_jpeg))
        content.append(
            {
                "type": "text",
                "text": "【偵測 JSON】\n" + json.dumps(request.findings_json, ensure_ascii=False),
            }
        )

        response = self.client.messages.parse(
            model=self.model_id,
            max_tokens=2048,
            system=request.prompt,
            messages=[{"role": "user", "content": content}],
            output_format=ImageAssessment,
        )

        assessment = response.parsed_output
        if not isinstance(assessment, ImageAssessment):
            raw = "".join(b.text for b in response.content if b.type == "text")[:500]
            raise VLMResponseError(f"Claude 回覆無法解析為 ImageAssessment：{raw}")

        usage = Usage(
            model_id=self.model_id,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )
        return assessment, usage
