# Plan A: VNIR empirical density-correction model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 CM020D 的 350-950 nm VNIR 10-band 資訊，建立 batch-level empirical density-correction model，降低「準確計數後用固定 `g_per_bean` 換算重量」造成的系統性偏差。

**Architecture:** 保留現有 `YOLOX-tiny + BeanTracker` 計數流程作為主路徑，新增一條不影響即時偵測的 VNIR feature extraction / calibration / model inference pipeline。模型不做 per-bean 秤重；一筆訓練資料就是一個 batch：`count + aggregate 10-band spectral features + bbox geometry stats + true total weight`，最後輸出 `density_factor`，用 `corrected_weight_g = count * g_per_bean_base * density_factor` 修正批次重量。

**Tech Stack:** Raspberry Pi 5, Hailo-8, CM020D raw `.qs` 1600x1200 16-bit mosaic, `spectral_capture/preview_display.py`, `spectral_capture/control_server.py`, FastAPI, phone cockpit `spectral_capture/ui/index.html`, Python 3, NumPy, pandas, scikit-learn `PLSR`, `HistGradientBoostingRegressor` 或 `GradientBoostingRegressor`, CSV/JSONL calibration dataset。

---

## 0. 背景與設計邊界

現有系統已可用：

- Pi5 + Hailo-8 + CM020D multispectral camera over conveyor。
- Real-time bean counting：`YOLOX-tiny + BeanTracker` dual counting line，已接近 99% 準確度，例如 `403 vs 399`。
- 每顆豆的 bbox 已可取得，live count 已透過 `/dev/shm/count_status.json` 與手機 cockpit 顯示。
- Raw `.qs` frame 是 `1600x1200 16-bit mosaic`。
- `spectral_capture/capture/fast_gray.h` 目前把 mosaic average 成單一 grayscale 給 detector 使用；Plan A 不能破壞這條即時偵測路徑。

真正要修的是重量估算的 **batch-level systematic bias**：

- 現行 `weight_g = count * fixed_g_per_bean` 在 count 很準時仍可能偏掉。
- 單顆豆重量的 random variation 會隨大批次平均掉，relative error 近似 `sigma / sqrt(N)`。
- 大問題是整批豆因 moisture / roast / variety / density 與 calibration batch 不同，導致固定 `g_per_bean` 出現最高約 `+/-8%` 的系統性偏差。

本計劃刻意做 **batch-level model**，不是 per-bean model：

```json
{
  "batch_id": "20260613-001",
  "count": 403,
  "spectral_features": "aggregate 10-band mean/std/ratios across beans",
  "bbox_geometry": "area/aspect/width/height stats across beans",
  "true_weight_g": 61.0
}
```

這代表校正資料只需要每批用 kitchen scale 秤一次總重，精度目標 `+/-1g`，不需要逐顆秤重。

---

## 1. 光譜物理約束與誠實目標

CM020D SDK 已確認提供 10 個 spectral bands，每個約 60 nm window，涵蓋 `350-950 nm`：

| Band | Wavelength window |
|---|---|
| B1 | 350-410 nm |
| B2 | 410-470 nm |
| B3 | 470-530 nm |
| B4 | 530-590 nm |
| B5 | 590-650 nm |
| B6 | 650-710 nm |
| B7 | 710-770 nm |
| B8 | 770-830 nm |
| B9 | 830-890 nm |
| B10 | 890-950 nm |

重要限制：

- 這是 `VNIR`，不是 full-NIR。
- 強 water absorption bands `~1450 nm`、`~1940 nm` 完全在相機範圍外。
- 弱 water overtone `~960-970 nm` 只勉強靠近 B10 的右側邊界；B10 是 moisture-correlated edge feature，不是直接水分光譜量測。
- B1-B6 主要捕捉 roast degree / variety / color，這些是 density 的主要 driver。
- B7-B10 提供 NIR-edge 與 moisture-correlated 資訊，但訊號強度受 illumination、exposure、camera response、bean surface condition 影響。

所以 Plan A 是 **empirical correlation model**：先做 `PLSR` baseline，再嘗試 gradient boosting。合理期望是把系統性偏差從約 `+/-8%` 降到 `+/-3-4%`；不應承諾 load-cell-grade `+/-1-2%`。

---

## 2. 檔案結構與責任

### Create: `spectral_capture/pipeline/vnir_bands.py`

責任：

