# 分工架構：Mac Mini（大腦）vs Pi5（執行）

## 原則
- **Mac Mini**：規劃、訓練、分析、程式架構、模型開發
- **Pi5**：採集資料、執行推論、控制硬體、跑 demo app

---

## 專案一：Siamese 多光譜豆子瑕疵偵測

| 任務 | 負責方 | 說明 |
|------|--------|------|
| 採集 10-band 光譜資料 | Pi5 | S鍵觸發，session_watcher.py 自動標記 |
| 匯出 CSV 傳給 Mac | Pi5 | `export_dataset.py` → scp 到 Mac |
| 訓練 Siamese MLP | **Mac Mini** | PyTorch MPS，目標 val_f1 > 0.90 |
| 模型評估 & 調參 | **Mac Mini** | confusion matrix、per-class recall |
| 打包 .pt 模型 | **Mac Mini** | export → 傳回 Pi5 |
| 推論整合到 demo app | Pi5 | 載入 .pt，C++ 呼叫 Python subprocess 或 torchscript |

### 資料流
```
Pi5 採集 → CSV → scp → Mac Mini/KyleClaude/siamese/data/raw/
Mac Mini 訓練 → .pt → scp → Pi5/KyleClaude/models/
```

### CSV 格式（Pi5 負責輸出）
```
bean_id, class, pass, b0, b1, b2, b3, b4, b5, b6, b7, b8, b9
1, good, 1, 0.123, ...
```

---

## 專案二：Agtron 校正（新 SDK 問題）

| 任務 | 負責方 | 說明 |
|------|--------|------|
| 等廠商回覆 band 波長 | - | 待定 |
| 測試 Linux ARM64 SDK Python binding | Pi5 | `ctypes` 載入 `.so`，驗證 per-band AGC 問題 |
| 補充校正資料採集 | Pi5 | 深/淺焙多批次，重跑回歸 |
| 回歸分析 & 公式更新 | **Mac Mini** | Python pandas/scipy，R² > 0.90 目標 |
| 更新 `agtron_analysis.py` | **Mac Mini** | 修正後 scp 回 Pi5 |

---

## 專案三：OPTIC-BEAN-SORTER 機構整合

| 任務 | 負責方 | 說明 |
|------|--------|------|
| GPIO 接線測試（電磁鐵 + IR）| Pi5 | libgpiod，gpiochip4 |
| 3D 列印斜坡滑道 | 實體 | PLA，~180g |
| SortState 狀態機實作 | **Mac Mini** | 設計邏輯 & 程式碼，scp 到 Pi5 編譯 |
| main.cpp 整合 | **Mac Mini** | 新增 SORT 模式，libgpiod 呼叫 |
| 實機測試 | Pi5 | GPIO 實際驅動 |

---

## 專案四：黴菌偵測實驗

| 任務 | 負責方 | 說明 |
|------|--------|------|
| 肉眼確認 bean_26/27 | Pi5 | 看有無菌落 |
| 第二輪拍攝 | Pi5 | `mold_experiment.py` |
| 結果分析 | **Mac Mini** | `mold_analysis.py` 跑在 Mac（或 Pi5 均可）|

---

## 現在的優先順序

1. **[Mac Mini - 立刻開始]** Siamese 訓練環境 + pipeline 實作
2. **[Pi5 - 等同步]** 採集資料腳本 `export_dataset.py`
3. **[Mac Mini - 等資料]** 實際訓練

---
更新時間：2026-06-02
