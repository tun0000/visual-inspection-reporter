"""每張影像的 findings 組裝：編號、標註整圖、context 裁切、給 VLM 的偵測 JSON。

編號（#1..N，依信心降冪）同時出現在標註圖與 JSON 中，讓 VLM 的回覆
能被 schema 強制對齊到具體 finding，防止張冠李戴。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from inspector.config import (
    ANNOTATED_MAX_SIDE,
    CLASS_NAMES_ZH,
    CROP_EXPAND,
    CROP_MIN_SIDE,
)
from inspector.detector import Detection

# 每類固定一色（RGB），挑在深綠色 PCB 基板上對比明顯的顏色
CLASS_COLORS = {
    "missing_hole": (255, 64, 64),
    "mouse_bite": (255, 160, 0),
    "open_circuit": (255, 255, 80),
    "short": (255, 0, 255),
    "spur": (0, 224, 255),
    "spurious_copper": (255, 255, 255),
}


@dataclass(frozen=True)
class Finding:
    finding_id: int  # 1-based，畫在標註圖上、也出現在偵測 JSON
    detection: Detection


@dataclass
class ImageFindings:
    image_path: Path
    image_size: tuple[int, int]  # (w, h)
    findings: list[Finding]


def build_findings(image_path: Path, image_size: tuple[int, int], detections: list[Detection]) -> ImageFindings:
    """依信心降冪排序並編號（#1 = 最高信心）。"""
    ordered = sorted(detections, key=lambda d: d.conf, reverse=True)
    findings = [Finding(i + 1, det) for i, det in enumerate(ordered)]
    return ImageFindings(image_path, image_size, findings)


def annotate(image: Image.Image, findings: list[Finding], max_side: int = ANNOTATED_MAX_SIDE) -> Image.Image:
    """在整圖上畫編號框（#id class），再把最長邊縮到 max_side。

    先在原解析度作畫再縮圖，框線與文字大小依影像尺寸調整。
    cv2.putText 不支援中文，圖上標籤用英文類名；中文對照在報告表格呈現。
    """
    canvas = np.asarray(image.convert("RGB")).copy()
    h, w = canvas.shape[:2]
    thickness = max(2, round(min(w, h) / 350))
    font_scale = min(max(min(w, h) / 1000.0, 0.7), 1.6)
    font = cv2.FONT_HERSHEY_SIMPLEX

    for f in findings:
        x1, y1, x2, y2 = (round(v) for v in f.detection.xyxy)
        color = CLASS_COLORS[f.detection.class_name]
        cv2.rectangle(canvas, (x1, y1), (x2, y2), color, thickness)

        label = f"#{f.finding_id} {f.detection.class_name}"
        (tw, th), baseline = cv2.getTextSize(label, font, font_scale, thickness)
        # 標籤背景放在框上方；貼近上緣時放到框內側，避免被裁掉
        ty = y1 - baseline - 4
        if ty - th < 0:
            ty = y1 + th + baseline + 4
        cv2.rectangle(canvas, (x1, ty - th - baseline), (x1 + tw + 4, ty + baseline), color, -1)
        cv2.putText(canvas, label, (x1 + 2, ty), font, font_scale, (0, 0, 0), thickness, cv2.LINE_AA)

    if max(w, h) > max_side:
        gain = max_side / max(w, h)
        canvas = cv2.resize(canvas, (round(w * gain), round(h * gain)), interpolation=cv2.INTER_AREA)
    return Image.fromarray(canvas)


def crop_finding(
    image: Image.Image,
    finding: Finding,
    expand: float = CROP_EXPAND,
    min_side: int = CROP_MIN_SIDE,
) -> Image.Image:
    """以 bbox 為中心外擴 expand 倍（至少 min_side px）從原圖裁切，保留周邊 context。"""
    x1, y1, x2, y2 = finding.detection.xyxy
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    half_w = max((x2 - x1) * expand, min_side) / 2
    half_h = max((y2 - y1) * expand, min_side) / 2

    w, h = image.size
    left = max(0, round(cx - half_w))
    top = max(0, round(cy - half_h))
    right = min(w, round(cx + half_w))
    bottom = min(h, round(cy + half_h))
    return image.crop((left, top, right, bottom))


def findings_to_json(fi: ImageFindings) -> list[dict]:
    """給 VLM 的偵測 JSON：id、類別（英/中）、信心、歸一化 bbox。"""
    w, h = fi.image_size
    return [
        {
            "id": f.finding_id,
            "class": f.detection.class_name,
            "class_zh": CLASS_NAMES_ZH[f.detection.class_name],
            "confidence": round(f.detection.conf, 3),
            "bbox_norm": [
                round(f.detection.xyxy[0] / w, 4),
                round(f.detection.xyxy[1] / h, 4),
                round(f.detection.xyxy[2] / w, 4),
                round(f.detection.xyxy[3] / h, 4),
            ],
        }
        for f in fi.findings
    ]