- 從 raw `.qs` 讀取 `1600x1200 16-bit mosaic` payload。
- 依 CM020D SDK / mosaic map 輸出 10 個 separate bands。
- 不取代 `fast_gray.h`；只供 spectral feature pipeline 使用。
- 提供測試用 API：

```python
def extract_bands_from_qs(qs_path: Path) -> np.ndarray:
    """Return bands with shape (10, H_band, W_band), dtype float32."""
```

### Create: `spectral_capture/pipeline/vnir_features.py`

責任：

- 把 detector bbox 對應到 band coordinate。
- 對每顆豆取 B1-B10 mean / std。
- 聚合成 batch-level features：每個 band 的 mean/std，以及 selected band ratios。
- 計算 bbox geometry stats：area、width、height、aspect ratio 的 mean/std/p10/p50/p90。

### Create: `spectral_capture/calibration/density_dataset.py`

責任：

- 定義 calibration row schema。
- 寫入 append-only JSONL 與 derived CSV。
- 在 batch finalize 時寫 `true_weight_g: null` 的 pending row。
- 提供更新 manual scale label 的 function。

### Create: `spectral_capture/calibration/train_density_model.py`

責任：

- 讀取 calibration dataset。
- 建立 feature matrix。
- 訓練 `PLSR` baseline 與 gradient boosting。
- 用 leave-one-condition-out 或 grouped cross-validation 回報：
  - baseline fixed `g_per_bean` error
  - VNIR-corrected error
  - MAE, MAPE, bias by condition
  - GO/NO-GO recommendation

### Create: `spectral_capture/calibration/density_model.py`

責任：

- 載入已訓練 model artifact。
- 給 live system 呼叫：

```python
def predict_density_factor(features: dict) -> dict:
    """Return {'density_factor': float, 'confidence': str, 'model_version': str}."""
```

### Modify: `spectral_capture/preview_display.py`

責任：

- 在 batch finalize 時，除了既有 `save_batch_json()`，也呼叫 VNIR batch logger。
- 保留 `/dev/shm/count_status.json` live counting，不在 main loop 做昂貴 training。
- 若 band extraction 失敗，仍要正常保存 count batch JSON。

### Modify: `spectral_capture/control_server.py`

責任：

- 新增 manual scale label API。
- 新增 corrected weight status API。
- 提供 calibration dataset 與 model validation summary 給手機 cockpit 顯示。

建議 API：

```text
POST /api/calibration/batches/{batch_id}/weight
GET  /api/calibration/batches?limit=50
GET  /api/weight/estimate?batch_id=...
GET  /api/weight/model
```

### Modify: `spectral_capture/ui/index.html`

責任：

- 在「計數」或新增「重量」區塊顯示：
  - raw count
  - base weight estimate
  - `density_factor`
  - corrected weight estimate
  - model confidence / stale / not calibrated state
- 在最近批次列表提供 `true_weight_g` 手動輸入欄位。

### Tests

- Create: `spectral_capture/tests/test_vnir_bands.py`
- Create: `spectral_capture/tests/test_vnir_features.py`
- Create: `spectral_capture/tests/test_density_dataset.py`
- Create: `spectral_capture/tests/test_density_model.py`
- Modify: `spectral_capture/tests/test_preview_display_batch.py`
- Modify: `spectral_capture/tests/test_control_server.py`

---

## 3. Summary Timeline

| Phase | Duration | Lead | Outcome | Gate |
|---|---:|---|---|---|
| Phase 0: band table confirmed | 0.5d, DONE | both | VNIR wavelength limits known | 無；已完成 |
| Phase 1: 10-band extraction + batch logger | 3-5d | Codex | 每批可產生 pending calibration row | band map / bbox alignment 正確 |
| Phase 2: calibration data collection | 1-2 weeks | user-manual | 30-50 labeled batches | data diversity 決定模型天花板 |
| Phase 3: model training + GO/NO-GO | 3-5d | Codex + both | bias reduction report | VNIR 是否真的降 bias |
| Phase 4: live integration | 3-5d | Codex | phone cockpit 顯示 corrected weight | inference latency / fallback |
| Phase 5: field validation | 1 week | both | 現場 predicted vs scale validation | 是否需要補資料或 pivot |

總時程約 `5-7 weeks`。其中 Phase 2 是 long pole，且是模型上限的主要來源。

---

## Phase 0: Band → Wavelength table confirmed

**Status:** DONE  
**Duration:** 0.5d  
**Lead:** both

### Goal

確認 CM020D 可用 band 與物理限制，避免把 Plan A 誤寫成 direct water spectroscopy。

### Concrete Tasks

