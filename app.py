"""Gradio 介面：拖一批 PCB 影像 → 線上看巡檢報告。

    uv run python app.py   # http://localhost:7860

Gradio 6 用法核對日期 2026-07-08：theme/css 已從 gr.Blocks() 建構子移到
demo.launch()（https://www.gradio.app/main/guides/gradio-6-migration-guide）。
主題設計取捨見 PRODUCT.md（product register：沉穩、克制、資訊密度優先）。
"""

from __future__ import annotations

import re
import shutil
import tempfile
from pathlib import Path

import gradio as gr
from dotenv import load_dotenv
from gradio.themes.utils import colors, fonts, sizes

from inspector.config import DEFAULT_MODELS, DEFAULT_PROVIDER, REPO_ROOT

load_dotenv(REPO_ROOT / ".env")

from inspector.pipeline import run_batch  # noqa: E402 — 需先載入 .env
from inspector.report import _image_verdict, render_json, render_report  # noqa: E402

IMG_MD_LINE = re.compile(r"^!\[.*\]\(.*\)\n?", flags=re.MULTILINE)

# ---------------------------------------------------------------------------
# 主題：深夜產線監控站——深色主控螢幕，只有需要注意的地方（互動元件）亮起。
# OKLCH 數值皆通過對比驗證（ink/bg ≥7:1、button 文字 ≥4.5:1），見 PRODUCT.md。
# 強調色（accent）與報告內部嚴重度色階（紅/橘/灰黃）刻意不同色系，兩者不混用。
# _dark 變體刻意設為與亮值相同：無論檢視者系統是亮/暗色，畫面都固定深色，
# 確保錄 demo GIF 時外觀一致，不受觀看端系統設定影響。
# ---------------------------------------------------------------------------
_C = {
    "bg": "oklch(0.16 0.014 268)",
    "surface": "oklch(0.23 0.018 268)",
    "surface2": "oklch(0.28 0.02 268)",
    "surface3": "oklch(0.33 0.022 268)",
    "border": "oklch(0.32 0.02 268)",
    "border_strong": "oklch(0.42 0.024 268)",
    "ink": "oklch(0.94 0.006 268)",
    "muted": "oklch(0.64 0.012 268)",
    "primary": "oklch(0.32 0.17 270)",
    "primary_hover": "oklch(0.27 0.17 270)",
    "primary_active": "oklch(0.22 0.16 270)",
    "on_primary": "oklch(0.98 0 0)",
    "accent": "oklch(0.80 0.10 195)",
    "accent_hover": "oklch(0.88 0.08 195)",
    "accent_soft": "oklch(0.80 0.10 195 / 0.16)",
    "error_bg": "oklch(0.24 0.05 25)",
    "error_border": "oklch(0.42 0.09 25)",
    "error_text": "oklch(0.90 0.03 25)",
}

