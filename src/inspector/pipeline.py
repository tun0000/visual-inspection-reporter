"""批次巡檢流程：讀圖 → 偵測 → findings 組裝與落地 → VLM 評估（併發 + 快取，或 Gemini
Batch API 模式）→ 彙整。domain（見 domains.py）決定要用哪組權重/類別/prompt。
"""

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
    DEFAULT_MODELS,
    DEFAULT_PROVIDER,
    DEFAULT_WORKERS,
    MAX_CROPS_PER_IMAGE,
    MAX_RPM,
    VLM_ON_CLEAN,
)
from inspector.cost import CostMeter
from inspector.detector import Detector
from inspector.domains import DomainProfile, PCB_PROFILE
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
    domain: DomainProfile
    started: datetime
    elapsed_s: float
    detect_only: bool = False
    used_batch_api: bool = False


def list_images(input_dir: Path) -> list[Path]:
    images = sorted(p for p in input_dir.iterdir() if p.suffix.lower() in IMAGE_EXTS)
    if not images:
        raise SystemExit(f"在 {input_dir} 找不到影像（支援 {'/'.join(sorted(IMAGE_EXTS))}）")
    return images


def run_detection(
    input_dir: Path,
    output_dir: Path,
    domain: DomainProfile = PCB_PROFILE,
    conf: float | None = None,
    weights: Path | None = None,
) -> list[ImageResult]:
    """偵測階段：對資料夾內每張影像產出 findings、編號標註圖與裁切圖。

    標註圖與裁切圖存進 output_dir/images、output_dir/crops，
    原始偵測結果彙整成 output_dir/detections.json 供除錯與測試。
    """
    conf = domain.conf if conf is None else conf
    weights = domain.weights if weights is None else weights

    images_dir = output_dir / "images"
    crops_dir = output_dir / "crops"
    images_dir.mkdir(parents=True, exist_ok=True)
    crops_dir.mkdir(parents=True, exist_ok=True)

    detector = Detector(weights, domain.class_names)
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
            "findings": findings_to_json(r.findings, domain.class_names_zh),
        }
        for r in results
    ]
    (output_dir / "detections.json").write_text(
        json.dumps(detections_dump, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return results


def _build_request(
    result: ImageResult, domain: DomainProfile, model_id: str
) -> tuple[str, VLMRequest]:
    """組出這張影像的快取鍵（含 model_id 才唯一）與 VLMRequest（同步/批次路徑共用）。

    快取鍵吃原始來源影像 bytes（不是標註圖）：跟上游偵測/標註邏輯的實作細節脫鉤，
    只要「同一張來源圖 + 同一份偵測結果 + 同一個模型」就命中。
    """
    fj = findings_to_json(result.findings, domain.class_names_zh)
    source_bytes = result.findings.image_path.read_bytes()
    key = cache_key(source_bytes, fj, model_id)
    request = VLMRequest(
        prompt=domain.prompt,
        annotated_jpeg=result.annotated_path.read_bytes(),
        crops=[(fid, path.read_bytes()) for fid, path in sorted(result.crop_paths.items())],
        findings_json=fj,
    )
    return key, request


def _assess_one(
    result: ImageResult,
    domain: DomainProfile,
    provider: VLMProvider,
    cache: VLMCache,
    limiter: RateLimiter,
) -> tuple[ReconciledAssessment, Usage, bool]:
    """單張影像的 VLM 評估（先查快取）。回傳 (對齊後評估, 用量, 是否快取命中)。"""
    key, request = _build_request(result, domain, provider.model_id)
    valid_ids = [f.finding_id for f in result.findings.findings]

    cached = cache.get(key)
    if cached is not None:
        assessment, usage = cached
        return reconcile(assessment, valid_ids), usage, True

    limiter.acquire()  # 只對真正打 API 的呼叫限速；快取命中不佔額度
    assessment, usage = vlm_retry(provider.assess_image)(request)
    cache.put(key, assessment, usage)
    return reconcile(assessment, valid_ids), usage, False


def _run_sync(
    todo: list[ImageResult],
    domain: DomainProfile,
    provider: VLMProvider,
    cache: VLMCache,
    limiter: RateLimiter,
    workers: int,
    meter: CostMeter,
) -> None:
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_assess_one, r, domain, provider, cache, limiter): r for r in todo}
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


