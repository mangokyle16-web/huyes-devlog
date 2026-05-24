# Mold Experiment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立 `mold_experiment.py` 主控腳本，整合白光 FPI 掃描與 UV 365nm 螢光偵測，輸出雙模態交叉驗證的黴菌可疑豆報告。

**Architecture:** 新建 `mold_analysis.py` 放純分析函式（可測試、無硬體依賴）；`mold_experiment.py` 作為主控入口，import `uv_mold_scan.py` 已有的 subprocess 工具函式；不修改任何現有腳本。

**Tech Stack:** Python 3.11、numpy、opencv-python、matplotlib、pytest；現有 CM020D SDK binaries（capture_one、spec_fingerprint）

---

## File Map

| 操作 | 路徑 | 用途 |
|------|------|------|
| **新建** | `mold_analysis.py` | 純分析函式：Mahalanobis、cross_validate、圖表輸出 |
| **新建** | `mold_experiment.py` | 主控腳本：四步拍攝流程 + 分析 + 輸出 |
| **新建** | `tests/test_mold_analysis.py` | `mold_analysis.py` 的 unit tests |
| **只讀 import** | `uv_mold_scan.py` | 複用：`load_spec_csv`, `compute_fluorescence`, `compute_fl_score`, `capture_qs`, `extract_gray`, `run_segmentation`, `run_spec_fingerprint` |

---

## Task 1：mold_analysis.py — 核心分析函式

**Files:**
- Create: `mold_analysis.py`
- Test: `tests/test_mold_analysis.py`

- [ ] **Step 1：寫失敗測試（compute_mahalanobis）**

`tests/test_mold_analysis.py` 建立新檔：

```python
import csv, os, sys, pytest
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from mold_analysis import compute_mahalanobis, cross_validate, save_report_csv


# ── compute_mahalanobis ────────────────────────────────────────────────────────

def _make_spec(n_beans, base_val=1.0):
    """n normal beans with uniform spectrum."""
    nms = [350, 410, 450, 490, 550, 650, 750, 850, 930]
    return {f"bean_{i}": {nm: base_val for nm in nms} for i in range(1, n_beans + 1)}


def test_compute_mahalanobis_returns_all_keys():
    spec = _make_spec(5)
    result = compute_mahalanobis(spec)
    assert set(result.keys()) == set(spec.keys())


def test_compute_mahalanobis_non_negative():
    spec = _make_spec(10)
    result = compute_mahalanobis(spec)
    assert all(v >= 0 for v in result.values())


def test_compute_mahalanobis_outlier_highest():
    """Outlier bean should have maximum distance."""
    spec = _make_spec(9)
    # bean_10 is an outlier with extreme spectral values
    spec["bean_10"] = {350: 5.0, 410: 0.1, 450: 5.0, 490: 0.1,
                       550: 5.0, 650: 0.1, 750: 5.0, 850: 0.1, 930: 5.0}
    result = compute_mahalanobis(spec)
    max_bean = max(result, key=result.__getitem__)
    assert max_bean == "bean_10"


def test_compute_mahalanobis_too_few_beans():
    """Returns zeros when fewer than 3 beans (SVD unstable)."""
    spec = _make_spec(2)
    result = compute_mahalanobis(spec)
    assert all(v == 0.0 for v in result.values())


# ── cross_validate ─────────────────────────────────────────────────────────────

def _make_cross_data():
    """
    bean_1: both mahal and fl_norm high  → HIGH
    bean_2: only mahal high              → MID
    bean_3: only fl_norm high            → MID
    bean_4..10: both low                 → LOW
    With value=20 for outliers vs 1.0 for normals.
    """
    mahal   = {f"bean_{i}": 1.0 for i in range(1, 11)}
    fl_norm = {f"bean_{i}": 1.0 for i in range(1, 11)}
    mahal["bean_1"]   = 20.0;  fl_norm["bean_1"]  = 20.0
    mahal["bean_2"]   = 20.0   # fl_norm stays 1.0
    fl_norm["bean_3"] = 20.0   # mahal stays 1.0
    return mahal, fl_norm


def test_cross_validate_high():
    mahal, fl_norm = _make_cross_data()
    result = cross_validate(mahal, fl_norm, sigma=1.5)
    assert result["bean_1"] == "HIGH"


def test_cross_validate_mid_mahal_only():
    mahal, fl_norm = _make_cross_data()
    result = cross_validate(mahal, fl_norm, sigma=1.5)
    assert result["bean_2"] == "MID"


def test_cross_validate_mid_fl_only():
    mahal, fl_norm = _make_cross_data()
    result = cross_validate(mahal, fl_norm, sigma=1.5)
    assert result["bean_3"] == "MID"


def test_cross_validate_low():
    mahal, fl_norm = _make_cross_data()
    result = cross_validate(mahal, fl_norm, sigma=1.5)
    assert result["bean_4"] == "LOW"


def test_cross_validate_returns_all_common_keys():
    mahal   = {"bean_1": 1.0, "bean_2": 5.0}
    fl_norm = {"bean_1": 1.0, "bean_2": 5.0}
    result = cross_validate(mahal, fl_norm)
    assert set(result.keys()) == {"bean_1", "bean_2"}


def test_cross_validate_ignores_keys_not_in_both():
    mahal   = {"bean_1": 1.0, "bean_x": 99.0}
    fl_norm = {"bean_1": 1.0, "bean_y": 99.0}
    result = cross_validate(mahal, fl_norm)
    assert set(result.keys()) == {"bean_1"}


# ── save_report_csv ────────────────────────────────────────────────────────────

def test_save_report_csv_columns(tmp_path):
    mahal   = {"bean_1": 1.23, "bean_2": 4.56}
    fl_norm = {"bean_1": 0.01, "bean_2": 0.99}
    suspects = {"bean_1": "LOW", "bean_2": "HIGH"}
    out = str(tmp_path / "report.csv")
    save_report_csv(mahal, fl_norm, suspects, out)
    with open(out) as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["bean_id"] == "bean_1"
    assert rows[1]["suspect_level"] == "HIGH"
    assert float(rows[1]["mahal"]) == pytest.approx(4.56, abs=0.01)
    assert float(rows[1]["fl_norm"]) == pytest.approx(0.99, abs=0.01)
```

