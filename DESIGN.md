# Design

## Theme

**深夜產線監控站**——深色主控螢幕，只有互動元件（按鈕、連結、focus 狀態）亮起，其餘資訊維持中性灰階。固定深色（不隨系統淺色模式切換），確保 demo 錄影外觀一致。強制策略：`app.py` 對每個色彩 token 都把 `_dark` 變體設為與基礎值相同。

強調色與報告內文的嚴重度色階（重大=紅、中等=橘、輕微=灰黃）刻意不同色系、不共用——介面強調色只用於互動狀態，語義色只存在於報告內容。

色彩策略：Restrained（product 預設）——強調色僅用於主要操作、當前選取、狀態指示，不作裝飾。

## Palette

全部使用 OKLCH，數值定義於 `app.py` 的 `_C` dict。已驗證對比（見下方 contrast 欄）。

| Token | OKLCH | 用途 | Contrast |
|---|---|---|---|
| `bg` | `oklch(0.16 0.014 268)` | 頁面背景 | — |
| `surface` | `oklch(0.23 0.018 268)` | Block/元件背景 | vs bg 1.5:1 |
| `surface2` | `oklch(0.28 0.02 268)` | 面板背景、表格底色、hover | vs bg 1.6:1 |
| `surface3` | `oklch(0.33 0.022 268)` | 二級 hover/focus 背景 | — |
| `border` | `oklch(0.32 0.02 268)` | 一般邊框/分隔線 | vs bg 2.45:1 |
| `border_strong` | `oklch(0.42 0.024 268)` | 輸入框 hover 邊框 | — |
| `ink` | `oklch(0.94 0.006 268)` | 主要文字 | vs bg 9.61:1 |
| `muted` | `oklch(0.64 0.012 268)` | 次要文字 | vs bg 5.92:1 |
| `primary` | `oklch(0.32 0.17 270)` | 主按鈕、互動主色（indigo/violet） | 白字 5.56:1 |
| `primary_hover` / `primary_active` | `oklch(0.27/0.22 0.17/0.16 270)` | 按鈕 hover/pressed（更深＝對比更高） | — |
| `on_primary` | `oklch(0.98 0 0)` | 主按鈕文字 | — |
| `accent` | `oklch(0.80 0.10 195)` | 連結、focus 環、狀態指示（cyan/teal） | 深色底文字 7.74:1 |
| `error_bg/border/text` | hue 25（暖紅） | Gradio 系統錯誤提示，獨立於報告嚴重度紅 | — |

**取色邏輯**：primary（indigo，hue 270）與 accent（cyan，hue 195）故意選在色相輪上有明顯距離（Δ75°）且明度不同，兩者對比 2.21:1，不會被誤認是同一色的深淺變化。

## Typography

- 字型：`Inter`（400/500/600/700，Google Font）；等寬 `JetBrains Mono`（400/500，用於模型 ID 等代碼感文字）。單一家族承載標題與內文，符合 product register「一個字型家族就夠」原則。
- 標題（`h1`）：weight 700、letter-spacing -0.02em。
- Body：沿用 Gradio 預設 `text_size=md`；表格內文縮至 0.9em 提高密度。

## Spacing & Radius

- `spacing_size = sizes.spacing_sm`（資訊密度優先於留白）。
- `radius_size = sizes.radius_md`（頂多 12px，不用大圓角卡片）。
- 陰影統一扁平化：`shadow_drop`/`shadow_drop_lg` 縮到 1–2px 模糊，避免「1px 邊框＋大範圍陰影」的 AI 感 ghost-card。

## Layout

- `.gradio-container` 限制 `max-width: 1180px` 並置中，避免內容貼滿超寬視窗邊緣。
- 標題區（`#header`）與雙欄主體之間用 1px 中性邊框分隔（不用強調色裝飾）。
- 左側控制面板（`#control-panel`）：`gr.Column(variant="panel")` 在目前安裝的 Gradio 6.20.0 **實測無視覺效果**（原始碼確認 Svelte 前端未渲染對應樣式），改用 `elem_id` 手動賦予 `surface2` 背景＋邊框＋圓角＋padding。日後升級 Gradio 版本後應重新測試 `variant="panel"` 是否修復，若有效可移除這段手動 CSS。
- 右側內容區（`#report-panel`）：`.prose table/th/td` 明確定義邊框、表頭底色（`surface2`）、斑馬紋（偶數列 `surface2`），取代瀏覽器預設表格樣式——這是報告最資訊密集的區塊。

## Components

- 按鈕：僅「產出巡檢報告」為 `variant="primary"`（唯一帶強調色的操作），其餘（下載連結、上傳框）維持中性 `surface`/`border`。
- 輸入框：預設 `surface2`、focus 態邊框＋外環用 `accent`（呼應「強調色只用在互動狀態」原則），hover 用 `border_strong`。
- Focus-visible：所有按鈕/連結有 2px `accent` outline，滿足鍵盤可及性。
- `prefers-reduced-motion: reduce` 全域降級所有 transition/animation 至趨近 0。

## 已知限制

- 自動化預覽工具（Claude Preview）在這個 Gradio session 中，`preview_screenshot` 持續逾時、且一度回報 `window.innerWidth=0`——判斷為工具本身的 viewport/screenshot 時序問題，與程式碼無關（已用 `preview_inspect` 逐一驗證每個色彩/字型/間距 token 的 computed style 皆正確套用）。實際整體版面觀感仍建議在真實瀏覽器（`http://localhost:7860`）目視確認一次。