def _run_via_batch_api(
    todo: list[ImageResult],
    domain: DomainProfile,
    model_id: str,
    cache: VLMCache,
    meter: CostMeter,
) -> None:
    """Gemini Batch API 路徑：快取先擋一輪，剩下的一次送成一個 batch job（5 折，非即時）。"""
    from inspector.batch_gemini import run_batch_assess

    keyed_requests = {}
    key_by_image = {}
    for r in todo:
        key, request = _build_request(r, domain, model_id)
        cached = cache.get(key)
        if cached is not None:
            assessment, usage = cached
            valid_ids = [f.finding_id for f in r.findings.findings]
            r.assessed, r.cache_hit = reconcile(assessment, valid_ids), True
            meter.add_cache_hit()
            continue
        keyed_requests[key] = request
        key_by_image[key] = r

    if not keyed_requests:
        return  # 全部快取命中，連 batch job 都不用送

    print(f"提交 Gemini batch job：{len(keyed_requests)} 張影像，輪詢中（可能要幾分鐘）…")
    results = run_batch_assess(keyed_requests, model_id, on_poll=lambda s: print(f"  batch 狀態：{s}"))

    for key, r in key_by_image.items():
        outcome = results[key]
        valid_ids = [f.finding_id for f in r.findings.findings]
        if isinstance(outcome, Exception):
            r.error = f"{type(outcome).__name__}: {outcome}"
            continue
        assessment, usage = outcome
        r.assessed, r.cache_hit = reconcile(assessment, valid_ids), False
        cache.put(key, assessment, usage)
        meter.add(usage, batch=True)


def run_batch(
    input_dir: Path,
    output_dir: Path,
    *,
    domain: DomainProfile = PCB_PROFILE,
    provider_name: str = DEFAULT_PROVIDER,
    model_id: str | None = None,
    conf: float | None = None,
    weights: Path | None = None,
    workers: int = DEFAULT_WORKERS,
    max_rpm: int = MAX_RPM,
    use_cache: bool = True,
    detect_only: bool = False,
    vlm_on_clean: bool = VLM_ON_CLEAN,
    use_batch_api: bool = False,
) -> BatchResult:
    """整條 pipeline。VLM 階段預設 ThreadPoolExecutor 併發同步呼叫；
    use_batch_api=True 時（僅 gemini）改走 Gemini Batch API（5 折但非即時）。
    單圖失敗記入該圖不中斷整批。
    """
    if use_batch_api and provider_name != "gemini":
        raise ValueError("--batch-api 目前只支援 gemini 供應商")

    started = datetime.now().astimezone()
    t0 = time.perf_counter()
    meter = CostMeter()
    conf = domain.conf if conf is None else conf

    results = run_detection(input_dir, output_dir, domain, conf, weights)
    model_id = model_id or DEFAULT_MODELS[provider_name]

    if not detect_only:
        cache = VLMCache(enabled=use_cache)
        # 無瑕疵影像預設跳過 VLM（成本槓桿）；報告直接標「合格（未檢出瑕疵）」
        todo = [r for r in results if r.findings.findings or vlm_on_clean]

        if use_batch_api:
            _run_via_batch_api(todo, domain, model_id, cache, meter)
        else:
            provider = create_provider(provider_name, model_id)
            limiter = RateLimiter(max_rpm)
            _run_sync(todo, domain, provider, cache, limiter, workers, meter)

    return BatchResult(
        results=results,
        meter=meter,
        provider_name=provider_name,
        model_id=model_id,
        conf=conf,
        domain=domain,
        started=started,
        elapsed_s=time.perf_counter() - t0,
        detect_only=detect_only,
        used_batch_api=use_batch_api,
    )