- [ ] **Step 2：確認測試失敗**

```bash
cd /home/kyle/KyleClaude && python -m pytest tests/test_mold_analysis.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'mold_analysis'`

- [ ] **Step 3：實作 mold_analysis.py**

建立 `/home/kyle/KyleClaude/mold_analysis.py`：

```python
#!/usr/bin/env python3
"""
mold_analysis.py - Pure analysis functions for dual-mode mold detection.
No subprocess calls; no hardware dependencies.
"""
import csv, json
import cv2
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches


def compute_mahalanobis(spec: dict) -> dict:
    """
    PCA-based outlier distance per bean.
    spec: {bean_id: {nm_int: float}}
    Returns {bean_id: float}  higher = more anomalous.
    """
    bean_ids = sorted(spec.keys())
    if len(bean_ids) < 3:
        return {bid: 0.0 for bid in bean_ids}
    all_nms = sorted(next(iter(spec.values())).keys())
    X = np.array([[spec[bid].get(nm, 0.0) for nm in all_nms] for bid in bean_ids])
    X_c = X - X.mean(axis=0)
    U, s, _ = np.linalg.svd(X_c, full_matrices=False)
    n_pc = min(5, len(bean_ids) - 1)
    pc = U[:, :n_pc] * s[:n_pc]
    dist = np.sqrt(((pc - pc.mean(axis=0)) / (pc.std(axis=0) + 1e-9)) ** 2).mean(axis=1)
    return {bid: float(dist[i]) for i, bid in enumerate(bean_ids)}


def cross_validate(mahal: dict, fl_norm: dict, sigma: float = 1.5) -> dict:
    """
    Returns {bean_id: 'LOW'|'MID'|'HIGH'}.
    HIGH: both indicators exceed mean + sigma*std.
    MID:  one exceeds threshold.
    LOW:  neither.
    """
    common = sorted(set(mahal) & set(fl_norm))

    def _thr(d):
        v = np.array([d[k] for k in common])
        return float(v.mean() + sigma * v.std())

    thr_m = _thr(mahal)
    thr_f = _thr(fl_norm)
    result = {}
    for bid in common:
        hi_m = mahal[bid] > thr_m
        hi_f = fl_norm[bid] > thr_f
        result[bid] = "HIGH" if (hi_m and hi_f) else ("MID" if (hi_m or hi_f) else "LOW")
    return result


def save_report_csv(mahal: dict, fl_norm: dict, suspects: dict, out_path: str):
    with open(out_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["bean_id", "mahal", "fl_norm", "suspect_level"])
        for bid in sorted(suspects):
            w.writerow([bid,
                        f"{mahal.get(bid, 0.0):.4f}",
                        f"{fl_norm.get(bid, 0.0):.4f}",
                        suspects[bid]])


def save_scatter_plot(mahal: dict, fl_norm: dict, suspects: dict, out_path: str):
    color_map = {"HIGH": "crimson", "MID": "orange", "LOW": "steelblue"}
    common = sorted(set(mahal) & set(fl_norm) & set(suspects))
    fig, ax = plt.subplots(figsize=(8, 6))
    for bid in common:
        level = suspects[bid]
        ax.scatter(mahal[bid], fl_norm[bid],
                   color=color_map[level], s=60, alpha=0.8,
                   zorder=3 if level == "HIGH" else 2)
        if level != "LOW":
            ax.annotate(bid.replace("bean_", "#"),
                        (mahal[bid], fl_norm[bid]),
                        fontsize=7, ha="left", va="bottom")
    m_arr = np.array([mahal[b] for b in common])
    f_arr = np.array([fl_norm[b] for b in common])
    ax.axvline(m_arr.mean() + 1.5 * m_arr.std(), color="gray", ls="--", lw=0.8, alpha=0.6)
    ax.axhline(f_arr.mean() + 1.5 * f_arr.std(), color="gray", ls="--", lw=0.8, alpha=0.6)
    patches = [mpatches.Patch(color=c, label=l) for l, c in color_map.items()]
    ax.legend(handles=patches, fontsize=9)
    ax.set_xlabel("Mahalanobis distance (white-light FPI)")
    ax.set_ylabel("fl_norm (UV 365nm fluorescence)")
    ax.set_title("Dual-Mode Mold Detection")
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(out_path, dpi=150)
    plt.close()


def save_cross_labeled_png(ref_gray_path: str, rois_path: str,
                            mahal: dict, fl_norm: dict, suspects: dict,
                            out_path: str):
    img = cv2.imread(ref_gray_path)
    if img is None:
        raise RuntimeError(f"Cannot read: {ref_gray_path}")
    with open(rois_path) as f:
        rois_data = json.load(f)
    bgr_map = {"HIGH": (0, 0, 220), "MID": (0, 140, 255), "LOW": (180, 160, 0)}
    for roi in rois_data:
        bean_id = f"bean_{roi['id']}"
        if bean_id not in suspects:
            continue
        level = suspects[bean_id]
        cx = int((roi["x0"] + roi["x1"]) / 2)
        cy = int((roi["y0"] + roi["y1"]) / 2)
        r  = max(10, int(np.sqrt((roi["x1"] - roi["x0"]) *
                                  (roi["y1"] - roi["y0"]) / np.pi) * 0.8))
        bgr = bgr_map[level]
        cv2.circle(img, (cx, cy), r, bgr, 4 if level == "HIGH" else 2)
        label = f"m{mahal.get(bean_id, 0):.1f}/f{fl_norm.get(bean_id, 0):.2f}"
        if level == "HIGH":
            label += "!"
        cv2.putText(img, label, (cx - 25, cy - r - 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.35, bgr, 1, cv2.LINE_AA)
    cv2.imwrite(out_path, img)
```