- [x] 確認 SDK 提供 10 個 spectral bands。
- [x] 建立 band table：B1-B10 = `350-950 nm`。
- [x] 明確標註 strong water absorption `~1450 nm`、`~1940 nm` out of range。
- [x] 明確標註 B10 只 marginally 接近 weak `~960-970 nm` water overtone。
- [x] 將模型定位為 empirical correlation model，不是 direct moisture spectroscopy。

### Deliverable

本文件的 band table 與 physics caveat。

### Gating Risk

無；已完成。剩餘風險是 Phase 1 的 raw mosaic → band index map 必須實測驗證，不能只靠假設。

---

## Phase 1: Extract 10 separate bands and build batch-level logger

**Duration:** 3-5d  
**Lead:** Codex  
**Support:** user-manual 提供 sample `.qs`、確認 SDK band order / mosaic map、現場跑一次採集

### Goal

從目前被 `fast_gray.h` average 掉的 raw mosaic 中，建立 **separate B1-B10 band extraction**，並在 batch finalize 時產生 calibration dataset row。Phase 1 不訓練模型，只確保每批都能留下可用特徵與之後可填的 scale label。

### Concrete Tasks

- [ ] Create `spectral_capture/pipeline/vnir_bands.py`
  - 實作 `read_qs_payload(path: Path) -> np.ndarray`，讀出 `1600x1200 uint16` raw payload。
  - 實作 `extract_bands_from_qs(path: Path) -> np.ndarray`，輸出 `(10, H_band, W_band)`。
  - 在 docstring 寫清楚 band order：`B1=350-410 ... B10=890-950 nm`。
  - 加入 `validate_band_map(sample_qs)` helper，輸出每個 band 的 mean/std，供現場確認不是全零或錯位。

- [ ] Modify `spectral_capture/capture/fast_gray.h`
  - 不改 `fastGrayFromRaw()` 的既有 detector behavior。
  - 只在 comment 補上：fast-gray 是 detection-only average path，VNIR density correction 使用 Python separate-band extractor。
  - 若要加 C++ helper，必須保留現有 `fast_gray_selftest.cpp` pass。

- [ ] Create `spectral_capture/pipeline/vnir_features.py`
  - 實作 bbox coordinate scaling：從 detector frame coordinate 對應到 band image coordinate。
  - 對每個 bbox 取 B1-B10 mean / std；bbox 邊界要 clamp 到 image bounds。
  - 對 batch 聚合：
    - `B1_mean` ... `B10_mean`
    - `B1_std` ... `B10_std`
    - ratios：`B10_B6_ratio`, `B9_B6_ratio`, `B8_B5_ratio`, `B4_B2_ratio`, `visible_slope_B1_B6`
    - bbox stats：`bbox_area_mean/std/p10/p50/p90`, `bbox_aspect_mean/std`, `bbox_width_mean`, `bbox_height_mean`

- [ ] Create `spectral_capture/calibration/density_dataset.py`
  - Dataset path 建議：
    - JSONL: `spectral_capture/data/calibration/density_batches.jsonl`
    - CSV: `spectral_capture/data/calibration/density_batches.csv`
  - 每 row 欄位固定：

```json
{
  "schema_version": 1,
  "batch_id": "20260613-001",
  "created_at": "2026-06-13T12:00:00+08:00",
  "count": 403,
  "g_per_bean_base": 0.151,
  "base_weight_g": 60.853,
  "true_weight_g": null,
  "density_factor_label": null,
  "spectral": {
    "B1_mean": 0.0,
    "B10_mean": 0.0,
    "B10_B6_ratio": 0.0
  },
  "geometry": {
    "bbox_area_mean": 0.0,
    "bbox_aspect_mean": 0.0
  },
  "meta": {
    "origin": "unknown",
    "process": "washed",
    "roast_level": "medium",
    "bean_type": "roast"
  }
}
```

- [ ] Modify `spectral_capture/preview_display.py`
  - 在現有 batch finalize 附近接入 logger。
  - 建議在 `save_batch_json(batch_id, total_beans, frames, batch_dir=BATCH_DIR)` 後呼叫：

```python
log_density_calibration_batch(
    batch_id=batch_id,
    count=total_beans,
    frames=frames,
    meta=meta,
    g_per_bean_base=current_base_g_per_bean,
)
```

  - 如果 raw `.qs` 或 spectral feature 不可用，row 仍要寫入，但加 `feature_status: "missing_qs"` 或 `feature_status: "extract_failed"`，避免 batch 消失。

