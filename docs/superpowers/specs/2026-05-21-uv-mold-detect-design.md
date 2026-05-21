# UV 365nm 黴菌螢光偵測驗證腳本設計

**日期**: 2026-05-21  
**狀態**: 已核准，待實作  
**目標**: 驗證 365nm UV LED + QS 多光譜相機能否偵測熟豆（烘焙後）的黴菌螢光訊號

---

## 背景與動機

現有黴菌偵測腳本（`mold_detection.py` 等）使用白光反射率光譜異常分析。本實驗採用不同原理：
**螢光激發**——黴菌代謝物（尤其黃麴毒素 Aflatoxin B1）在 365nm 照射下於 ~425–450nm 發出螢光。

本腳本為驗證用獨立 Python 腳本，不整合進 main.cpp app。

**樣品**：烘焙後熟豆，外觀輕微異常、可疑但未確認發霉。

---

## 方案選擇

| 方案 | 說明 | 選擇 |
|------|------|------|
| A. 單次 UV 拍攝 + 比值 | 一次拍攝，410-490nm / 350nm | 棄用（無暗場基準） |
| **B. UV − 暗場差分** | 兩次拍攝相減，純螢光訊號 | **採用** |
| C. UV + 白光雙模 | 三模對比，資訊最多 | 棄用（驗證期過複雜） |

---

## 腳本：`uv_mold_scan.py`

### 互動流程（3 次拍攝）

```
步驟 1 ─ 白光 ON
  提示：「白光開著，按 Enter 拍分割參考圖...」
  → capture_one → ref.qs → qs_to_png → ref_gray.png
  → fast_seg 分割 → beans_rois.json + beans_labelmap.png

步驟 2 ─ UV ON（白光 OFF）
  提示：「關掉白光，開 365nm UV LED，按 Enter...」
  → capture_one → uv_on.qs（曝光 5000us 預設）
  → spec_fingerprint → uv_on_spec.csv

步驟 3 ─ 全暗
  提示：「關掉所有光源，按 Enter...」
  → capture_one → dark.qs（同曝光）
  → spec_fingerprint → dark_spec.csv

步驟 4 ─ 分析與輸出（自動）
```

### 分析邏輯

```python
# 暗場相減，得純螢光訊號
fl[bean][nm] = uv_on[bean][nm] - dark[bean][nm]

# 螢光分數：410–490nm 為黃麴毒素發射帶
fl_score[bean] = mean(fl[bean][410, 430, 450, 470, 490])

# 正規化：除以 UV 反射帶（350nm），補償各豆照度不均
fl_norm[bean] = fl_score[bean] / (uv_on[bean][350] + 1e-6)

# 判斷門檻：超過 mean + 1.5×std 標記為 SUSPECT
```

### 輸出檔案

| 檔案 | 說明 |
|------|------|
| `uv_mold_labeled.png` | ref_gray 底圖 + 每顆豆彩色圓圈（綠→黃→紅）＋ fl_norm 數值 |
| `uv_spectrum_plot.png` | 前 3 名可疑豆 vs 中位正常豆的螢光光譜對比（410–490nm 區間標色） |
| `uv_report.csv` | `bean_id, fl_score, fl_norm, flag` |

### CLI 參數

```bash
python3 uv_mold_scan.py [--n-beans N] [--exposure-uv US]
# --n-beans     預期豆數（印提示用）
# --exposure-uv UV 拍攝曝光，預設 5000us
```

---

## 依賴

| 工具 | 路徑 |
|------|------|
| capture_one | `/home/kyle/KyleClaude/multispectral_demo/build/capture_one` |
| qs_to_png | `/home/kyle/KyleClaude/multispectral_demo/build/qs_to_png` |
| spec_fingerprint | `/home/kyle/KyleClaude/multispectral_demo/build/spec_fingerprint` |
| fast_seg_agtron.py | `/home/kyle/KyleClaude/fast_seg_agtron.py`（分割邏輯參考） |
| camera_new.qsbs | `/home/kyle/KyleClaude/camera_new.qsbs` |
| db_std.qsdb | `/home/kyle/KyleClaude/db_std.qsdb` |
| Python libs | numpy, cv2, matplotlib（已安裝） |

---

## 已知限制與風險

- 烘焙高溫（200–230°C）可能降解約 70% 的黃麴毒素 B1，若樣品毒素殘留量低，螢光訊號可能微弱
- 旋轉豆（熟豆表面不均勻）會造成豆內螢光分布不均，per-bean 平均可能稀釋訊號
- 365nm LED 功率與照射角度會影響訊號強度，首次拍攝建議先確認曝光是否合適（非飽和）
- 樣品為可疑豆（未確認陽性），若結果無明顯差異，需取得確認發霉樣品再評估

---

## 成功標準

1. 可疑豆的 `fl_norm` 分布與其他豆有可見差異（即使只有 1–2 顆）
2. `uv_spectrum_plot.png` 顯示可疑豆在 410–490nm 有相對較高的螢光峰
3. 腳本從頭到尾可無錯誤完成（三次拍攝 → 輸出三個檔案）