- [ ] **Step 4：執行測試，確認全部通過**

```bash
cd /home/kyle/KyleClaude && python -m pytest tests/test_mold_analysis.py -v
```

Expected output（11 tests）：
```
tests/test_mold_analysis.py::test_compute_mahalanobis_returns_all_keys PASSED
tests/test_mold_analysis.py::test_compute_mahalanobis_non_negative PASSED
tests/test_mold_analysis.py::test_compute_mahalanobis_outlier_highest PASSED
tests/test_mold_analysis.py::test_compute_mahalanobis_too_few_beans PASSED
tests/test_mold_analysis.py::test_cross_validate_high PASSED
tests/test_mold_analysis.py::test_cross_validate_mid_mahal_only PASSED
tests/test_mold_analysis.py::test_cross_validate_mid_fl_only PASSED
tests/test_mold_analysis.py::test_cross_validate_low PASSED
tests/test_mold_analysis.py::test_cross_validate_returns_all_common_keys PASSED
tests/test_mold_analysis.py::test_cross_validate_ignores_keys_not_in_both PASSED
tests/test_mold_analysis.py::test_save_report_csv_columns PASSED
11 passed
```

- [ ] **Step 5：Commit**

```bash
cd /home/kyle/KyleClaude
git add mold_analysis.py tests/test_mold_analysis.py
git commit -m "feat: add mold_analysis pure functions with tests"
```

