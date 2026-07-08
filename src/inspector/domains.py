"""Domain profiles：同一條 pipeline（偵測 → findings → VLM 結構化輸出 → 報告）
換一組權重/類別/prompt/報告詞彙就能服務不同任務，展示可移植性。

新增領域只需要：1) 一組 ONNX 權重 2) 類別表(英/中) 3) 一段 VLM prompt
4) 報告用詞彙，其餘 detector/findings/pipeline/report 程式碼完全不用改。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from inspector.config import REPO_ROOT
from inspector.prompt import PCB_INSPECTION_PROMPT, UAV_INSPECTION_PROMPT


@dataclass(frozen=True)
class DomainProfile:
    name: str
    report_title_zh: str  # report.md/html 標題
    model_desc_zh: str  # 報告內「偵測模型」說明
    weights: object  # Path，型別放寬避免 import 順序問題
    class_names: list[str]
    class_names_zh: dict[str, str]
    prompt: str  # 給 VLM 的完整 system prompt
    conf: float  # 預設偵測信心閾值
    caveats_zh: list[str] = field(default_factory=list)  # 報告末尾「注意事項」


PCB_CLASS_NAMES = [
    "missing_hole",
    "mouse_bite",
    "open_circuit",
    "short",
    "spur",
    "spurious_copper",
]

PCB_CLASS_NAMES_ZH = {
    "missing_hole": "缺孔",
    "mouse_bite": "鼠咬",
    "open_circuit": "斷路",
    "short": "短路",
    "spur": "毛刺",
    "spurious_copper": "殘銅",
}

UAV_CLASS_NAMES = [
    "pedestrian",
    "people",
    "bicycle",
    "car",
    "van",
    "truck",
    "tricycle",
    "awning-tricycle",
    "bus",
    "motor",
]

UAV_CLASS_NAMES_ZH = {
    "pedestrian": "行人",
    "people": "群聚人群",
    "bicycle": "腳踏車",
    "car": "小客車",
    "van": "廂型車",
    "truck": "卡車",
    "tricycle": "三輪車",
    "awning-tricycle": "篷布三輪車",
    "bus": "公車",
    "motor": "機車",
}

PCB_PROFILE = DomainProfile(
    name="pcb",
    report_title_zh="PCB 巡檢報告",
    model_desc_zh="YOLO26n ONNX（PCB 6 類瑕疵）",
    weights=REPO_ROOT / "weights" / "best.onnx",
    class_names=PCB_CLASS_NAMES,
    class_names_zh=PCB_CLASS_NAMES_ZH,
    prompt=PCB_INSPECTION_PROMPT,
    conf=0.25,
    caveats_zh=[
        "偵測模型並非完美：上游測試集實測 `short` 類 AP50 僅 0.565、`spurious_copper` 0.793，"
        "可能漏檢；VLM 僅評估「已被偵測到」的項目。",
        "flash-lite 級 VLM 對細微低對比瑕疵（如殘銅細線）可能誤判為誤檢；"
        "重要批次可用 `--model gemini-3.5-flash` 升級複核（成本約 15 倍，見 README）。",
        "疑似誤檢項由 VLM 於說明中標註，最終處置仍建議人工確認。",
    ],
)

UAV_PROFILE = DomainProfile(
    name="uav",
    report_title_zh="無人機空拍巡邏報告",
    model_desc_zh="YOLO26s ONNX（VisDrone 10 類物件）",
    weights=REPO_ROOT / "weights" / "yolo26s_visdrone_640.onnx",
    class_names=UAV_CLASS_NAMES,
    class_names_zh=UAV_CLASS_NAMES_ZH,
    prompt=UAV_INSPECTION_PROMPT,
    conf=0.25,
    caveats_zh=[
        "偵測模型並非完美：上游 VisDrone 驗證集實測 `awning-tricycle` AP50-95 僅 0.107、"
        "`bicycle` 僅 0.124（小型/形變類別數量少、難偵測），且極小物件（<16px）AP 明顯偏低；"
        "VLM 僅評估「已被偵測到」的物件，畫面中過小或被遮蔽的目標可能漏檢。",
        "本模型僅做單張影像物件偵測，不含跨畫面追蹤／車流計數（那是另一支獨立腳本疊加 ByteTrack 才有的功能）。",
        "VisDrone 資料集僅限學術研究用途；本工具僅重用其訓練出的權重做偵測示範，不隨 repo 散布任何 VisDrone 影像。",
    ],
)

DOMAIN_PROFILES: dict[str, DomainProfile] = {"pcb": PCB_PROFILE, "uav": UAV_PROFILE}
DEFAULT_DOMAIN = "pcb"


def get_domain(name: str) -> DomainProfile:
    try:
        return DOMAIN_PROFILES[name]
    except KeyError:
        raise ValueError(f"未知的 domain：{name}（可用：{sorted(DOMAIN_PROFILES)}）") from None
