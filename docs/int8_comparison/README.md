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
