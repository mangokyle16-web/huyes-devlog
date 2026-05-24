# 多光譜咖啡豆黴菌偵測可行性實驗設計

**日期：** 2026-05-25  
**目標：** 以 CM020D FPI 相機驗證多光譜方法可偵測咖啡豆黴菌，建立後續 OPTIC-BEAN-SORTER 整合的理論與實驗基礎

---

## 文獻依據

| 論文 | 方法 | 與本實驗的關係 |
|------|------|---------------|
| *Rapid and accurate classification of Aspergillus ochraceous in Robusta green coffee bean* (Food Control, 2022) | NIR 光譜 + SVM，準確率 0.96 | 直接確認 NIR 波段（850/930nm）可分類咖啡豆黴菌 |
| *Real-time defect inspection of green coffee beans using NIR snapshot hyperspectral imaging* (Computers and Electronics in Agriculture, 2022) | NIR 快照多光譜 + 深度學習 | 與 CM020D FPI 架構相同，分類「moldy」豆 |
| *Fluorescence spectroscopy enhancing aflatoxin detection in solid food products* (SPIE, 2024) | 365nm 激發，380–530nm 發射（峰值 420nm） | 確認 uv_mold_scan.py 的 410–490nm 偵測窗口有效 |
| *Aflatoxin contaminated degree detection by hyperspectral data using band index* (Food and Chemical Toxicology, 2020) | 365nm UV + 33 波段 band index + SVM | UV 照射下多波段比值可量化污染程度 |
| *Detection of Insect Damage in Green Coffee Beans Using VIS-NIR Hyperspectral Imaging* (Remote Sensing, 2020) | VIS-NIR 400–1000nm，準確率 95% | 黴菌與蟲害有相似 NIR 反射率特徵 |

**三種偵測機制均有文獻支撐：**
- UV 螢光（Aflatoxin）：365nm 激發 → 410–490nm 發射
- VIS 反射率異常（黴菌色素）：350–700nm
- NIR 結構損傷：850–930nm

---

## 實驗策略：雙模態交叉驗證法

樣本類型：D 類（外觀懷疑發霉但尚未確認）

兩路信號同時測量，互相交叉驗證，降低假陽性：

```
同一批豆子 → 白光 FPI 掃描 → Mahalanobis 距離（全波段異常）
           → UV 365nm 暗場 → fl_norm（螢光強度，歸一化）
           → 二維散點圖 → 雙高者標記 SUSPECT
           → 48h 觀察 → 確認 Ground Truth
```

---

## 硬體配置

**拍攝序列（豆子全程不移動）：**

1. 白光開、UV 關 → CM020D FPI 全波段掃描（2500us）
2. 白光關、UV 365nm 開、遮光盒蓋上 → UV 拍攝（5000us）
3. 所有光關、遮光盒蓋上 → 暗場（dark subtraction 用，5000us）

**現有設備：**
- 相機：CM020D + FPI 可調濾光（350–930nm）
- UV 光源：365nm UV LED，已整合至 uv_mold_scan.py 流程
- 遮光：紙箱或遮光布（現有）
- 豆碟：DiFluid 6cm 圓盤

---

## 軟體架構

新建 `mold_experiment.py` 作為主控腳本，**不修改現有腳本**，只 import 現有函式：

```
mold_experiment.py
    ├─ Step 1：白光 FPI 掃描
    │   └─ capture_one (2500us) → spec_fingerprint → Mahalanobis 距離
    │      （從 mold_detection.py 抽出計算函式）
    │
    ├─ Step 2：UV 螢光掃描
    │   └─ import uv_mold_scan: compute_fluorescence, compute_fl_score, flag_suspects
    │      capture UV-on (5000us) → capture dark (5000us) → fl_norm
    │
    └─ Step 3：交叉分析輸出
        ├─ 散點圖：X = mahalanobis_dist，Y = fl_norm，可疑豆標紅
        ├─ 疊加標注圖：原始灰階圖上標出每顆豆的 suspect_level
        └─ report.csv：bean_id, mahal, fl_norm, suspect_level (LOW/MID/HIGH)
```

**suspect_level 判定：**
- HIGH：mahal > μ+1.5σ **且** fl_norm > μ+1.5σ
- MID：任一指標超閾值
- LOW：兩者均在正常範圍

---

## Ground Truth 與成功標準

**確認流程：**
1. 分離所有 suspect_level = HIGH 的豆子
2. 放置 48 小時，觀察是否出現肉眼可見菌落
3. 記錄於 `experiment_log.md`（照片 + 結果）

**第一次實驗的成功門檻（可行性層次，非效能層次）：**

| 指標 | 門檻 |
|------|------|
| 程式跑完三步 + 分析 | 必要條件 |
| 散點圖有聚類或離群點 | 初步信號存在 |
| 48h 後至少 1 顆 HIGH 豆出現菌落 | 方法有辨識力 |

**失敗診斷路線：**
- 散點圖均勻無聚類 → 白光 FPI 信噪比不足，退回純 UV 螢光路線
- 48h 無菌落 → 樣本無活性黴菌，啟動方案 C（主動培養資料集）

---

## 方案 C：主動培養資料集（同步啟動）

與主實驗並行進行，不阻塞主實驗：

1. 取 30–50 顆生豆，一半置於高濕密封袋（溼布 + 35°C），一半正常儲存作對照
2. 每隔 24 小時拍攝一次（三步流程）
3. 建立 Day 0 / 1 / 2 / 3 / 5 時間序列光譜資料庫
4. 資料充足後訓練 SVM / k-NN 分類器，進入 OPTIC-BEAN-SORTER 整合

---

## 後續整合方向

本實驗成功後，進入 OPTIC-BEAN-SORTER 的黴菌偵測模組：
- 單顆豆靜態拍攝（stop-and-release 機構）
- 白光 + UV 雙模態拍攝（各 ~300ms）
- 即時 suspect_level 判定 → 轉向閘分流
