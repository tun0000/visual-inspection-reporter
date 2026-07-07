"""Torch-free ONNX Runtime 推論（YOLO26 end-to-end 免 NMS 匯出版）。

移植自上游 pcb-defect-detection 專案（AGPL-3.0）的 src/pcb_defect/e2e_onnx.py，
該處已用 scripts/verify_onnx_parity.py 驗證過與 ultralytics .pt 推論的一致性
（測試集 mAP50 差 < 3%）。

ONNX 輸出為單一 (1, 300, 6) tensor：[x1, y1, x2, y2, confidence, class_id]，
座標在 letterbox 後的 640x640 輸入像素空間，不需 NMS——後處理只有
信心閾值過濾 + 反 letterbox 座標還原。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from inspector.config import CLASS_NAMES, DEFAULT_CONF

IMG_SIZE = 640
PAD_VALUE = 114


@dataclass(frozen=True)
class Detection:
    class_id: int
    class_name: str
    xyxy: tuple[float, float, float, float]  # 原圖像素座標
    conf: float


@dataclass(frozen=True)
class LetterboxInfo:
    gain: float
    pad_left: float
    pad_top: float


def letterbox(image: Image.Image, size: int = IMG_SIZE) -> tuple[np.ndarray, LetterboxInfo]:
    """等比縮放 + 置中補灰邊，與 ultralytics LetterBox 完全一致。

    必須用 cv2.resize（INTER_LINEAR）而非 PIL resize：上游實測兩者在高倍率
    縮小密集細節（IC 腳、細走線）時數值差異足以讓模型在 conf=0.25 掉 2 個真實偵測。
    """
    rgb = np.asarray(image.convert("RGB"))
    h, w = rgb.shape[:2]
    gain = min(size / w, size / h)
    new_w, new_h = round(w * gain), round(h * gain)
    resized = cv2.resize(rgb, (new_w, new_h), interpolation=cv2.INTER_LINEAR)

    dw, dh = (size - new_w) / 2, (size - new_h) / 2
    top, bottom = round(dh - 0.1), round(dh + 0.1)
    left, right = round(dw - 0.1), round(dw + 0.1)
    canvas = cv2.copyMakeBorder(
        resized, top, bottom, left, right, cv2.BORDER_CONSTANT, value=(PAD_VALUE,) * 3
    )
    return canvas, LetterboxInfo(gain, left, top)


def preprocess(image: Image.Image) -> tuple[np.ndarray, LetterboxInfo]:
    """RGB HWC uint8 -> normalized NCHW float32 batch，並回傳反變換所需的 letterbox 資訊。"""
    canvas, info = letterbox(image)
    chw = canvas.transpose(2, 0, 1).astype(np.float32) / 255.0
    batch = np.ascontiguousarray(np.expand_dims(chw, axis=0))
    return batch, info


def postprocess(
    output: np.ndarray,
    info: LetterboxInfo,
    orig_size: tuple[int, int],
    conf: float = DEFAULT_CONF,
) -> list[Detection]:
    """(1, 300, 6) letterbox 空間 rows -> 原圖像素座標的 Detection list。

    信心過濾同時丟掉 e2e head 的零信心填充列（max_det=300 固定輸出）。
    """
    rows = output[0]
    rows = rows[rows[:, 4] >= conf]

    orig_w, orig_h = orig_size
    detections = []
    for x1, y1, x2, y2, score, cls in rows:
        # 全部轉成 Python 原生型別：numpy float32 無法直接 json 序列化
        ox1 = float(max(0.0, min((x1 - info.pad_left) / info.gain, orig_w)))
        oy1 = float(max(0.0, min((y1 - info.pad_top) / info.gain, orig_h)))
        ox2 = float(max(0.0, min((x2 - info.pad_left) / info.gain, orig_w)))
        oy2 = float(max(0.0, min((y2 - info.pad_top) / info.gain, orig_h)))
        class_id = int(cls)
        detections.append(
            Detection(class_id, CLASS_NAMES[class_id], (ox1, oy1, ox2, oy2), float(score))
        )
    return detections


class Detector:
    """獨立的 ONNX Runtime session——不依賴 torch / ultralytics。"""

    def __init__(self, onnx_path: str | Path, providers: list[str] | None = None):
        import onnxruntime as ort

        self.session = ort.InferenceSession(
            str(onnx_path), providers=providers or ["CPUExecutionProvider"]
        )
        self.input_name = self.session.get_inputs()[0].name

    def predict(self, image: Image.Image, conf: float = DEFAULT_CONF) -> list[Detection]:
        batch, info = preprocess(image)
        (output,) = self.session.run(None, {self.input_name: batch})
        return postprocess(output, info, image.size, conf)