---

## Task 2：mold_experiment.py — 主控腳本

**Files:**
- Create: `mold_experiment.py`

- [ ] **Step 1：建立 mold_experiment.py**

```python
#!/usr/bin/env python3
"""
mold_experiment.py - Dual-mode mold detection experiment.
Step 1: White-light FPI scan  → Mahalanobis distance
Step 2: UV 365nm scan         → fl_norm fluorescence
Step 3: Cross-validate        → scatter plot + labeled PNG + CSV report
"""
import argparse, os, sys
from datetime import datetime

from uv_mold_scan import (
    load_spec_csv, compute_fluorescence, compute_fl_score,
    capture_qs, extract_gray, run_segmentation, run_spec_fingerprint,
)
from mold_analysis import (
    compute_mahalanobis, cross_validate,
    save_scatter_plot, save_cross_labeled_png, save_report_csv,
)

EXPOSURE_WHITE = 2500
EXPOSURE_UV    = 5000


def main():
    parser = argparse.ArgumentParser(description="Dual-mode mold detection experiment")
    parser.add_argument("--sigma", type=float, default=1.5,
                        help="Threshold in sigmas above mean (default: 1.5)")
    args = parser.parse_args()

    ts          = datetime.now().strftime("%Y%m%d_%H%M%S")
    session_dir = os.path.expanduser(f"~/Desktop/mold_exp_{ts}")
    os.makedirs(session_dir, exist_ok=True)
    print(f"\n[MOLD EXPERIMENT] Session: {session_dir}\n")

    ref_qs      = os.path.join(session_dir, "ref.qs")
    ref_gray    = os.path.join(session_dir, "capture_2500us_gray.png")
    white_qs    = os.path.join(session_dir, "white.qs")
    white_csv   = os.path.join(session_dir, "white_spec.csv")
    uv_qs       = os.path.join(session_dir, "uv_on.qs")
    dark_qs     = os.path.join(session_dir, "dark.qs")
    uv_csv      = os.path.join(session_dir, "uv_spec.csv")
    dark_csv    = os.path.join(session_dir, "dark_spec.csv")
    scatter_png = os.path.join(session_dir, "scatter.png")
    labeled_png = os.path.join(session_dir, "labeled.png")
    report_csv  = os.path.join(session_dir, "report.csv")
    rois        = os.path.join(session_dir, "beans_rois.json")

    # ── Step 1：白光灰階參考 → 分割 ──────────────────────────────────────────
    input("[STEP 1/4] 白光開，UV 關。豆子擺好。按 Enter 拍攝...")
    print("  拍攝灰階參考...", flush=True)
    capture_qs(ref_qs, EXPOSURE_WHITE)
    extract_gray(ref_qs, ref_gray)
    print("  分割豆子...", flush=True)
    n = run_segmentation(session_dir)
    print(f"  偵測到 {n} 顆豆子")

    # ── Step 2：白光 FPI 全波段掃描 → Mahalanobis ─────────────────────────────
    input(f"\n[STEP 2/4] 白光保持開啟。按 Enter 拍 FPI 全波段（{EXPOSURE_WHITE}us）...")
    print("  FPI 掃描中...", flush=True)
    capture_qs(white_qs, EXPOSURE_WHITE)
    run_spec_fingerprint(white_qs, white_csv, session_dir)
    white_spec = load_spec_csv(white_csv)
    mahal = compute_mahalanobis(white_spec)
    print(f"  Mahalanobis 完成，{len(mahal)} 顆")

    # ── Step 3：UV 螢光拍攝 ───────────────────────────────────────────────────
    input(f"\n[STEP 3/4] 關白光，開 UV 365nm，蓋上遮光盒。按 Enter（{EXPOSURE_UV}us）...")
    print("  UV 拍攝中...", flush=True)
    capture_qs(uv_qs, EXPOSURE_UV)
    run_spec_fingerprint(uv_qs, uv_csv, session_dir)

    # ── Step 4：暗場 ──────────────────────────────────────────────────────────
    input(f"\n[STEP 4/4] 關所有光。按 Enter 拍暗場（{EXPOSURE_UV}us）...")
    print("  暗場拍攝中...", flush=True)
    capture_qs(dark_qs, EXPOSURE_UV)
    run_spec_fingerprint(dark_qs, dark_csv, session_dir)

    # ── 交叉分析 ──────────────────────────────────────────────────────────────
    print("\n[分析] 計算螢光 + 交叉驗證...", flush=True)
    uv_spec   = load_spec_csv(uv_csv)
    dark_spec = load_spec_csv(dark_csv)
    fl_signal = compute_fluorescence(uv_spec, dark_spec)
    _, fl_norm = compute_fl_score(fl_signal, uv_spec)
    suspects  = cross_validate(mahal, fl_norm, sigma=args.sigma)

    n_high = sum(1 for v in suspects.values() if v == "HIGH")
    n_mid  = sum(1 for v in suspects.values() if v == "MID")
    n_low  = len(suspects) - n_high - n_mid
    print(f"  結果：HIGH={n_high}  MID={n_mid}  LOW={n_low}")
    for bid in sorted(suspects, key=lambda b: ("LOW", "MID", "HIGH").index(suspects[b]),
                      reverse=True):
        if suspects[bid] != "LOW":
            print(f"  {bid}: {suspects[bid]}"
                  f"  mahal={mahal.get(bid, 0):.3f}"
                  f"  fl_norm={fl_norm.get(bid, 0):.4f}")

    # ── 輸出 ──────────────────────────────────────────────────────────────────
    print("\n[輸出] 產生結果...", flush=True)
    save_scatter_plot(mahal, fl_norm, suspects, scatter_png)
    save_cross_labeled_png(ref_gray, rois, mahal, fl_norm, suspects, labeled_png)
    save_report_csv(mahal, fl_norm, suspects, report_csv)

    print(f"\n[完成] {session_dir}/")
    print(f"  scatter.png    ← 二維散點圖（Mahalanobis vs fl_norm）")
    print(f"  labeled.png    ← 豆子位置標注（紅=HIGH 橘=MID）")
    print(f"  report.csv     ← 每顆豆完整數據")
    if n_high:
        print(f"\n  *** {n_high} 顆 HIGH 可疑豆，請分離並觀察 48 小時 ***")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2：確認語法正確（不連接硬體）**

```bash
cd /home/kyle/KyleClaude && python -c "import mold_experiment; print('OK')"
```

Expected: `OK`（無 ImportError）

- [ ] **Step 3：Commit**

```bash
cd /home/kyle/KyleClaude
git add mold_experiment.py
git commit -m "feat: add mold_experiment dual-mode orchestrator"
```

---

## Task 3：手動執行驗證

這一步需要連接相機，無法自動化。

- [ ] **Step 1：準備豆子**

把懷疑發霉的豆子和正常豆子混放在 DiFluid 碟上（建議 15–30 顆）。

- [ ] **Step 2：執行實驗**

```bash
cd /home/kyle/KyleClaude
python mold_experiment.py --sigma 1.5
```

按照四個提示依序操作：
1. 白光開 → Enter（灰階 + 分割）
2. 白光開 → Enter（FPI 全波段）
3. 白光關、UV 開、蓋遮光盒 → Enter
4. 全關 → Enter（暗場）

- [ ] **Step 3：確認輸出**

```bash
ls ~/Desktop/mold_exp_*/
```

應看到：`scatter.png`、`labeled.png`、`report.csv`、以及各個 `.qs` 原始檔

- [ ] **Step 4：開啟散點圖確認信號存在**

```bash
eog ~/Desktop/mold_exp_*/scatter.png
```

散點圖應有可見的點分布（若全部堆在一起，表示信噪比不足 → 見下方診斷）

- [ ] **Step 5：記錄結果**

把 HIGH/MID 豆子分離，放置 48 小時。在 `experiment_log.md` 記錄：
- 幾顆 HIGH / MID
- 散點圖是否有聚類
- 48h 後照片 + 是否有菌落

---

## 診斷：若散點圖無聚類

**可能原因 A：白光 FPI 信噪比不足**
→ 改用 `--sigma 1.0` 放寬閾值，或改用純 UV 模式（直接執行 `uv_mold_scan.py`）

**可能原因 B：樣本本身無活性黴菌**
→ 啟動主動培養（高濕密封袋，35°C，3–5 天），重新實驗

**可能原因 C：遮光不足影響 UV 信號**
→ 確認遮光盒完全密閉，或在夜晚/暗室重拍 Step 3–4
