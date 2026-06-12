# YOLOX-tiny Hailo-8 部署開發紀錄（2026-06-11 ~ 06-12）

## 背景：為什麼換 YOLOX

YOLOv8n 在 Hailo-8 INT8 量化後 bbox 完全錯位（詳見 `docs/int8_comparison/`）。
根因診斷確認：YOLOv8n 的 **DFL（Distribution Focal Loss）head** 需要對 16 個 bin 做
softmax，INT8 量化讓分布嚴重失真。5 種修復方法（DFC升級/全量calibration/QAT v1/v2/
REG_MAX=4）全部失敗。

**YOLOX 使用直接回歸（4 個值 x/y/w/h），不依賴 DFL，天然 INT8 友好。**

## 訓練

- 模型：YOLOX-tiny（depth=0.33, width=0.375, act=lrelu）
- 輸入：416×416（Hailo-8 標準尺寸）
- 資料：3468 張訓練圖（YOLO→COCO 轉換），1 class "bean"
- 環境：Mac M4 Pro MPS（YOLOX 原生 CUDA-only，做了 6 處 MPS patch）
- 結果：**Best AP@50:95 = 95.01%，AP@50 = 98.9%**（50 epochs）

## HEF 編譯（DFC 3.33.1）

YOLOX ONNX 與 DFC 相容性需要 4 處 patch：
1. opset 18 → 11
2. Resize op 移除 `keep_aspect_ratio_policy`/`antialias`（opset18 專有屬性）
3. Resize roi 空字串輸入 → 補空 tensor initializer
4. Conv 節點補 `kernel_shape` 屬性（從 weight shape 推算）
5. 提取 3 個 raw head 輸出（cat_14/15/16，6ch × 3 尺寸），切掉 decode/concat

最終 HEF：`yolox_tiny_beans_final.hef`（9.76 MB）

## Pi5 INT8 部署 Bug 修正

首次 Pi5 批次測試,偵測數遠少於 Mac FP32。查出兩個 detector 端 bug：

### Bug 1：預處理拉伸失真
`cv2.resize(img, (416,416))` 把 1600×1200（4:3）硬拉成 416×416（1:1），
扭曲豆子形狀。YOLOX 訓練用的是 letterbox（保持比例 + 補邊 114）。
→ 改為 letterbox 預處理。

### Bug 2：亮度過濾誤殺
`MAX_BRIGHTNESS=200` 是當初為 YOLOv8n 擋 IR LED 反光設計的，
把過曝的亮豆子整顆當反光濾掉（frame_805 從 8 顆 → 0 顆）。
→ 移除該過濾。YOLOX 已能自行區分豆子與 IR 反光點。

## 修正前後對比（同一批 8 張圖）

| Frame | Mac FP32 | Pi5 INT8 修正前 | Pi5 INT8 修正後 |
|-------|----------|----------------|----------------|
| 088 | 29 | 19 | **29** ✓ |
| 099 | 26 | 14 | **26** ✓ |
| 109 | 30 | 14 | **30** ✓ |
| 121 | 21 | 8 | **21** ✓ |
| 130 | 29 | 23 | **29** ✓ |
| 805 | 8 | **0** | **8** ✓ |
| 1138 | 30 | 14 | **30** ✓ |
| 1141 | 26 | 13 | 27 (~) |

修正後 Pi5 INT8 ≈ Mac FP32，再次證明 **YOLOX INT8 在 Hailo-8 上幾乎無損**。

## 圖片

- `before_fix/` — 修正前 8 張（stretch resize + 亮度過濾）
- `after_fix/` — 修正後 8 張（letterbox + 無亮度過濾）
- `compare_frame_000805.jpg` — 最戲劇性對比：0 → 8 顆（左修前/右修後）
- `compare_frame_000109.jpg` — 密集場景：14 → 30 顆
- `before_after_grid.jpg` — 4 張並排總覽（上修前/下修後）

## 結論

YOLOX-tiny 取代 YOLOv8n 完全解決 Hailo-8 INT8 bbox 精度問題。
即時偵測已整合進 Pi5 採集 UI（`preview_display.py` + `yolo_bean_detector.py`）。
