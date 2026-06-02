# Portrait UI 直立版面設計

**日期**: 2026-05-22  
**狀態**: 已核准，待實作  
**參考圖**: `/home/kyle/Downloads/Gemini_Generated_Image_oqb4r7oqb4r7oqb4.png`

---

## 目標

將 main.cpp 的顯示器版面從橫向（800×480，側邊欄在右）改為直立（480×800，預覽在上、圖示按鈕網格在中、控制列在下），風格參考參考圖的深色背景 + 圓形預覽 + 方形圖示按鈕網格。

---

## 顯示器規格

| 項目 | 值 |
|------|-----|
| 實體解析度 | 800×480 |
| wlr-randr transform | 270 |
| Wayland 邏輯解析度 | **480×800** |
| main.cpp 視窗尺寸 | 480×800 |

---

## 版面分區（像素座標）

```
y=0   ┌─────────────────────────────┐
      │  狀態列  480×32             │  BG=#1a1a1a
y=32  ├─────────────────────────────┤
      │                             │
      │     圓形相機預覽             │  BG=#1e1e2e
      │     center=(240,192)        │  預覽區 480×320
      │     radius=140px            │
      │                             │
      │  標籤列（模式名/Agtron值）   │  h=32, BG=#1a1a1a
y=352 ├─────────────────────────────┤
      │  3×3 圖示按鈕網格            │  BG=#1a1a1a
      │  每格 160×120px             │  共 360px
      │  [3 行 × 3 欄]              │
y=712 ├─────────────────────────────┤
      │  底部控制列  480×88         │  曝光 +/- 與狀態訊息
y=800 └─────────────────────────────┘
```

---

## 新常數定義

```cpp
static const int DISP_W       = 480;   // 邏輯寬（portrait）
static const int DISP_H       = 800;   // 邏輯高（portrait）
static const int DISP_PREV_H  = 352;   // 預覽區高（含狀態列32 + 圖像區320）
static const int GRID_H       = 360;   // 按鈕網格高
static const int BOT_H        = 88;    // 底部控制列高
static const int GRID_COLS    = 3;
static const int GRID_ROWS    = 3;
static const int CELL_W       = DISP_W / GRID_COLS;   // 160
static const int CELL_H       = GRID_H / GRID_ROWS;   // 120
// 移除: SB_W, SB_FULL_H, DISP_PREV_W
```

---

## 各區域說明

### 狀態列（y: 0–32）
- 背景 `#1a1a1a`
- 左：`LUX VISIONS` logo 文字（小）
- 右：曝光值顯示（e.g. `2500us`）

### 預覽區（y: 32–352）
- 背景 `#1e1e2e`
- 圓形遮罩：center=(240, 192)，radius=140px
  - 相機影像縮放至 280×280（先 fit 在 280×280 再套圓形遮罩）
  - 遮罩外填充 `#1e1e2e`
- 下方標籤列（y: 320–352）：
  - 中央顯示當前模式名稱（`LIVE` / `AGTRON` / `SEGMENT` 等）
  - 若有 Agtron 結果：右側顯示數值（e.g. `76.3`）
  - 若有豆數：左側顯示（e.g. `51 beans`）

### 按鈕網格（y: 352–712）
- 背景 `#1a1a1a`
- 3×3 格，每格 160×120px
- 每個按鈕：
  - 圖示文字（大字 emoji 或 ASCII，置中，y+50）
  - 標籤文字（小字，置中，y+85）
  - 選中狀態：填充 `#3a3a5c`，邊框 `#7a7aff`
  - 未選中：填充 `#2a2a3c`，邊框 `#3a3a4c`
  - 圓角矩形（radius=12px）

**按鈕配置（row, col 從 0 開始）：**

| row | col | 標籤 | 圖示字 | BtnTag |
|-----|-----|------|--------|--------|
| 0 | 0 | CAPTURE | CAM | FULL_ANALYSIS（已存在）|
| 0 | 1 | AGTRON | AGT | AGTRON_RUN（已存在）|
| 0 | 2 | SEGMENT | SEG | SEG_SEGMENT（已存在）|
| 1 | 0 | MOLD | MLD | MOLD_DETECT（已存在）|
| 1 | 1 | SPECTRUM | SPC | SPEC_CAPTURE（已存在）|
| 1 | 2 | UV SCAN | UV | UV_SCAN（**新增 BtnTag**）|
| 2 | 0 | ROI | ROI | AGTRON_ROI_SETUP（已存在）|
| 2 | 1 | WHITE REF | WHT | WHITE_CAPTURE（已存在）|
| 2 | 2 | QUIT | END | QUIT（已存在）|

### 底部控制列（y: 712–800）
- 背景 `#111118`
- 左側：`◀ EXP ▶` 曝光增減按鈕（各 80×50px）
- 中央：狀態訊息（`g_app.statusMsg`，最多 2 行）
- 右側：STOP 按鈕（如果有任務進行中）

---

## 觸控事件對應

```
觸控 y < 352             → 預覽區點擊（ROI 設定用）
觸控 y ∈ [352, 712)      → 按鈕網格，計算 col=(x/160), row=((y-352)/120)
觸控 y >= 712            → 底部控制列
```

相機座標映射（預覽區內）：
```
cam_x = touch_x * 1600 / DISP_W           // 480 → 1600
cam_y = (touch_y - 32) * 1200 / 288       // 預覽圖像區 288px → 1200
```

---

## 程式碼架構改動

| 改動 | 說明 |
|------|------|
| 常數 | 如上 6 個新常數，移除 SB_W/SB_FULL_H/DISP_PREV_W |
| `drawSidebar()` | **刪除**，替換為 `drawPortraitUI(AppState&) → cv::Mat(DISP_H, DISP_W)` |
| 合成 | `hconcat(preview, sb)` → 直接 preview 和 grid 都畫在同一張 480×800 canvas |
| 觸控 | `onMouse()` 重寫判斷區域邏輯 |
| 捲軸 | 移除，按鈕固定 9 格（重要功能都在一頁內）|
| 預覽縮放 | 相機 1600×1200 → 280×280（等比裁切為正方形後套圓遮罩）|

---

## 色票（Apple Dark 延續）

| 用途 | 顏色 |
|------|------|
| 主背景 | `#1a1a1a` (26,26,26) |
| 預覽背景 | `#1e1e2e` (30,30,46) |
| 按鈕未選中 | `#2a2a3c` (42,42,60) |
| 按鈕選中 | `#3a3a5c` (58,58,92) |
| 選中邊框 | `#7a7aff` (122,122,255) |
| 底部列背景 | `#111118` (17,17,24) |
| 文字主色 | `#e8e8e8` (232,232,232) |
| 文字副色 | `#8a8a9a` (138,138,154) |
| 強調色 | `#7a7aff` (122,122,255) |
