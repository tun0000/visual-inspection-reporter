"""Gradio 介面：拖一批 PCB 影像 → 線上看巡檢報告。

    uv run python app.py   # http://localhost:7860

Gradio 6 用法核對日期 2026-07-08：
https://www.gradio.app/main/guides/gradio-6-migration-guide
"""

from __future__ import annotations

import re
import shutil
import tempfile
from pathlib import Path

import gradio as gr
from dotenv import load_dotenv

from inspector.config import DEFAULT_MODELS, DEFAULT_PROVIDER, REPO_ROOT

load_dotenv(REPO_ROOT / ".env")

from inspector.pipeline import run_batch  # noqa: E402 — 需先載入 .env
from inspector.report import _image_verdict, render_json, render_report  # noqa: E402

IMG_MD_LINE = re.compile(r"^!\[.*\]\(.*\)\n?", flags=re.MULTILINE)


def inspect_files(files: list[str] | None, provider: str, model: str, progress=gr.Progress()):
    if not files:
        raise gr.Error("請先拖入至少一張 PCB 影像")

    workdir = Path(tempfile.mkdtemp(prefix="vir-"))
    input_dir = workdir / "input"
    output_dir = workdir / "output"
    input_dir.mkdir(parents=True)
    for f in files:
        shutil.copy(f, input_dir / Path(f).name)

    progress(0.1, desc="YOLO 偵測中…")
    batch = run_batch(
        input_dir,
        output_dir,
        provider_name=provider,
        model_id=model.strip() or None,
    )
    progress(0.85, desc="產出報告…")
    report_path = render_report(batch, output_dir)
    render_json(batch, output_dir)

    # 報告內的圖是相對路徑，網頁端由 Gallery 顯示，Markdown 拿掉圖片行
    markdown = IMG_MD_LINE.sub("", report_path.read_text(encoding="utf-8"))
    gallery = [
        (str(r.annotated_path), f"{r.findings.image_path.name}｜{_image_verdict(r)}")
        for r in batch.results
    ]
    return markdown, gallery, str(report_path)


with gr.Blocks(title="PCB 巡檢報告產生器") as demo:
    gr.Markdown(
        "# PCB 巡檢報告產生器\n"
        "本地 YOLO26 ONNX 偵測 + 商用 VLM 評估 → 繁體中文巡檢報告。"
        "拖入一批 PCB 影像，產出總覽統計、逐圖明細與成本附錄。"
    )
    with gr.Row():
        with gr.Column(scale=1):
            files = gr.File(
                label="PCB 影像（可多選）",
                file_count="multiple",
                file_types=["image"],
            )
            provider = gr.Dropdown(
                choices=sorted(DEFAULT_MODELS), value=DEFAULT_PROVIDER, label="VLM 供應商"
            )
            model = gr.Textbox(
                label="模型 ID（留空用預設）",
                placeholder=f"預設：{DEFAULT_MODELS[DEFAULT_PROVIDER]}",
            )
            run_btn = gr.Button("產出巡檢報告", variant="primary")
            report_file = gr.File(label="下載 report.md", interactive=False)
        with gr.Column(scale=2):
            gallery = gr.Gallery(label="編號標註圖", columns=2, height=360)
            report_md = gr.Markdown()

    run_btn.click(inspect_files, inputs=[files, provider, model], outputs=[report_md, gallery, report_file])

if __name__ == "__main__":
    demo.launch()
