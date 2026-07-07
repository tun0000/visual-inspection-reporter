"""visual-inspection-reporter CLI：批次巡檢影像資料夾，產出繁體中文巡檢報告。

用法：
    uv run python inspect_cli.py --input-dir sample_images --output output/
    uv run python inspect_cli.py --input-dir sample_images --output output/ --detect-only

（檔名刻意不叫 inspect.py：會遮蔽 Python 標準庫的 inspect 模組。）
"""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv

from inspector.config import (
    DEFAULT_CONF,
    DEFAULT_MODELS,
    DEFAULT_PROVIDER,
    DEFAULT_WORKERS,
    MAX_RPM,
    REPO_ROOT,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--input-dir", type=Path, required=True, help="輸入影像資料夾")
    parser.add_argument("--output", type=Path, default=Path("output"), help="輸出資料夾（預設 output/）")
    parser.add_argument(
        "--provider", choices=sorted(DEFAULT_MODELS), default=DEFAULT_PROVIDER, help="VLM 供應商"
    )
    parser.add_argument("--model", default=None, help="VLM 模型 ID（預設依供應商，見 config.py）")
    parser.add_argument("--conf", type=float, default=DEFAULT_CONF, help="偵測信心閾值")
    parser.add_argument("--max-workers", type=int, default=DEFAULT_WORKERS, help="VLM 併發數")
    parser.add_argument(
        "--max-rpm", type=int, default=MAX_RPM, help="客戶端 RPM 限速（0 = 停用；預設對應免費層）"
    )
    parser.add_argument("--no-cache", action="store_true", help="停用 VLM 回應快取")
    parser.add_argument("--detect-only", action="store_true", help="只跑偵測，不呼叫 VLM、不出報告")
    return parser.parse_args()


def main() -> None:
    load_dotenv(REPO_ROOT / ".env")
    args = parse_args()

    from inspector.pipeline import run_batch
    from inspector.report import _image_verdict, render_json, render_report

    batch = run_batch(
        args.input_dir,
        args.output,
        provider_name=args.provider,
        model_id=args.model,
        conf=args.conf,
        workers=args.max_workers,
        max_rpm=args.max_rpm,
        use_cache=not args.no_cache,
        detect_only=args.detect_only,
    )

    print(f"\n偵測完成：{len(batch.results)} 張影像")
    for r in batch.results:
        counts = Counter(f.detection.class_name for f in r.findings.findings)
        summary = ", ".join(f"{k}x{v}" for k, v in sorted(counts.items())) or "無瑕疵"
        print(f"  {r.findings.image_path.name}: {summary}")

    if args.detect_only:
        print(f"\n標註圖與裁切圖已存於 {args.output}/images、{args.output}/crops")
        return

    report_path = render_report(batch, args.output)
    json_path = render_json(batch, args.output)
    meter = batch.meter
    print(f"\nVLM 評估完成（快取命中 {meter.cache_hits} 張）")
    for r in batch.results:
        print(f"  {r.findings.image_path.name}: {_image_verdict(r)}")
    print(
        f"\n成本估算：${meter.total_usd:.4f} USD ≈ NT${meter.total_twd:.2f}"
        f"（付費層定價換算；免費層實際帳單 $0）"
    )
    print(f"報告：{report_path}（JSON：{json_path}）")


if __name__ == "__main__":
    main()
