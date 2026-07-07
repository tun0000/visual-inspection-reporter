"""批次巡檢流程：讀圖 → 偵測 → findings 組裝與落地 →（M3 起）VLM 評估 → 報告。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from inspector.config import DEFAULT_CONF, DEFAULT_WEIGHTS, MAX_CROPS_PER_IMAGE
from inspector.detector import Detector
from inspector.findings import (
    ImageFindings,
    annotate,
    build_findings,
    crop_finding,
    findings_to_json,
)

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp"}


@dataclass
class ImageResult:
    findings: ImageFindings
    annotated_path: Path
    crop_paths: dict[int, Path] = field(default_factory=dict)  # finding_id -> 裁切圖路徑
    assessment: object | None = None  # M3: schema.ImageAssessment
    error: str | None = None


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