- [ ] Modify `spectral_capture/control_server.py`
  - 新增 `POST /api/calibration/batches/{batch_id}/weight`。
  - Request body：

```json
{
  "true_weight_g": 61.0,
  "scale_precision_g": 1.0,
  "note": "fresh medium roast"
}
```

  - 寫入後計算：

```text
density_factor_label = true_weight_g / (count * g_per_bean_base)
```

- [ ] Modify `spectral_capture/ui/index.html`
  - 在最近批次列表增加 `true_weight_g` input。
  - 使用 `POST /api/calibration/batches/{batch_id}/weight` 保存人工秤重。
  - 未填重量時顯示「待標註」，已填時顯示 `scale weight` 與 `density_factor_label`。

- [ ] Add tests
  - `spectral_capture/tests/test_vnir_bands.py`：fake raw payload 可被拆成 10 bands，shape / dtype 正確。
  - `spectral_capture/tests/test_vnir_features.py`：bbox clamp、band mean、ratio feature 沒有 divide-by-zero。
  - `spectral_capture/tests/test_density_dataset.py`：append pending row、update true weight、derived CSV 欄位穩定。
  - `spectral_capture/tests/test_control_server.py`：manual weight API 成功更新 label，缺 batch 回 404 或 structured error。

### Deliverable

一個 append-only calibration dataset pipeline：每批結束後都會產生 pending row；使用者可在手機 cockpit 或 API 填入 kitchen scale 的 `true_weight_g`。

### Gating Risk

最大風險是 raw mosaic 的 band index map / spatial alignment。如果 B1-B10 extraction 對錯位置，後面模型會學到 noise。Phase 1 gate 是：用 sample `.qs` 驗證 10 個 band 都有合理 signal，且 bbox 投影到 band image 後落在豆子位置，不是背景。

---

## Phase 2: Collect 30-50 calibration batches

**Duration:** 1-2 weeks  
**Lead:** user-manual  
**Support:** Codex 協助檢查 dataset completeness script

### Goal

收集足夠多、足夠多樣的 labeled batch data。這是 long pole，也是模型準確度的 ceiling。

### Concrete Tasks

- [ ] 準備 kitchen scale，解析度至少 `1g`，每批只秤一次總重。
- [ ] 每批跑現有 conveyor counting flow，保留系統 count。
- [ ] 每批結束後，把整批豆倒到 scale 上，輸入 `true_weight_g`。
- [ ] 每批建議 count 至少 `200-500 beans`，降低 random per-bean variation。
- [ ] 收集 `30-50 batches`，並刻意涵蓋：
  - moisture：fresh / aged / 放置不同天數
  - roast：green / light / medium / dark
  - variety：若取得容易，至少 2-3 種來源或品種
  - process：washed / natural / honey 若可取得
- [ ] 每 5-10 批跑一次 dataset audit：

```bash
python3 spectral_capture/calibration/train_density_model.py --audit-only
```

Expected output:

```text
rows=30 labeled=30 missing_weight=0 feature_status_ok>=90%
condition coverage: roast_level>=4 moisture_proxy>=2
```

### Deliverable

`spectral_capture/data/calibration/density_batches.jsonl` 中有 `30-50` 筆 labeled rows，且每筆都有：

- `count`
- aggregate 10-band features
- bbox geometry stats
- `true_weight_g`
- `density_factor_label`
- roast / bean_type / batch metadata

### Gating Risk

資料多樣性就是模型上限。如果 30 批都來自同一天、同一 roast、同一 moisture condition，cross-validation 可能看起來漂亮，但換新批次仍會偏。Phase 2 gate 是資料覆蓋範圍，而不是 row count 本身。

---

## Phase 3: Train, cross-validate, and decide GO/NO-GO

**Duration:** 3-5d  
**Lead:** Codex  
**Support:** both 一起解讀結果與決定是否進 Phase 4

### Goal

建立可驗證的 empirical density correction model，並誠實回答：VNIR 350-950 nm 是否真的把 batch-level systematic bias 從 `+/-8%` 降到約 `+/-3-4%`。

### Concrete Tasks

- [ ] Create `spectral_capture/calibration/train_density_model.py`
  - 載入 labeled rows。
  - 排除 `true_weight_g is null`、`feature_status != "ok"` 的資料。
  - 計算 target：

```text
density_factor_label = true_weight_g / (count * g_per_bean_base)
```

