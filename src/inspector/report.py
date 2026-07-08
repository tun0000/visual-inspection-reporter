"""報告渲染：report.md（人讀）與 report.json（機器可讀）。"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from inspector.config import CLASS_NAMES_ZH, USD_TO_TWD
from inspector.cost import CostMeter, format_usd
from inspector.pipeline import BatchResult, ImageResult
from inspector.schema import SEVERITY_ZH, VERDICT_ZH


def _cell(text: str) -> str:
    """Markdown 表格儲存格跳脫：管線符與換行會破壞表格。"""
    return text.replace("|", "／").replace("\n", " ")


def _image_verdict(r: ImageResult) -> str:
    if r.error:
        return "評估失敗"
    if not r.findings.findings:
        return "合格（未檢出瑕疵）"
    if r.assessed is None:
        return "未評估"
    return VERDICT_ZH[r.assessed.assessment.verdict]


def _overview(batch: BatchResult) -> list[str]:
    lines = ["## 總覽", ""]

    verdict_counts = Counter(_image_verdict(r) for r in batch.results)
    lines += ["| 單板判定 | 張數 |", "|---|---|"]
    lines += [f"| {v} | {n} |" for v, n in verdict_counts.most_common()]
    lines.append("")

    class_counts = Counter(
        f.detection.class_name for r in batch.results for f in r.findings.findings
    )
    if class_counts:
        lines += ["| 瑕疵類別 | 偵測數 |", "|---|---|"]
        lines += [
            f"| {CLASS_NAMES_ZH[c]}（{c}） | {n} |" for c, n in class_counts.most_common()
        ]
        lines.append("")

    severity_counts = Counter(
        SEVERITY_ZH[fa.severity]
        for r in batch.results
        if r.assessed
        for fa in r.assessed.assessment.findings
    )
    if severity_counts:
        lines += ["| 嚴重度 | 項數 |", "|---|---|"]
        lines += [f"| {s} | {n} |" for s, n in severity_counts.most_common()]
        lines.append("")
    return lines


def _detail(index: int, r: ImageResult, output_dir: Path) -> list[str]:
    name = r.findings.image_path.name
    lines = [f"### {index}. {name} — 判定：{_image_verdict(r)}", ""]
    lines += [f"![{name}]({r.annotated_path.relative_to(output_dir).as_posix()})", ""]

    if r.error:
        lines += [f"> ⚠ VLM 評估失敗：{r.error}", ""]
        return lines
    if not r.findings.findings:
        lines += ["未檢出瑕疵，未呼叫 VLM。", ""]
        return lines

    conf_by_id = {f.finding_id: f.detection for f in r.findings.findings}
    lines += [
        "| # | 類別 | 信心 | 嚴重度 | 說明 | 建議處置 |",
        "|---|---|---|---|---|---|",
    ]
    if r.assessed:
        for fa in sorted(r.assessed.assessment.findings, key=lambda x: x.finding_id):
            det = conf_by_id[fa.finding_id]
            lines.append(
                f"| #{fa.finding_id} | {CLASS_NAMES_ZH[det.class_name]}（{det.class_name}） "
                f"| {det.conf:.2f} | {SEVERITY_ZH[fa.severity]} "
                f"| {_cell(fa.description_zh)} | {_cell(fa.action_zh)} |"
            )
        for fid in r.assessed.missing_ids:
            det = conf_by_id[fid]
            lines.append(
                f"| #{fid} | {CLASS_NAMES_ZH[det.class_name]}（{det.class_name}） "
                f"| {det.conf:.2f} | — | VLM 未評估此項 | 建議人工複檢 |"
            )
        lines.append("")
        lines += [f"**總評**：{r.assessed.assessment.summary_zh}", ""]
        for w in r.assessed.warnings:
            lines += [f"> ⚠ {w}", ""]
    return lines


def _cost_appendix(meter: CostMeter, elapsed_s: float) -> list[str]:
    lines = ["## 附錄：token 用量與成本", ""]
    if meter.by_model:
        lines += [
            "| 模型 | API 呼叫 | input tokens | output tokens | 成本 (USD) |",
            "|---|---|---|---|---|",
        ]
        for mc in meter.by_model.values():
            usd = format_usd(mc.usd) if mc.usd is not None else "未知定價"
            lines.append(
                f"| {mc.model_id} | {mc.calls} | {mc.input_tokens:,} | {mc.output_tokens:,} | {usd} |"
            )
        lines.append("")
    lines += [
        f"- 快取命中：{meter.cache_hits} 張（不重打 API、計 0 成本）",
        f"- 本次估算成本：**{format_usd(meter.total_usd)} USD**",
        f"- 執行耗時：{elapsed_s:.1f} 秒",
        "",
        "> 成本以各模型「付費層」官方定價換算（單價見 `src/inspector/config.py`，"
        "查證日期 2026-07-08）；token 數為 API 回傳的實際用量。"
        "若使用免費層金鑰，實際帳單為 $0，此數字代表換到付費層的花費。",
        "",
    ]
    return lines


def render_report(batch: BatchResult, output_dir: Path) -> Path:
    """把整批結果渲染成 output_dir/report.md，回傳報告路徑。"""
    lines = [
        "# PCB 巡檢報告",
        "",
        f"- 影像數：{len(batch.results)}",
        f"- 偵測模型：YOLO26n ONNX（conf ≥ {batch.conf}）",
        f"- VLM：{batch.provider_name} / {batch.model_id}"
        + ("（--detect-only，未呼叫）" if batch.detect_only else ""),
        "",
    ]
    lines += _overview(batch)

    lines += ["## 逐圖明細", ""]
    for i, r in enumerate(batch.results, 1):
        lines += _detail(i, r, output_dir)

    if not batch.detect_only:
        lines += _cost_appendix(batch.meter, batch.elapsed_s)

    lines += [
        "## 注意事項",
        "",
        "- 偵測模型並非完美：上游測試集實測 `short` 類 AP50 僅 0.565、"
        "`spurious_copper` 0.793，可能漏檢；VLM 僅評估「已被偵測到」的項目。",
        "- flash-lite 級 VLM 對細微低對比瑕疵（如殘銅細線）可能誤判為誤檢；"
        "重要批次可用 `--model gemini-3.5-flash` 升級複核（成本約 15 倍，見 README）。",
        "- 疑似誤檢項由 VLM 於說明中標註，最終處置仍建議人工確認。",
        "",
    ]

    report_path = output_dir / "report.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


def render_json(batch: BatchResult, output_dir: Path) -> Path:
    """機器可讀版報告：output_dir/report.json。"""
    images = []
    for r in batch.results:
        assessed_by_id = (
            {fa.finding_id: fa for fa in r.assessed.assessment.findings} if r.assessed else {}
        )
        findings = []
        for f in r.findings.findings:
            fa = assessed_by_id.get(f.finding_id)
            findings.append(
                {
                    "id": f.finding_id,
                    "class": f.detection.class_name,
                    "class_zh": CLASS_NAMES_ZH[f.detection.class_name],
                    "confidence": round(f.detection.conf, 3),
                    "bbox_xyxy": [round(v, 1) for v in f.detection.xyxy],
                    "assessed": fa is not None,
                    "severity": fa.severity.value if fa else None,
                    "description_zh": fa.description_zh if fa else None,
                    "action_zh": fa.action_zh if fa else None,
                }
            )
        images.append(
            {
                "image": r.findings.image_path.name,
                "verdict_zh": _image_verdict(r),
                "verdict": r.assessed.assessment.verdict.value if r.assessed else None,
                "summary_zh": r.assessed.assessment.summary_zh if r.assessed else None,
                "warnings": r.assessed.warnings if r.assessed else [],
                "cache_hit": r.cache_hit,
                "error": r.error,
                "annotated_image": r.annotated_path.relative_to(output_dir).as_posix(),
                "findings": findings,
            }
        )

    payload = {
        "meta": {
            "generated": batch.started.isoformat(timespec="seconds"),
            "provider": batch.provider_name,
            "model": batch.model_id,
            "conf_threshold": batch.conf,
            "elapsed_s": round(batch.elapsed_s, 1),
            "image_count": len(batch.results),
            "detect_only": batch.detect_only,
        },
        "cost": {
            "models": [
                {
                    "model": mc.model_id,
                    "calls": mc.calls,
                    "input_tokens": mc.input_tokens,
                    "output_tokens": mc.output_tokens,
                    "usd": round(mc.usd, 6) if mc.usd is not None else None,
                }
                for mc in batch.meter.by_model.values()
            ],
            "cache_hits": batch.meter.cache_hits,
            "total_usd": round(batch.meter.total_usd, 6),
            "total_twd": round(batch.meter.total_twd, 2),
            "usd_to_twd": USD_TO_TWD,
        },
        "images": images,
    }
    json_path = output_dir / "report.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return json_path
