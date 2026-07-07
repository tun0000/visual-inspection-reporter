"""集中設定：模型註冊表與定價、偵測參數、VLM 輸入組裝參數、pipeline 行為。

價格與型號皆為手動維護的常數；換模型或隔一段時間後，記得回官方定價頁核對。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# ---------------------------------------------------------------------------
# VLM 模型註冊表與定價
#
# 單價為官方「付費層」定價（USD / 1M tokens），查證日期 2026-07-08：
#   - https://ai.google.dev/gemini-api/docs/pricing
#   - https://developers.openai.com/api/docs/pricing
# 本專案開發期走 Gemini 免費層（實際帳單 $0），報告中的成本一律標示為
# 「以付費層定價換算的估算值」。
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ModelPricing:
    input_usd_per_m: float  # USD / 1M input tokens
    output_usd_per_m: float  # USD / 1M output tokens


MODEL_PRICING: dict[str, ModelPricing] = {
    # Google Gemini（GA）
    "gemini-3.1-flash-lite": ModelPricing(0.25, 1.50),  # 預設：最新 flash-lite 級
    "gemini-2.5-flash-lite": ModelPricing(0.10, 0.40),  # 省錢備選（上一代）
    "gemini-3.5-flash": ModelPricing(1.50, 9.00),  # 品質升級備選
    # OpenAI（GA）
    "gpt-5.4-nano": ModelPricing(0.20, 1.25),  # openai provider 預設
    "gpt-5.4-mini": ModelPricing(0.75, 4.50),  # openai 品質備選
}

DEFAULT_PROVIDER = "gemini"
DEFAULT_MODELS = {
    "gemini": "gemini-3.1-flash-lite",
    "openai": "gpt-5.4-nano",
}

# USD → TWD 匯率常數，僅用於報告中的新台幣估算；手動維護。
# TODO(M2): 實作成本統計前查一次當日匯率並更新此值與日期註記。
USD_TO_TWD = 30.0

# ---------------------------------------------------------------------------
# 偵測（YOLO26n ONNX，end-to-end 免 NMS）
# ---------------------------------------------------------------------------

CLASS_NAMES = [
    "missing_hole",
    "mouse_bite",
    "open_circuit",
    "short",
    "spur",
    "spurious_copper",
]

CLASS_NAMES_ZH = {
    "missing_hole": "缺孔",
    "mouse_bite": "鼠咬",
    "open_circuit": "斷路",
    "short": "短路",
    "spur": "毛刺",
    "spurious_copper": "殘銅",
}

DEFAULT_WEIGHTS = REPO_ROOT / "weights" / "best.onnx"
DEFAULT_CONF = 0.25

# ---------------------------------------------------------------------------
# VLM 輸入組裝
# ---------------------------------------------------------------------------

ANNOTATED_MAX_SIDE = 1280  # 給 VLM 的編號標註整圖最長邊（px）
CROP_EXPAND = 1.6  # 裁切框相對偵測 bbox 的外擴倍數（帶 context）
CROP_MIN_SIDE = 64  # 裁切最短邊下限（px）
MAX_CROPS_PER_IMAGE = 8  # 依信心排序最多送前 N 張裁切給 VLM

# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

DEFAULT_WORKERS = 2  # M4 加入 RPM 限速器後再調高
VLM_ON_CLEAN = False  # 無瑕疵影像不呼叫 VLM，report 直接標「合格（未檢出瑕疵）」

PROMPT_VERSION = "v1"  # 進快取鍵；改 prompt 內容必須 bump
SCHEMA_VERSION = "v1"  # 進快取鍵；改回傳 schema 必須 bump
CACHE_DIR = REPO_ROOT / ".cache" / "vlm"
