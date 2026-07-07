"""批次巡檢流程：讀圖 → 偵測 → findings 組裝與落地 → VLM 評估（併發 + 快取）→ 彙整。"""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from PIL import Image

from inspector.cache import VLMCache, cache_key
from inspector.config import (
    DEFAULT_CONF,
    DEFAULT_MODELS,
    DEFAULT_PROVIDER,
    DEFAULT_WEIGHTS,
    DEFAULT_WORKERS,
    MAX_CROPS_PER_IMAGE,
    MAX_RPM,
    VLM_ON_CLEAN,
)
from inspector.cost import CostMeter
from inspector.detector import Detector
from inspector.findings import (
    ImageFindings,
    annotate,
    build_findings,
    crop_finding,
    findings_to_json,
)
from inspector.providers.base import Usage, VLMProvider, VLMRequest, create_provider
from inspector.retry import RateLimiter, vlm_retry
from inspector.schema import ReconciledAssessment, reconcile

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp"}


@dataclass
class ImageResult:
    findings: ImageFindings
    annotated_path: Path
    crop_paths: dict[int, Path] = field(default_factory=dict)  # finding_id -> 裁切圖路徑
    assessed: ReconciledAssessment | None = None  # 無瑕疵跳過 VLM 時為 None
    cache_hit: bool = False
    error: str | None = None  # VLM 評估失敗時的錯誤訊息（單圖失敗不炸整批）


@dataclass
class BatchResult:
    results: list[ImageResult]
    meter: CostMeter
    provider_name: str
    model_id: str
    conf: float
    started: datetime
    elapsed_s: float
    detect_only: bool = False


def list_images(input_dir: Path) -> list[Path]:
    images = sorted(p for p in input_dir.iterdir() if p.suffix.lower() in IMAGE_EXTS)
    if not images:
        raise SystemExit(f"在 {input_dir} 找不到影像（支援 {'/'.join(sorted(IMAGE_EXTS))}）")
    return images


def run_detection(
    input_dir: Path,
    output_dir: Path,
    conf: float = DEFAULT_CONF,
    weights: Path = DEFAULT_WEIGHTS,
) -> list[ImageResult]:
    """偵測階段：對資料夾內每張影像產出 findings、編號標註圖與裁切圖。

    標註圖與裁切圖存進 output_dir/images、output_dir/crops，
    原始偵測結果彙整成 output_dir/detections.json 供除錯與測試。
    """
    images_dir = output_dir / "images"
    crops_dir = output_dir / "crops"
    images_dir.mkdir(parents=True, exist_ok=True)
    crops_dir.mkdir(parents=True, exist_ok=True)

    detector = Detector(weights)
    results: list[ImageResult] = []

    for image_path in list_images(input_dir):
        image = Image.open(image_path)
        detections = detector.predict(image, conf)
        fi = build_findings(image_path, image.size, detections)

        annotated_path = images_dir / f"{image_path.stem}_annotated.jpg"
        annotate(image, fi.findings).save(annotated_path, quality=90)

        result = ImageResult(fi, annotated_path)
        # 裁切只做會送給 VLM 的前 N 個（依信心排序，編號即順位）
        for f in fi.findings[:MAX_CROPS_PER_IMAGE]:
            crop_path = crops_dir / f"{image_path.stem}_f{f.finding_id:02d}_{f.detection.class_name}.jpg"
            crop_finding(image, f).save(crop_path, quality=90)
            result.crop_paths[f.finding_id] = crop_path
        results.append(result)

    detections_dump = [
        {
            "image": str(r.findings.image_path),
            "size": list(r.findings.image_size),
            "findings": findings_to_json(r.findings),
        }
        for r in results
    ]
    (output_dir / "detections.json").write_text(
        json.dumps(detections_dump, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return results


def _assess_one(
    result: ImageResult, provider: VLMProvider, cache: VLMCache, limiter: RateLimiter
) -> tuple[ReconciledAssessment, Usage, bool]:
    """單張影像的 VLM 評估（先查快取）。回傳 (對齊後評估, 用量, 是否快取命中)。"""
    image_bytes = result.findings.image_path.read_bytes()
    fj = findings_to_json(result.findings)
    key = cache_key(image_bytes, fj, provider.model_id)
    valid_ids = [f.finding_id for f in result.findings.findings]

    cached = cache.get(key)
    if cached is not None:
        assessment, usage = cached
        return reconcile(assessment, valid_ids), usage, True

    request = VLMRequest(
        annotated_jpeg=result.annotated_path.read_bytes(),
        crops=[(fid, path.read_bytes()) for fid, path in sorted(result.crop_paths.items())],
        findings_json=fj,
    )
    limiter.acquire()  # 只對真正打 API 的呼叫限速；快取命中不佔額度
    assessment, usage = vlm_retry(provider.assess_image)(request)
    cache.put(key, assessment, usage)
    return reconcile(assessment, valid_ids), usage, False


def run_batch(
    input_dir: Path,
    output_dir: Path,
    *,
    provider_name: str = DEFAULT_PROVIDER,
    model_id: str | None = None,
    conf: float = DEFAULT_CONF,
    weights: Path = DEFAULT_WEIGHTS,
    workers: int = DEFAULT_WORKERS,
    max_rpm: int = MAX_RPM,
    use_cache: bool = True,
    detect_only: bool = False,
    vlm_on_clean: bool = VLM_ON_CLEAN,
) -> BatchResult:
    """整條 pipeline。VLM 階段以 ThreadPoolExecutor 併發，單圖失敗記入該圖不中斷整批。"""
    started = datetime.now().astimezone()
    t0 = time.perf_counter()
    meter = CostMeter()

    results = run_detection(input_dir, output_dir, conf, weights)
    model_id = model_id or DEFAULT_MODELS[provider_name]

    if not detect_only:
        provider = create_provider(provider_name, model_id)
        cache = VLMCache(enabled=use_cache)
        limiter = RateLimiter(max_rpm)
        # 無瑕疵影像預設跳過 VLM（成本槓桿）；報告直接標「合格（未檢出瑕疵）」
        todo = [r for r in results if r.findings.findings or vlm_on_clean]

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_assess_one, r, provider, cache, limiter): r for r in todo}
            for future in as_completed(futures):
                r = futures[future]
                try:
                    r.assessed, usage, r.cache_hit = future.result()
                except Exception as exc:  # noqa: BLE001 — 單圖失敗記錄後繼續
                    r.error = f"{type(exc).__name__}: {exc}"
                    continue
                if r.cache_hit:
                    meter.add_cache_hit()
                else:
                    meter.add(usage)

    return BatchResult(
        results=results,
        meter=meter,
        provider_name=provider_name,
        model_id=model_id,
        conf=conf,
        started=started,
        elapsed_s=time.perf_counter() - t0,
        detect_only=detect_only,
    )
