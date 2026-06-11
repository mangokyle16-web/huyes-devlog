# INT8 精度比較測試結果

**測試圖片：** 20260609-001 batch，frame_000030.jpg（包含 9 顆咖啡豆）  
**測試日期：** 2026-06-11  
**硬體：** Raspberry Pi 5 + Hailo-8 NPU

## 方法與結果

| 編號 | 方法 | Pi5 偵測數 | FP32 基準 | 備註 |
|------|------|-----------|---------|------|
| 0 | Mac FP32（基準）| 9 | — | 9 顆，位置準確 |
| 1 | DFC 3.33.1 + recal | 27 | 9 | 框過多，位置偏移 |
| 2 | 全量 calibration 513 張 | 27 | 9 | 與 #1 相同（同底層模型）|
| 3 | QAT v1（動態 scale 30 epochs）| 32 | 9 | 稍改善但仍過多 |
| 4 | QAT v2（固定 scale 50 epochs）| 41 | 9 | 更差 |
| 5 | REG_MAX=4（16ch DFL）| 21 | 9 | 減少但位置仍不正確 |

## 各方法具體改動說明

**方法 1 — DFC 3.33.1 + recalibration**  
將 Hailo 編譯器從 DFC 3.28 升級到 3.33.1，並重新用 513 張圖片做 calibration（原本只有 40 張）。升級後的編譯器對某些 op 有改善的量化策略，但 YOLOv8n DFL head 的 64 通道輸出仍維持 INT8，精度損失根因未消除。結果：框數量從 24 降到約 27，但位置仍嚴重偏移。

**方法 2 — 全量 calibration 513 張**  
在方法 1 的基礎上，將 calibration 圖片增加到全部 513 張真實採集圖（涵蓋不同豆量、不同位置）。更多校正資料讓 Hailo DFC 估算的 INT8 activation scale 更貼近真實分布，但底層模型架構與方法 1 相同，最終偵測數與框的位置跟方法 1 幾乎完全一致，改善幅度可忽略。

**方法 3 — QAT v1（動態 scale，30 epochs）**  
在訓練過程中對 YOLOv8n 的 cv2 DFL head 輸出注入 fake INT8 量化噪聲（每次 forward 動態計算 scale = max_abs/127），讓模型學會在 fake 量化條件下輸出正確 bbox。訓練 30 epochs，mAP50=99.4%。問題在於動態 scale 跟 Hailo 部署時的固定 scale 不一致，模型學習到的補償與實際量化誤差不完全匹配。結果：框數量增加到 32，稍有改善但更不穩定。

**方法 4 — QAT v2（固定 scale，50 epochs）**  
改良 QAT 策略：先用 120 張圖跑 EMA calibration 確定固定 scale（cv2_0=0.244, cv2_1=0.236, cv2_2=0.239），訓練期間全程用固定 scale 做 fake quant，模擬 Hailo 推論的實際條件。訓練 50 epochs，mAP50=99.4%。理論上比 v1 更接近真實量化條件，但實際結果反而更差（41 框），可能因為 EMA 估算的 scale 與 DFC 內部的 scale 計算方式仍有差異。

**方法 5 — REG_MAX=4（16ch DFL head）**  
從根本改變模型架構：YOLOv8n 預設 REG_MAX=16，每個 bbox 座標用 16 個 softmax bin 描述，INT8 量化後每個 bin 只有 16 levels 精度。改為 REG_MAX=4（每座標 4 個 bin），每個 bin 有 64 levels 精度（提升 4 倍），理論上大幅降低量化誤差。實作時需繼承 DetectionTrainer 並 override get_model()，確保 Ultralytics 不會把修改覆蓋回 reg_max=16。訓練 50 epochs mAP50=99.4%，HEF 編譯後 cv2 輸出確認為 16ch。但結果顯示框數仍有 21 個，位置集中在影像中央偏右區域，與 FP32 的 9 顆完全不符。

## 結論

所有方法都無法讓 Pi5 Hailo-8 INT8 推論結果接近 Mac FP32（9 顆準確）。  
根據 Codex 分析，Hailo 官方 YOLOv8n 的 float→hardware mAP 差距僅 0.6%，  
問題可能在於我們的 training domain 跟 Hailo DFC calibration pipeline 的差異。

**下一步選項：**
- 換用 YOLOX-tiny（非 DFL，Hailo model zoo 原生支援）
- 使用 CenterNet（適合圓形物件，直接 center/size 回歸）

## 圖片檔案

- `0_mac_fp32.jpg` — 綠色框，FP32 基準
- `1_dfc331_recal.jpg` — 橘色框
- `2_fullcalib_513.jpg` — 黃色框  
- `3_qat_v1.jpg` — 藍色框
- `4_qat_v2.jpg` — 紫色框
- `5_regmax4.jpg` — 紅色框
- `grid_all_methods.jpg` — 6 格綜合比較圖
