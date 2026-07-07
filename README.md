# visual-inspection-reporter

> PCB 產線巡檢報告產生器：本地 YOLO26 ONNX 偵測 + 商用 VLM API → 繁體中文巡檢報告

輸入一批 PCB 影像，輸出一份繁體中文巡檢報告（`report.md`）：YOLO26 小模型在本地做瑕疵偵測（ONNX Runtime、CPU 即可），偵測結果（標註圖 + 裁切圖 + JSON）交給商用 VLM（預設 Gemini flash-lite 級）做嚴重度分級、繁中說明與建議處置，最後彙整成含總覽統計與成本附錄的報告。

**展示重點：API 工程與系統整合** — 供應商抽象層（Gemini / OpenAI 可切換）、結構化輸出（JSON schema）、內容雜湊快取、指數退避重試、併發與 RPM 限速、token 用量與成本統計。

<!-- TODO(M6): 架構圖 (mermaid)、範例報告截圖、demo GIF -->

## 快速開始

```bash
uv sync
uv run python inspect_cli.py --input-dir sample_images --output output/
```

<!-- TODO(M6): 完整參數說明、Gradio 用法、成本估算表（每 100 張影像）、
     「為什麼偵測用自訓小模型、理解與文字生成用 API 大模型」取捨說明、
     重現步驟、HF 權重連結 -->

## 模型與資料

- 偵測模型：[betty0/pcb-defect-detection](https://huggingface.co/betty0/pcb-defect-detection)（YOLO26n，6 類 PCB 瑕疵，ONNX 匯出）。
- 資料集：HRIPCB（PKU-Market-PCB），來源 [Kaggle akhatova/pcb-defects](https://www.kaggle.com/datasets/akhatova/pcb-defects)，授權未明，引用 [Huang & Wei (2019)](https://arxiv.org/abs/1901.08204)。影像不隨 repo 發佈。

## License

AGPL-3.0-or-later（偵測模型與推論程式碼衍生自以 ultralytics 訓練的 [pcb-defect-detection](https://huggingface.co/betty0/pcb-defect-detection)，受 AGPL 授權傳染條款約束）。
