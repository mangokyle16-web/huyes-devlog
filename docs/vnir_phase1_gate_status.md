# 提案15 VNIR Phase 1 — Gate 進度 (2026-06-14)

## 已釐清:「9 band vs 10 band」不是矛盾

- **實體 mosaic**:CM020D raw 是 3×3 = **9** 個濾光位置(本機 + Pi5 三次獨立實測:tile-variance N=3 ratio≈3.7、autocorrelation lag 3/6/9)。fast-gray 用的是這層。
- **SDK 重建 band**:`qsToQsi`(Fabry–Perot specinv)把 9-cell mosaic 重建成連續光譜,再依要求窗寬重新取樣成任意 band 數(SDK 最小 20nm 窗,須對齊 `specBegin`)。
- **結論**:band 數是軟體取樣選擇,與實體 9-cell 無衝突。提案的「60nm × 10 band @ 350–950nm」只是其中一種合法取樣。證據在 Pi5 已開發的 `multispectral_demo/spec_fingerprint.cpp`(STEP=20、動態生成 bandArr、註解 "Fabry-Perot reconstruction needs full spectral context")。

## 對 Phase 1 的影響

1. 純 Python 的 **5×2 de-tile fallback 無效**(週期錯 + 概念錯:光譜 band 必須經 specinv 重建,不能拆 raw 格子)。只能當 pipeline smoke test,**不可產生校正資料**。
2. 唯一正確抽取路徑 = **SDK 路徑**(`qsToQsi`+`qsiToGray`),Pi5 已有可用實作。`qs_to_bands.cpp` 應對齊 demo,並補:**白參考正規化** + **band 起點對齊 `specBegin+N×STEP`**。
3. Gate 必須在 **Pi5(linux-arm64)** 跑,Mac 跑不了 SDK。

## Gate 執行狀態

- **已派工給 Pi5 Claude**(2026-06-14,60nm 切法):複製 `spec_fingerprint.cpp`→`spec_gate.cpp`(STEP=60),用 `camera_new.qsbs`+`db_std.qsdb`,跑白板 + `20260607-001/frame_000085.qs`。
- 待回報:實際 `specBegin/specEnd`、60nm 實得 band 數與範圍、`qsToQsi` 是否接受/重新對齊、各 band mean/std 是否可區分、band 影像是否看得出豆子、**GO/NO-GO**。
- 報告將輸出至 Pi5 `docs/vnir_phase1_gate_report.md`。

## 待辦 (task 2)

- 清理散落重複檔:`spectral_capture/pipeline/band_extract.py`、`spectral_capture/tools/calib_logger.py`(canonical 在 `spectral_capture/spectral/`,測試也由此 import)。
