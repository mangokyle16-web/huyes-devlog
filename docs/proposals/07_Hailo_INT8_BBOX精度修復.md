# 提案 07：Hailo-8 INT8 BBox 精度修復全紀錄 — REG_MAX=4 治本方案

> 由 Mac Mini Claude Code 在 Kyle 休息時自主思考並實作（2026-06-10 深夜）

---

## 問題根因

YOLOv8n DFL head 的 cv2 分支輸出 **64 通道**（4 座標 × 16 bins）。  
Hailo-8 INT8 量化時，256 個等級分攤到 16 個 bin → 每個 bin 只有 16 levels 精度  
→ softmax 分布被截斷 → bbox 位置嚴重偏移。

## 修復歷程

| 版本 | 方法 | 結果 |
|------|------|------|
| v1 HEF（DFC 3.28）| 基本編譯 | 24 boxes，嚴重錯位 |
| v2 HEF（DFC 3.28）| 513 張重新 calibration | 12 boxes，仍偏 |
| Soft-NMS | Gaussian decay σ=0.5 | 不再爆框 |
| DFC 3.33.1 | 升級編譯器 | 小改善 |
| QAT v1 | 動態 scale fake quant 30 epochs | 10 boxes，明顯改善但不夠 |
| QAT v2 | 固定 scale 50 epochs | 18 boxes，更差 |
| **REG_MAX=4**（進行中）| cv2 從 64ch → 16ch，每 bin 64 levels | 訓練中（2026-06-10）|

## REG_MAX=4 技術細節

```
DFL bins: 16 → 4
cv2 輸出: 64ch → 16ch  
每個 bin INT8 精度: 16 levels → 64 levels（提升 4 倍）
```

**關鍵實作問題：** Ultralytics `DetectionTrainer.setup_model()` 固定從 YAML 重建架構，  
in-memory 修改會被覆蓋。

**解法（由 OpenAI Codex 分析並實作）：** 繼承 `DetectionTrainer`，override `get_model()`，  
在 `DetectionModel(yaml)` 建立後立刻呼叫 `force_regmax4()` 替換 cv2 head，  
再載入 backbone weights。

```python
class RegMax4DetectionTrainer(DetectionTrainer):
    def get_model(self, cfg=None, weights=None, verbose=True):
        model = DetectionModel(cfg, nc=self.data["nc"], ...)
        model = force_regmax4(model)   # cv2 64ch→16ch
        if weights:
            model.load(weights)
        return model
```

## 三點精度比較計劃

訓練完成後，對同一張測試圖執行：
1. **Mac PyTorch FP32**：ground truth
2. **Hailo DFC 模擬 INT8**：在 Mac 上 emulate
3. **Pi5 Hailo-8 實機**：真實硬體輸出

腳本：`~/Desktop/compare_three_outputs.py`

## Codex 分析：LocateAnything 可行性

> 2026-06-10，由 OpenAI Codex（web search）分析 NVIDIA 新發布的 LocateAnything

**結論：不可行，不要替換 YOLO。**

- LocateAnything 是 VLM grounding 模型，不是嵌入式偵測器
- 無 Hailo-8 export 路徑、無 checkpoint、無 benchmark
- **重要發現：** Hailo 官方數據顯示 YOLOv8n float mAP 37.0 → hardware mAP 36.4，  
  差距只有 0.6%，代表問題在 export/calibration，不在模型本身

**若真的要換架構，Codex 推薦：**  
YOLOX-tiny（Hailo 原生支援，非 DFL，742 FPS）  
CenterNet（center/size 格式，對圓形豆子概念最合適）

---

*訓練腳本：`~/Desktop/train_regmax4_v3.py`（由 OpenAI Codex 實作）*  
*比較腳本：`~/Desktop/compare_three_outputs.py`*
