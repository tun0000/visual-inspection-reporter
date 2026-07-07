"""VLM 結構化輸出的 schema 與解析防呆。

schema 直接以 Pydantic 模型傳給供應商 SDK 的結構化輸出功能；
改動任何欄位或 enum 記得 bump config.SCHEMA_VERSION（快取鍵的一部分）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from pydantic import BaseModel, Field


class Severity(str, Enum):
    CRITICAL = "critical"  # 重大：直接造成功能失效或安全疑慮
    MAJOR = "major"  # 中等：可能影響可靠度或壽命，需要處理
    MINOR = "minor"  # 輕微：外觀性或輕微缺損，風險低


class Verdict(str, Enum):
    PASS = "pass"  # 合格：僅 minor 或無瑕疵
    REWORK = "rework"  # 需複檢/返修：無 critical 但有 major
    FAIL = "fail"  # 不合格：存在任何 critical


SEVERITY_ZH = {Severity.CRITICAL: "重大", Severity.MAJOR: "中等", Severity.MINOR: "輕微"}
VERDICT_ZH = {Verdict.PASS: "合格", Verdict.REWORK: "需複檢", Verdict.FAIL: "不合格"}


class FindingAssessment(BaseModel):
    finding_id: int = Field(description="對應輸入偵測 JSON 的 id，不得新增或省略")
    severity: Severity = Field(description="此瑕疵的嚴重度")
    description_zh: str = Field(description="繁體中文描述此瑕疵的外觀、位置與嚴重度判斷理由，1-2 句")
    action_zh: str = Field(description="繁體中文建議處置，1 句")


class ImageAssessment(BaseModel):
    verdict: Verdict = Field(description="整張板子的判定")
    summary_zh: str = Field(description="繁體中文總評，2-3 句：整體狀況、主要風險、是否可放行")
    findings: list[FindingAssessment] = Field(description="逐項評估，須涵蓋偵測 JSON 的每個 id")


@dataclass
class ReconciledAssessment:
    """對齊偵測結果後的評估：VLM 幻覺的 id 已丟棄、缺漏的 id 另列不捏造內容。"""

    assessment: ImageAssessment
    dropped_ids: list[int] = field(default_factory=list)  # VLM 回了不存在的 id（已剔除）
    missing_ids: list[int] = field(default_factory=list)  # VLM 漏評的 id（報告標「未評估」）
    warnings: list[str] = field(default_factory=list)


def reconcile(assessment: ImageAssessment, valid_ids: list[int]) -> ReconciledAssessment:
    """強制 VLM 回覆對齊輸入的 finding id 集合。"""
    valid = set(valid_ids)
    seen: set[int] = set()
    kept: list[FindingAssessment] = []
    dropped: list[int] = []

    for fa in assessment.findings:
        if fa.finding_id not in valid:
            dropped.append(fa.finding_id)
        elif fa.finding_id in seen:  # 重複評同一項：保留第一筆
            dropped.append(fa.finding_id)
        else:
            seen.add(fa.finding_id)
            kept.append(fa)

    missing = sorted(valid - seen)
    warnings = []
    if dropped:
        warnings.append(f"VLM 回覆了不存在或重複的 finding_id {sorted(set(dropped))}，已剔除")
    if missing:
        warnings.append(f"VLM 漏評 finding_id {missing}，報告中標記為未評估")

    cleaned = assessment.model_copy(update={"findings": kept})
    return ReconciledAssessment(cleaned, sorted(set(dropped)), missing, warnings)
