# 方案 A：raw mosaic 快速灰階(fast-gray)— 取代慢速 qsToGray

> 目的:把偵測 fps 從 2-3 拉到 10-13,減少掉幀,提升輸送帶豆子計數準確率

## 背景:為什麼需要

豆子計數在 2-3 fps 下嚴重受限:
- 偵測瓶頸是廠商 SDK 的 `qsToGray`(多光譜 demosaic ~300ms/幀,單執行緒純 C++ 黑盒,無法改)
- 相機產 669 幀但偵測只跑 318 幀(掉幀 53%)
- 豆子每步移動 140-160px = 一個框寬 → 追蹤窗口易錯過 → 計數 399 真值只到 330(83%)

## 解法:跳過 qsToGray,直接處理 raw mosaic

CM020D 是 **3×3 mosaic(9 波段)** snapshot 多光譜相機。
不做完整光譜反演,直接把每個 3×3 tile 的 9 個值平均成一個灰階像素,
即得到「全波段平均」的灰階圖 —— 對 YOLOX 偵測足夠,且快 100 倍。

### 實測確認的參數

| 項目 | 值 | 確認方式 |
|------|-----|---------|
| raw 格式 | `LLSQ` + 8 byte 前綴 + 1600×1200 16-bit LE | hexdump + 檔案大小 |
| 位元深度 | 10-bit(值 67-1023)| raw max=1023 |
| mosaic 週期 | **3×3(9 band)** | 水平/垂直自相關都在 lag 3,6,9 強峰值 |
| 快速灰階尺寸 | 533×400(1600/3, 1200/3)| block-average |
| 處理時間 | ~3ms(vs qsToGray 300ms)| OpenMP 4 核 |
| 預估 fps | 10-13 | |

## fast-gray vs qsToGray 差異說明

兩者都產生灰階,但原理不同:

| | qsToGray(廠商)| fast-gray N=3(方案A)|
|---|---|---|
| **原理** | 完整多光譜 demosaic + 校正重建,加權合成灰階 | 3×3 tile 的 9 個原始 mosaic 值直接平均 |
| **校正** | 有(暗電流/增益/波段校正,用 .qsbs 校正檔)| 無,只做 per-frame 1-99% 百分位對比拉伸 |
| **解析度** | 原生 1600×1200 | 原生 533×400(上採樣回 1600×1200 保持座標)|
| **耗時** | ~300ms(單執行緒)| ~3ms(OpenMP 4 核)|
| **影像外觀** | 較平滑、校正後的灰階 | block-average,略帶 mosaic 紋理(放大可見),背景稍暗 |
| **豆子偵測** | 17 顆(同幀)| 18 顆(同幀)|

**關鍵結論:**
- 對「豆子偵測」這個任務,兩者**等效**(YOLOX 框的位置、數量幾乎相同)
- fast-gray 因為沒有光譜校正,背景稍暗、亮區有輕微 mosaic 紋理,但**不影響豆子偵測**
- **現有 YOLOX 模型不用重訓**(訓練用 qsToGray,推論用 fast-gray 直接通用)
- **不用重編 HEF**

> 注意:fast-gray 是「全波段平均」的灰階,丟失了光譜資訊。
> 若未來要做「豆子瑕疵的光譜分析」,仍需用原始 .qs / qsToQab 走光譜路徑。
> fast-gray 只用於「即時偵測 + 計數」的快速路徑;光譜採集另存原始 .qs 不受影響。

## 同幀驗證

`samefr_qstogray_vs_fastgray.jpg`:同一個 frame_000130.qs,左 qsToGray(17顆)右 fast-gray(18顆),
豆子位置完全一致,影像視覺幾乎相同。

`fastgray_detection.jpg`:fast-gray 上 YOLOX 偵測 18 顆,框緊貼豆子。

## 預期效益

| | 改善前 | 方案 A 後 |
|---|---|---|
| 偵測 fps | 2-3 | 10-13 |
| 掉幀率 | 53% | 大幅降低 |
| 豆子每步移動 | 140-160px(一個框寬)| 35-40px |
| 追蹤可靠度 | 差(近零 IOU)| 大幅改善 |
| 計數準確率 | 83%(399→330)| 預期顯著提升 |

## 實作

- `spectral_capture/capture/preview_daemon.cpp`:`fastGrayFromRaw()` + 上採樣 + 寫 preview.ppm
- `spectral_capture/capture/Makefile`:加 `-fopenmp -O3 -march=armv8.2-a+simd`
- `spectral_capture/launch_ui.sh`:preview_daemon fps 5 → 13
- 由 OpenAI Codex 實作