_theme = gr.themes.Base(
    primary_hue=colors.indigo,
    neutral_hue=colors.slate,
    spacing_size=sizes.spacing_sm,
    radius_size=sizes.radius_md,
    font=fonts.GoogleFont("Inter", weights=(400, 500, 600, 700)),
    font_mono=fonts.GoogleFont("JetBrains Mono", weights=(400, 500)),
).set(
    # 全域
    body_background_fill=_C["bg"],
    body_background_fill_dark=_C["bg"],
    body_text_color=_C["ink"],
    body_text_color_dark=_C["ink"],
    body_text_color_subdued=_C["muted"],
    body_text_color_subdued_dark=_C["muted"],
    background_fill_primary=_C["surface"],
    background_fill_primary_dark=_C["surface"],
    background_fill_secondary=_C["surface2"],
    background_fill_secondary_dark=_C["surface2"],
    border_color_primary=_C["border"],
    border_color_primary_dark=_C["border"],
    border_color_accent=_C["accent"],
    border_color_accent_dark=_C["accent"],
    border_color_accent_subdued=_C["accent_soft"],
    border_color_accent_subdued_dark=_C["accent_soft"],
    color_accent=_C["accent"],
    color_accent_soft=_C["accent_soft"],
    color_accent_soft_dark=_C["accent_soft"],
    # 連結
    link_text_color=_C["accent"],
    link_text_color_dark=_C["accent"],
    link_text_color_hover=_C["accent_hover"],
    link_text_color_hover_dark=_C["accent_hover"],
    link_text_color_active=_C["accent"],
    link_text_color_visited=_C["accent"],
    code_background_fill=_C["surface2"],
    code_background_fill_dark=_C["surface2"],
    # 陰影：扁平克制，不做寬模糊的「ghost card」
    shadow_drop="0 1px 2px oklch(0 0 0 / 0.35)",
    shadow_drop_lg="0 2px 6px oklch(0 0 0 / 0.35)",
    shadow_spread="1px",
    shadow_spread_dark="1px",
    # 區塊 / 面板
    block_background_fill=_C["surface"],
    block_background_fill_dark=_C["surface"],
    block_border_color=_C["border"],
    block_border_color_dark=_C["border"],
    block_border_width="1px",
    block_label_background_fill=_C["surface2"],
    block_label_background_fill_dark=_C["surface2"],
    block_label_border_color=_C["border"],
    block_label_border_color_dark=_C["border"],
    block_label_text_color=_C["muted"],
    block_label_text_color_dark=_C["muted"],
    block_title_text_color=_C["ink"],
    block_title_text_color_dark=_C["ink"],
    block_info_text_color=_C["muted"],
    block_info_text_color_dark=_C["muted"],
    panel_background_fill=_C["surface"],
    panel_background_fill_dark=_C["surface"],
    panel_border_color=_C["border"],
    panel_border_color_dark=_C["border"],
    # 按鈕：只有主按鈕帶強調色，其餘中性
    button_primary_background_fill=_C["primary"],
    button_primary_background_fill_dark=_C["primary"],
    button_primary_background_fill_hover=_C["primary_hover"],
    button_primary_background_fill_hover_dark=_C["primary_hover"],
    button_primary_border_color=_C["primary"],
    button_primary_border_color_dark=_C["primary"],
    button_primary_border_color_hover=_C["primary_hover"],
    button_primary_text_color=_C["on_primary"],
    button_primary_text_color_dark=_C["on_primary"],
    button_primary_shadow="none",
    button_primary_shadow_hover="none",
    button_secondary_background_fill=_C["surface2"],
    button_secondary_background_fill_dark=_C["surface2"],
    button_secondary_background_fill_hover=_C["surface3"],
    button_secondary_background_fill_hover_dark=_C["surface3"],
    button_secondary_border_color=_C["border"],
    button_secondary_border_color_dark=_C["border"],
    button_secondary_text_color=_C["ink"],
    button_secondary_text_color_dark=_C["ink"],
    button_secondary_shadow="none",
    button_transition="background-color 150ms ease-out, border-color 150ms ease-out",
    # 輸入元件：focus 用 accent，呼應「強調色只用在互動狀態」原則
    input_background_fill=_C["surface2"],
    input_background_fill_dark=_C["surface2"],
    input_background_fill_focus=_C["surface3"],
    input_background_fill_focus_dark=_C["surface3"],
    input_background_fill_hover=_C["surface3"],
    input_border_color=_C["border"],
    input_border_color_dark=_C["border"],
    input_border_color_focus=_C["accent"],
    input_border_color_focus_dark=_C["accent"],
    input_border_color_hover=_C["border_strong"],
    input_placeholder_color=_C["muted"],
    input_placeholder_color_dark=_C["muted"],
    input_shadow="none",
    input_shadow_focus=f"0 0 0 3px {_C['accent_soft']}",
    # 表格（gr.Dataframe 用；報告內文表格另由 CSS 的 .prose table 處理）
    table_border_color=_C["border"],
    table_border_color_dark=_C["border"],
    table_even_background_fill=_C["surface"],
    table_even_background_fill_dark=_C["surface"],
    table_odd_background_fill=_C["surface2"],
    table_odd_background_fill_dark=_C["surface2"],
    # 錯誤提示：獨立色系，不借用報告內部嚴重度紅
    error_background_fill=_C["error_bg"],
    error_background_fill_dark=_C["error_bg"],
    error_border_color=_C["error_border"],
    error_border_color_dark=_C["error_border"],
    error_text_color=_C["error_text"],
    error_text_color_dark=_C["error_text"],
    # 進度條 / 載入指示
    loader_color=_C["accent"],
    loader_color_dark=_C["accent"],
    slider_color=_C["accent"],
    slider_color_dark=_C["accent"],
)

