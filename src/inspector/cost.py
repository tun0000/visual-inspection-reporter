"""單次執行的 token 用量與成本統計。

token 數一律取 API 回傳的實際 usage；金額以 config.MODEL_PRICING（或
Gemini Batch API 的 MODEL_PRICING_BATCH）官方定價換算（免費層實際帳單
為 $0，報告標示為估算值）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from inspector.config import MODEL_PRICING, MODEL_PRICING_BATCH, USD_TO_TWD
from inspector.providers.base import Usage


def format_usd(usd: float) -> str:
    """$0.xxxx，或小到 4 位小數會四捨五入成 0 時顯示 <0.0001（而非誤導的 $0.0000）。"""
    if usd < 0.00005:
        return "<0.0001"
    return f"${usd:.4f}"


@dataclass
class ModelCost:
    model_id: str
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    batch: bool = False  # True：這個模型的用量走 Gemini Batch API 折扣價

    @property
    def usd(self) -> float | None:
        table = MODEL_PRICING_BATCH if self.batch else MODEL_PRICING
        pricing = table.get(self.model_id)
        if pricing is None:
            return None  # 未登錄定價的模型：報告標「未知定價」
        return (
            self.input_tokens * pricing.input_usd_per_m
            + self.output_tokens * pricing.output_usd_per_m
        ) / 1_000_000


@dataclass
class CostMeter:
    by_model: dict[str, ModelCost] = field(default_factory=dict)
    cache_hits: int = 0

    def add(self, usage: Usage, *, batch: bool = False) -> None:
        mc = self.by_model.setdefault(usage.model_id, ModelCost(usage.model_id, batch=batch))
        mc.calls += 1
        mc.input_tokens += usage.input_tokens
        mc.output_tokens += usage.output_tokens

    def add_cache_hit(self) -> None:
        self.cache_hits += 1

    @property
    def total_usd(self) -> float:
        return sum(mc.usd or 0.0 for mc in self.by_model.values())

    @property
    def total_twd(self) -> float:
        return self.total_usd * USD_TO_TWD
