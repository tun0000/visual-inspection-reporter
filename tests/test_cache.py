"""內容雜湊快取：鍵的敏感性、roundtrip、壞檔自癒。"""

from inspector.cache import VLMCache, cache_key
from inspector.providers.base import Usage
from inspector.schema import FindingAssessment, ImageAssessment, Severity, Verdict

FINDINGS_JSON = [{"id": 1, "class": "short", "confidence": 0.9, "bbox_norm": [0.1, 0.2, 0.3, 0.4]}]


def _assessment() -> ImageAssessment:
    return ImageAssessment(
        verdict=Verdict.FAIL,
        summary_zh="總評",
        findings=[
            FindingAssessment(
                finding_id=1, severity=Severity.CRITICAL, description_zh="描述", action_zh="處置"
            )
        ],
    )


def test_cache_key_sensitivity():
    base = cache_key(b"image", FINDINGS_JSON, "model-a")
    assert cache_key(b"image", FINDINGS_JSON, "model-a") == base  # 決定性
    assert cache_key(b"other", FINDINGS_JSON, "model-a") != base  # 圖變 → 鍵變
    assert cache_key(b"image", [], "model-a") != base  # 偵測變 → 鍵變
    assert cache_key(b"image", FINDINGS_JSON, "model-b") != base  # 模型變 → 鍵變


def test_cache_roundtrip(tmp_path):
    cache = VLMCache(cache_dir=tmp_path, enabled=True)
    usage = Usage(model_id="m", input_tokens=100, output_tokens=10)
    cache.put("k1", _assessment(), usage)

    hit = cache.get("k1")
    assert hit is not None
    assessment, cached_usage = hit
    assert assessment == _assessment()
    assert cached_usage == usage
    assert cache.get("nope") is None


def test_cache_disabled(tmp_path):
    cache = VLMCache(cache_dir=tmp_path, enabled=False)
    cache.put("k1", _assessment(), Usage("m", 1, 1))
    assert cache.get("k1") is None
    assert list(tmp_path.iterdir()) == []


def test_cache_corrupted_file_recovers(tmp_path):
    cache = VLMCache(cache_dir=tmp_path, enabled=True)
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert cache.get("bad") is None
    assert not bad.exists()  # 壞檔被清掉，之後重打 API
