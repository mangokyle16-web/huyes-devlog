# 提案 09：YOLOX-tiny 升級為「計數 + 即時流量統計」

> 由 Mac Mini Claude Code 在 Kyle 休息時自主思考產生（2026-06-12 凌晨）

---

## 背景

2026-06-12 成功驗證 YOLOX-tiny 在 Pi5 Hailo-8 INT8 精確偵測（9 顆 / 誤差 ≤4px）。
這解決了困擾多天的 YOLOv8n DFL INT8 精度問題。

## 提案

從「能偵測」升級到「真正有用的計數系統」：

**BeanTracker** 跨幀追蹤每顆豆子，統計：
- 每分鐘通過豆數（throughput）
- 每批次豆數（per session）
- 移動平均速度（輸送帶速度估算）

## 技術方案

```python
class BeanTracker:
    def __init__(self, max_age=5, min_hits=3):
        self.tracks = []

    def update(self, detections: List[dict]) -> int:
        """
        輸入：當前幀 YOLOX 偵測結果
        輸出：這一幀「新離開視野」的豆子數（計入計數器）
        """
        # IOU-based matching (或 centroid distance)
        # 超過 max_age 幀沒有配對到 → 離開視野 → 計數 +1
```

## 前置條件

- YOLOX-tiny HEF 穩定部署到 Pi5 ✓（2026-06-12 完成）
- conf 閾值調到 0.45 去除假陽性

## 效益

- 產品核心功能：豆子流量監控
- Siamese 瑕疵偵測的必要前置（知道「這是哪顆豆」）
- 不需要額外標注，直接在 YOLOX 上加追蹤邏輯

## 實作估計

- 撰寫 BeanTracker：~2 小時
- 整合到 Pi5 capture pipeline：~1 小時
- 測試：30 分鐘

---

*前置條件：提案 A 依賴 YOLOX-tiny 穩定部署（2026-06-12 完成）*
