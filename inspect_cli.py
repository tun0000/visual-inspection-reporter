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
    parser.add_argument("--no-cache", action="store_true", help="停用 VLM 回應快取")
    parser.add_argument("--detect-only", action="store_true", help="只跑偵測，不呼叫 VLM、不出報告")
    return parser.parse_args()


def main() -> None:
    load_dotenv(REPO_ROOT / ".env")
    args = parse_args()

    from inspector.pipeline import run_detection

    results = run_detection(args.input_dir, args.output, conf=args.conf)

    print(f"\n偵測完成：{len(results)} 張影像")
    for r in results:
        counts = Counter(f.detection.class_name for f in r.findings.findings)
        summary = ", ".join(f"{k}x{v}" for k, v in sorted(counts.items())) or "無瑕疵"
        print(f"  {r.findings.image_path.name}: {summary}")

    if args.detect_only:
        print(f"\n標註圖與裁切圖已存於 {args.output}/images、{args.output}/crops")
        return

    raise SystemExit("VLM 評估與報告產出尚未實作（M2/M3 進行中），請先用 --detect-only。")


if __name__ == "__main__":
    main()
