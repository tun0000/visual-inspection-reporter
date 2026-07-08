"""成本統計：以定價表精確換算、未知模型不炸、快取命中計數。"""

import pytest

from inspector.config import MODEL_PRICING, USD_TO_TWD
from inspector.cost import CostMeter, format_usd
from inspector.providers.base import Usage


def test_cost_math_exact():
    meter = CostMeter()
    meter.add(Usage("gemini-3.1-flash-lite", input_tokens=100_000, output_tokens=10_000))
    pricing = MODEL_PRICING["gemini-3.1-flash-lite"]
    expected = (100_000 * pricing.input_usd_per_m + 10_000 * pricing.output_usd_per_m) / 1_000_000
    assert meter.total_usd == pytest.approx(expected)
    assert meter.total_twd == pytest.approx(expected * USD_TO_TWD)


def test_cost_accumulates_per_model():
    meter = CostMeter()
    meter.add(Usage("gemini-3.1-flash-lite", 1000, 100))
    meter.add(Usage("gemini-3.1-flash-lite", 2000, 200))
    meter.add(Usage("gpt-5.4-nano", 500, 50))
    lite = meter.by_model["gemini-3.1-flash-lite"]
    assert (lite.calls, lite.input_tokens, lite.output_tokens) == (2, 3000, 300)
    assert len(meter.by_model) == 2


def test_unknown_model_pricing_is_none_not_crash():
    meter = CostMeter()
    meter.add(Usage("mystery-model", 1_000_000, 1_000_000))
    assert meter.by_model["mystery-model"].usd is None
    assert meter.total_usd == 0.0  # 未知定價不計入總額（報告另標「未知定價」）


def test_cache_hits_counted():
    meter = CostMeter()
    meter.add_cache_hit()
    meter.add_cache_hit()
    assert meter.cache_hits == 2 and meter.total_usd == 0.0


def test_format_usd_normal():
    assert format_usd(0.0136) == "$0.0136"
    assert format_usd(1.5) == "$1.5000"


def test_format_usd_tiny_amount_not_shown_as_zero():
    assert format_usd(0.0000017) == "<0.0001"
    assert format_usd(0.0) == "<0.0001"
