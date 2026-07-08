"""報告渲染與 VLM 評估流程（MockProvider，零網路）。"""

from __future__ import annotations

import json
from datetime import datetime

from PIL import Image

from inspector.cache import VLMCache
from inspector.cost import CostMeter
from inspector.domains import PCB_PROFILE
from inspector.findings import build_findings
from inspector.pipeline import BatchResult, ImageResult, _assess_one
from inspector.providers.base import Usage, VLMProvider, VLMRequest
from inspector.report import render_json, render_report
from inspector.retry import RateLimiter
from inspector.schema import (
    FindingAssessment,
    ImageAssessment,
    Severity,
    Verdict,
    reconcile,
)


def _fa(finding_id: int, severity: Severity = Severity.MINOR) -> FindingAssessment:
    return FindingAssessment(
        finding_id=finding_id, severity=severity, description_zh="描述文字", action_zh="處置建議"
    )


class MockProvider(VLMProvider):
    """依輸入 findings_json 回覆對齊 id 的固定評估。"""

    name = "mock"

    def __init__(self):
        self.model_id = "mock-model"
        self.calls = 0

    def assess_image(self, request: VLMRequest) -> tuple[ImageAssessment, Usage]:
        self.calls += 1
        ids = [item["id"] for item in request.findings_json]
        return (
            ImageAssessment(
                verdict=Verdict.REWORK, summary_zh="mock 總評", findings=[_fa(i) for i in ids]
            ),
            Usage(self.model_id, input_tokens=111, output_tokens=22),
        )


def _make_batch(tmp_path, image_findings) -> tuple[BatchResult, object]:
    output_dir = tmp_path / "out"
    (output_dir / "images").mkdir(parents=True)
    annotated = output_dir / "images" / "board_annotated.jpg"
    Image.new("RGB", (100, 80)).save(annotated, quality=85)

    # 一張已評估（VLM 漏評 id=3）、一張無瑕疵、一張評估失敗
    assessment = ImageAssessment(
        verdict=Verdict.FAIL,
        summary_zh="本板不合格。",
        findings=[_fa(1, Severity.CRITICAL), _fa(2)],
    )
    assessed = ImageResult(
        image_findings, annotated, assessed=reconcile(assessment, [1, 2, 3])
    )
    clean_path = tmp_path / "clean.jpg"
    Image.new("RGB", (100, 80)).save(clean_path, quality=85)
    clean = ImageResult(build_findings(clean_path, (100, 80), []), annotated)
    failed = ImageResult(image_findings, annotated, error="ServerError: 503")

    meter = CostMeter()
    meter.add(Usage("gemini-3.1-flash-lite", 5000, 300))
    meter.add_cache_hit()

    batch = BatchResult(
        results=[assessed, clean, failed],
        meter=meter,
        provider_name="gemini",
        model_id="gemini-3.1-flash-lite",
        conf=0.25,
        domain=PCB_PROFILE,
        started=datetime.now().astimezone(),
        elapsed_s=12.3,
    )
    return batch, output_dir


def test_render_report_covers_all_cases(tmp_path, image_findings):
    batch, output_dir = _make_batch(tmp_path, image_findings)
    report_path = render_report(batch, output_dir)
    md = report_path.read_text(encoding="utf-8")

    assert "判定：不合格" in md
    assert "合格（未檢出瑕疵）" in md
    assert "評估失敗" in md and "ServerError: 503" in md
    assert "VLM 未評估此項" in md and "漏評" in md  # missing id=3 標記 + warning
    assert "快取命中：1 張" in md
    assert "gemini-3.1-flash-lite | 1 | 5,000 | 300" in md
    assert "images/board_annotated.jpg" in md  # 相對路徑附圖


def test_render_json_structure(tmp_path, image_findings):
    batch, output_dir = _make_batch(tmp_path, image_findings)
    payload = json.loads(render_json(batch, output_dir).read_text(encoding="utf-8"))

    assert payload["meta"]["model"] == "gemini-3.1-flash-lite"
    assert payload["cost"]["cache_hits"] == 1 and payload["cost"]["total_usd"] > 0
    assert len(payload["images"]) == 3

    first = payload["images"][0]
    assert first["verdict"] == "fail"
    by_id = {f["id"]: f for f in first["findings"]}
    assert by_id[1]["assessed"] and by_id[1]["severity"] == "critical"
    assert not by_id[3]["assessed"] and by_id[3]["severity"] is None  # 漏評不捏造

    assert payload["images"][1]["verdict"] is None  # 無瑕疵未呼叫 VLM
    assert payload["images"][2]["error"] == "ServerError: 503"


def test_assess_one_uses_cache_on_second_call(tmp_path, image_findings):
    annotated = tmp_path / "ann.jpg"
    Image.new("RGB", (100, 80)).save(annotated, quality=85)
    result = ImageResult(image_findings, annotated)
    provider = MockProvider()
    cache = VLMCache(cache_dir=tmp_path / "cache", enabled=True)
    limiter = RateLimiter(0)

    rec, usage, hit = _assess_one(result, PCB_PROFILE, provider, cache, limiter)
    assert not hit and provider.calls == 1
    assert rec.missing_ids == [] and rec.dropped_ids == []

    rec2, usage2, hit2 = _assess_one(result, PCB_PROFILE, provider, cache, limiter)
    assert hit2 and provider.calls == 1  # 第二次走快取，不再打 API
    assert usage2 == usage