- [ ] Build feature set v1
  - 10-band means：`B1_mean` ... `B10_mean`
  - 10-band stds：`B1_std` ... `B10_std`
  - water-edge proxy：`B10_B6_ratio`, `B10_B8_ratio`, `B9_B6_ratio`
  - visible roast/color proxy：`B4_B2_ratio`, `B6_B1_ratio`, `visible_slope_B1_B6`
  - geometry：`bbox_area_mean/std/p50`, `bbox_aspect_mean/std`, `bbox_width_mean`, `bbox_height_mean`
  - metadata one-hot：`bean_type`, `roast_level` only if available at inference time

- [ ] Train `PLSR` baseline
  - Use standardized numeric features。
  - Tune `n_components` from `1..min(8, n_features, n_samples-2)`。
  - Report coefficients / important wavelengths for interpretability。

- [ ] Train gradient boosting candidate
  - Use `HistGradientBoostingRegressor` or `GradientBoostingRegressor`。
  - Keep hyperparameter grid small to avoid overfitting：

```text
max_iter / n_estimators: 50, 100, 200
learning_rate: 0.03, 0.05, 0.1
max_leaf_nodes or max_depth: shallow only
```

- [ ] Cross-validate with realistic splits
  - Minimum：`KFold` or `LeaveOneOut` if only 30 rows。
  - Better：group by `roast_level` or collection day when possible。
  - Required report columns：
    - `base_weight_error_pct`
    - `corrected_weight_error_pct`
    - `absolute_error_g`
    - `mape_pct`
    - `bias_pct_by_roast`

- [ ] Generate validation report
  - Output file：`spectral_capture/data/calibration/density_model_report.md`
  - Include:
    - fixed `g_per_bean` baseline error distribution
    - PLSR corrected error distribution
    - boosting corrected error distribution
    - held-out examples table
    - GO/NO-GO recommendation

- [ ] Save model artifact only if GO
  - Output directory：`spectral_capture/data/models/density_correction/`
  - Files:

```text
density_model.joblib
feature_schema.json
model_card.md
validation_report.json
```

### GO Criteria

Proceed to Phase 4 only if held-out validation shows:

- median absolute percentage error improves meaningfully vs fixed `g_per_bean`
- systematic bias range improves from about `+/-8%` toward `+/-3-4%`
- no single major condition, such as dark roast or aged beans, remains catastrophically biased
- model performance is stable under grouped validation, not only random split

### NO-GO Criteria

Recommend pivoting to a load cell or hybrid system if:

- VNIR-corrected model does not beat fixed `g_per_bean` by at least a practical margin
- validation error remains near `+/-8%`
- performance collapses when holding out roast/moisture/variety groups
- feature importances look dominated by noise or geometry-only leakage

### Deliverable

`density_model_report.md` with a clear GO/NO-GO decision. If GO, also save versioned model artifact and feature schema.

### Gating Risk

VNIR correlation may be too weak for density/weight at 350-950 nm, especially for moisture differences. This is the decision gate: if the empirical signal does not reduce bias enough, do not spend engineering time on live integration; pivot to load cell or hybrid count + load-cell correction.

---

## Phase 4: Integrate trained model into live system

**Duration:** 3-5d  
**Lead:** Codex  
**Support:** user-manual 現場確認 UI 與 inference 結果

### Goal

把 Phase 3 通過 GO gate 的 model 接到 live batch workflow：batch finalize 時算 aggregate features，predict `density_factor`，保存 corrected weight，手機 cockpit 顯示結果。

### Concrete Tasks

- [ ] Create `spectral_capture/calibration/density_model.py`
  - 載入 `density_model.joblib` 與 `feature_schema.json`。
  - 若 model missing，回傳 structured fallback：

```json
{
  "available": false,
  "density_factor": 1.0,
  "confidence": "not_calibrated",
  "model_version": null
}
```

- [ ] Modify `spectral_capture/preview_display.py`
  - batch finalize 時：
    - compute aggregate VNIR features
    - predict `density_factor`
    - compute `base_weight_g`
    - compute `corrected_weight_g`
    - write fields into batch JSON

```json
{
  "weight_estimate": {
    "base_weight_g": 60.85,
    "density_factor": 1.04,
    "corrected_weight_g": 63.29,
    "model_version": "density_vnir_20260613",
    "confidence": "calibrated"
  }
}
```

- [ ] Modify `spectral_capture/control_server.py`
  - `GET /api/batches` include `weight_estimate` summary。
  - `GET /api/weight/estimate?batch_id=...` return full estimate plus fallback reason。
  - `GET /api/weight/model` return model card summary and latest validation metrics。

