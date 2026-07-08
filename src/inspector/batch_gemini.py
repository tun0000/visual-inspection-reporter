"""Gemini Batch API 模式：整批影像評估一次送出，input/output 皆 5 折，
但非同步（提交 → 輪詢 → 取回），沒有即時逐張回應。僅 Gemini 供應商支援
（--batch-api，見 README「Gemini Batch API」一節）。

API 用法核對日期 2026-07-09（google-genai，實際安裝套件原始碼確認，非憑文件摘要猜測）：
https://ai.google.dev/gemini-api/docs/batch-api
- client.batches.create(model=..., src=list[types.InlinedRequest]) -> BatchJob
- InlinedRequest(contents=..., config=GenerateContentConfig(...), metadata=...)：
  contents/config 跟同步 generate_content 完全同構，圖片一樣用
  types.Part.from_bytes 內嵌（不需要先上傳檔案）。
- 輪詢 client.batches.get(name=job.name)，比對 job.state 是否為終態
  （JOB_STATE_SUCCEEDED / FAILED / CANCELLED / EXPIRED / PARTIALLY_SUCCEEDED）。
- 結果在 job.dest.inlined_responses（list[InlinedResponse]）。**不假設順序與送出
  時一致**——用 InlinedRequest.metadata / InlinedResponse.metadata 的自訂 key 對應
  回原始請求，這是 InlinedRequest/InlinedResponse 都有 metadata 欄位的用意。
"""

from __future__ import annotations

import json
import time

from google import genai
from google.genai import types

from inspector.providers.base import Usage, VLMRequest, VLMResponseError
from inspector.schema import ImageAssessment

_TERMINAL_STATES = {
    types.JobState.JOB_STATE_SUCCEEDED,
    types.JobState.JOB_STATE_FAILED,
    types.JobState.JOB_STATE_CANCELLED,
    types.JobState.JOB_STATE_EXPIRED,
    types.JobState.JOB_STATE_PARTIALLY_SUCCEEDED,
}

_KEY = "vir_request_key"  # InlinedRequest/Response metadata 裡用來對應原始請求的鍵


def _build_inline_request(key: str, req: VLMRequest) -> types.InlinedRequest:
    parts: list[types.Part] = [
        types.Part.from_text(text=req.prompt),
        types.Part.from_text(text="【編號標註整圖】"),
        types.Part.from_bytes(data=req.annotated_jpeg, mime_type="image/jpeg"),
    ]
    for finding_id, crop_jpeg in req.crops:
        parts.append(types.Part.from_text(text=f"【瑕疵 #{finding_id} 局部放大圖】"))
        parts.append(types.Part.from_bytes(data=crop_jpeg, mime_type="image/jpeg"))
    parts.append(
        types.Part.from_text(
            text="【偵測 JSON】\n" + json.dumps(req.findings_json, ensure_ascii=False)
        )
    )
    return types.InlinedRequest(
        contents=parts,
        metadata={_KEY: key},
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=ImageAssessment,
            temperature=0.2,
            seed=42,
        ),
    )


def run_batch_assess(
    keyed_requests: dict[str, VLMRequest],
    model_id: str,
    poll_interval_s: float = 15.0,
    timeout_s: float = 1800.0,
    on_poll: callable = None,
) -> dict[str, tuple[ImageAssessment, Usage] | Exception]:
    """送出一個 Gemini batch job 評估多張影像，輪詢直到完成。

    keyed_requests：{任意唯一 key（呼叫端自訂，通常用影像檔名）: VLMRequest}。
    回傳同樣以 key 對應的結果 dict——每個 key 對到 (評估, 用量) 或一個 Exception
    （單張失敗不影響其他張的結果）。
    """
    client = genai.Client()
    inline_requests = [_build_inline_request(key, req) for key, req in keyed_requests.items()]

    job = client.batches.create(model=model_id, src=inline_requests)
    deadline = time.monotonic() + timeout_s
    while job.state not in _TERMINAL_STATES:
        if time.monotonic() > deadline:
            raise TimeoutError(
                f"Gemini batch job {job.name} 逾時（{timeout_s:.0f}s）尚未完成，"
                f"目前狀態 {job.state.name}；可稍後用 client.batches.get(name='{job.name}') 手動查詢"
            )
        if on_poll:
            on_poll(job.state.name)
        time.sleep(poll_interval_s)
        job = client.batches.get(name=job.name)

    if job.state == types.JobState.JOB_STATE_FAILED:
        raise VLMResponseError(f"Gemini batch job 失敗：{job.error}")

    results: dict[str, tuple[ImageAssessment, Usage] | Exception] = {}
    inlined = job.dest.inlined_responses if job.dest else []
    for item in inlined:
        key = (item.metadata or {}).get(_KEY)
        if key is None:
            continue  # 理論上不會發生：每筆送出時都帶了 key
        if item.error:
            results[key] = VLMResponseError(f"Gemini batch 項目失敗：{item.error}")
            continue
        resp = item.response
        assessment = resp.parsed if resp else None
        if not isinstance(assessment, ImageAssessment):
            results[key] = VLMResponseError("Gemini batch 回覆無法解析為 ImageAssessment")
            continue
        um = resp.usage_metadata
        results[key] = (
            assessment,
            Usage(
                model_id=model_id,
                input_tokens=(um.prompt_token_count or 0) if um else 0,
                output_tokens=((um.candidates_token_count or 0) + (um.thoughts_token_count or 0)) if um else 0,
            ),
        )

    # 沒在回應裡出現的 key（理論上不該發生，但防禦性處理避免靜默漏評）
    for key in keyed_requests:
        if key not in results:
            results[key] = VLMResponseError("Gemini batch 回應中缺少這筆結果")
    return results