_css = f"""
.gradio-container {{
    max-width: 1180px !important;
    margin: 0 auto !important;
}}

/* 標題區：與下方雙欄用一條中性分隔線隔開（不用強調色裝飾） */
#header {{
    padding-bottom: var(--spacing-lg);
    margin-bottom: var(--spacing-lg);
    border-bottom: 1px solid {_C["border"]};
}}
#header h1 {{
    font-weight: 700;
    letter-spacing: -0.02em;
    margin-bottom: 0.25rem;
}}
#header p {{
    color: {_C["muted"]};
    max-width: 70ch;
}}

/* 左側控制面板：gr.Column variant="panel" 在目前 Gradio 版本無視覺效果
   （已實測確認），改用 elem_id 手動給背景/邊框/圓角做出面板分層 */
#control-panel {{
    background: {_C["surface2"]};
    border: 1px solid {_C["border"]};
    border-radius: var(--radius-lg, 8px);
    padding: var(--spacing-lg, 16px);
}}

/* 報告內文（gr.Markdown 渲染的 report.md）：表格是資訊密度最高的區塊，
   明確給邊框、表頭底色與斑馬紋，取代瀏覽器預設樣式 */
#report-panel .prose table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 0.9em;
}}
#report-panel .prose th,
#report-panel .prose td {{
    border: 1px solid {_C["border"]};
    padding: 0.5em 0.75em;
    text-align: left;
}}
#report-panel .prose thead th {{
    background: {_C["surface2"]};
    color: {_C["ink"]};
    font-weight: 600;
}}
#report-panel .prose tbody tr:nth-child(even) {{
    background: {_C["surface2"]};
}}
#report-panel .prose h1,
#report-panel .prose h2,
#report-panel .prose h3 {{
    letter-spacing: -0.01em;
}}
#report-panel .prose blockquote {{
    border-left: 3px solid {_C["accent"]};
    color: {_C["muted"]};
    margin-left: 0;
    padding-left: 1em;
}}

/* 鍵盤可及性：可見的 focus 提示（非裝飾性動畫） */
button:focus-visible, a:focus-visible {{
    outline: 2px solid {_C["accent"]};
    outline-offset: 2px;
}}

@media (prefers-reduced-motion: reduce) {{
    *, *::before, *::after {{
        transition-duration: 0.01ms !important;
        animation-duration: 0.01ms !important;
    }}
}}
"""


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
    with gr.Column(elem_id="header"):
        gr.Markdown("# PCB 巡檢報告產生器")
        gr.Markdown(
            "本地 YOLO26 ONNX 偵測 + 商用 VLM 評估 → 繁體中文巡檢報告。"
            "拖入一批 PCB 影像，產出總覽統計、逐圖明細與成本附錄。"
        )
    with gr.Row(equal_height=False):
        with gr.Column(scale=1, elem_id="control-panel"):
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
        with gr.Column(scale=2, elem_id="report-panel"):
            gallery = gr.Gallery(label="編號標註圖", columns=2, height=380, object_fit="contain")
            report_md = gr.Markdown()

    run_btn.click(inspect_files, inputs=[files, provider, model], outputs=[report_md, gallery, report_file])

if __name__ == "__main__":
    demo.launch(theme=_theme, css=_css)