- [ ] Modify `spectral_capture/ui/index.html`
  - 在 count tab 或新增 weight section 顯示：
    - count
    - base weight
    - corrected weight
    - density factor
    - confidence
  - `not_calibrated` 時清楚顯示「使用固定 g/bean，尚未啟用 VNIR correction」。

- [ ] Add tests
  - `spectral_capture/tests/test_density_model.py`：model missing fallback、schema mismatch error、successful prediction。
  - `spectral_capture/tests/test_control_server.py`：batch list includes corrected weight when available。
  - `spectral_capture/tests/test_preview_display_batch.py`：batch JSON preserves existing count fields and adds optional `weight_estimate`。

### Deliverable

Live system 在每批結束後輸出 `base_weight_g` 與 `corrected_weight_g`，手機 cockpit 可看到 corrected weight 與 model confidence。

### Gating Risk

Inference 與 feature extraction 不能讓 preview/count loop 卡頓。若 raw band extraction 太慢，Phase 4 必須改成 background worker 或 batch-finalize async job，而不是塞在每 frame main loop。

---

## Phase 5: Field validation and iteration

**Duration:** 1 week  
**Lead:** both  
**Support:** Codex 做分析，user-manual 做現場秤重

### Goal

用 live integrated system 做現場驗證：每批比較 `corrected_weight_g` 與 kitchen scale `true_weight_g`，確認 Phase 3 的離線結果能不能在真實流程重現。

### Concrete Tasks

- [ ] 跑至少 10-20 個新 validation batches，不混入 Phase 2 training set。
- [ ] 每批記錄：
  - `count`
  - `base_weight_g`
  - `density_factor`
  - `corrected_weight_g`
  - `true_weight_g`
  - condition notes：fresh/aged、roast、variety、環境光或輸送帶異常
- [ ] 產生 field validation report：

```bash
python3 spectral_capture/calibration/train_density_model.py --field-report
```

- [ ] 若某類條件持續偏差，新增 targeted calibration batches，而不是盲目加一般資料。
- [ ] 若 corrected weight 在 field validation 不穩，回到 Phase 3 重新訓練或判定 NO-GO。

### Deliverable

`spectral_capture/data/calibration/field_validation_report.md`，列出 live predicted vs scale weight 的誤差與下一步建議。

### Gating Risk

離線 cross-validation 可能高估現場表現。常見原因是 illumination drift、bbox/feature alignment drift、豆子堆疊遮擋、或 calibration set 與 field set 條件不同。

---

## 4. 三個誠實 Caveats

1. 需要 kitchen scale 做 calibration labels：沒有 `true_weight_g`，VNIR model 沒有 supervised target；這不是 unsupervised 自動校準。
2. Data diversity bounds accuracy：模型只能在 Phase 2 覆蓋過的 moisture / roast / variety 範圍內可靠外插；資料太窄會讓 validation 看似有效、現場卻失準。
3. VNIR 350-950 nm 不是 full-NIR：強 water absorption bands `~1450 nm`、`~1940 nm` 不可見，因此這是 empirical correlation，不是直接水分 spectroscopy。

---

## 5. 強烈建議的執行策略

先做 Phase 0-3，作為 `~2-3 weeks` 的 GO/NO-GO proof-of-concept。Phase 1 建好 dataset logger，Phase 2 收 30-50 批，Phase 3 用 held-out validation 證明 VNIR 是否能把固定 `g_per_bean` 的 batch-level systematic bias 從約 `+/-8%` 拉到 `+/-3-4%`。只有 Phase 3 報告通過 GO criteria，才投入 Phase 4-5 的 live integration 與 field validation；若 Phase 3 是 NO-GO，直接轉向 load cell 或 count + load-cell hybrid，避免把工程時間花在物理訊號不足的模型上。

---

## 6. Final Risk Statement

VNIR at `350-950 nm` 對 coffee-bean weight correction 有可測機會，因為 visible bands 能捕捉 roast / color / variety，B7-B10 也可能帶有 moisture-correlated edge information；但它缺少 `1450 nm` 與 `1940 nm` 強 water absorption bands，所以可行性本質上取決於 empirical calibration data 是否穩定反映 density drivers。最務實的期待是把 count-to-weight 的系統性偏差從約 `+/-8%` 降到 `+/-3-4%`；若 Phase 3 的 held-out validation 達不到這個幅度，就應誠實判定 VNIR-only 不足，改採 load cell 或 hybrid correction，而不是繼續把它包裝成 direct spectroscopy。
