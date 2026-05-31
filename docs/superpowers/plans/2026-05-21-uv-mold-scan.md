# UV Mold Scan Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立 `uv_mold_scan.py`，透過 365nm UV LED 照射 + OCF 多光譜相機拍攝，偵測熟豆可能的黴菌螢光訊號。

**Architecture:** 單一 Python 腳本，三次互動拍攝（白光參考 → UV on → 全暗），暗場相減後計算 per-bean 螢光正規化分數，輸出標注圖 + 光譜圖 + CSV。純分析函式獨立於硬體，可單元測試；subprocess wrapper 薄且不可單元測試，以手動煙霧測試驗證。

**Tech Stack:** Python 3.11, numpy, cv2, matplotlib, pytest；現有 binaries：`capture_one`, `ocf_to_png`, `spec_fingerprint`, `fast_seg_agtron.py`

---

## File Map

| 動作 | 路徑 | 職責 |
|------|------|------|
| Create | `/home/kyle/KyleClaude/uv_mold_scan.py` | 主腳本：constants、純函式、subprocess wrappers、main() |
| Create | `/home/kyle/KyleClaude/tests/test_uv_mold_scan.py` | 純函式的單元測試 |

---

### Task 1: 骨架 + 測試基礎設施

**Files:**
- Create: `/home/kyle/KyleClaude/uv_mold_scan.py`
- Create: `/home/kyle/KyleClaude/tests/__init__.py`
- Create: `/home/kyle/KyleClaude/tests/test_uv_mold_scan.py`

- [ ] **Step 1: 建立 tests 目錄與 `__init__.py`**

```bash
mkdir -p /home/kyle/KyleClaude/tests
touch /home/kyle/KyleClaude/tests/__init__.py
```

- [ ] **Step 2: 建立 `uv_mold_scan.py` 骨架**（imports + constants + 空 stub）

```python
#!/usr/bin/env python3
"""
uv_mold_scan.py - UV 365nm mold fluorescence detection
Usage: python3 uv_mold_scan.py [--n-beans N] [--exposure-uv US]
"""
import argparse, csv, json, os, subprocess, sys
from datetime import datetime

import cv2
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.cm as cm
import numpy as np

# ── Paths ──────────────────────────────────────────────────────────────────────
BUILD    = "/home/kyle/KyleClaude/multispectral_demo/build"
OCFBS     = "/home/kyle/KyleClaude/camera_new.ocfbs"
OCFDB     = "/home/kyle/KyleClaude/db_std.ocfdb"
FAST_SEG = "/home/kyle/KyleClaude/fast_seg_agtron.py"
SDK      = "/home/kyle/KyleClaude/sdk_extract/linux-sdk-arm64/qssdk-20250817"

CAPTURE_ONE      = os.path.join(BUILD, "capture_one")
OCF_TO_PNG        = os.path.join(BUILD, "ocf_to_png")
SPEC_FINGERPRINT = os.path.join(BUILD, "spec_fingerprint")

# ── Analysis constants ─────────────────────────────────────────────────────────
FL_BANDS    = [410, 430, 450, 470, 490]  # aflatoxin B1 emission region
UV_REF_BAND = 350                        # reflected UV band for normalization


# ── Pure analysis functions (unit-testable) ────────────────────────────────────

def load_spec_csv(path):
    pass  # Task 2

def compute_fluorescence(uv_spec, dark_spec):
    pass  # Task 3

def compute_fl_score(fl_signal, uv_spec, fl_bands=None, uv_ref_band=None):
    pass  # Task 4

def flag_suspects(fl_norm, sigma=1.5):
    pass  # Task 4


# ── Subprocess wrappers ────────────────────────────────────────────────────────

def _sdk_env():
    pass  # Task 5

def capture_ocf(out_path, exposure_us):
    pass  # Task 5

def extract_gray(ocf_path, gray_png_path):
    pass  # Task 5

def run_segmentation(session_dir):
    pass  # Task 5

def run_spec_fingerprint(ocf_path, out_csv, session_dir):
    pass  # Task 5


# ── Visualization ──────────────────────────────────────────────────────────────

def save_labeled_png(ref_gray_path, rois_path, fl_norm, flags, out_path):
    pass  # Task 6

def save_spectrum_plot(fl_signal, fl_norm, flags, out_path):
    pass  # Task 6

def save_report_csv(fl_score, fl_norm, flags, out_path):
    pass  # Task 6


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    pass  # Task 7


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: 建立測試骨架**

建立 `/home/kyle/KyleClaude/tests/test_uv_mold_scan.py`：

```python
import csv, os, sys, pytest
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from uv_mold_scan import (
    load_spec_csv, compute_fluorescence, compute_fl_score, flag_suspects,
    save_report_csv,
)


def _make_csv(tmp_path, data):
    """Write a spec CSV matching spec_fingerprint output format."""
    all_nms = sorted({nm for spec in data.values() for nm in spec})
    bean_ids = sorted(data.keys())
    path = str(tmp_path / "spec.csv")
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["wavelength_nm"] + bean_ids)
        for nm in all_nms:
            w.writerow([nm] + [data[b].get(nm, 0.0) for b in bean_ids])
    return path
```

- [ ] **Step 4: 確認測試骨架可以被收集（0 tests）**

```bash
cd /home/kyle/KyleClaude && python3 -m pytest tests/test_uv_mold_scan.py --collect-only
```

Expected: `0 items / 0 errors`

- [ ] **Step 5: Commit**

```bash
cd /home/kyle/KyleClaude
git add uv_mold_scan.py tests/__init__.py tests/test_uv_mold_scan.py
git commit -m "feat: uv_mold_scan skeleton + test infrastructure"
```

---

### Task 2: `load_spec_csv`

**Files:**
- Modify: `/home/kyle/KyleClaude/uv_mold_scan.py` — 實作 `load_spec_csv`
- Modify: `/home/kyle/KyleClaude/tests/test_uv_mold_scan.py` — 加入測試

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_uv_mold_scan.py` 加入：

```python
def test_load_spec_csv_basic(tmp_path):
    path = _make_csv(tmp_path, {
        "bean_1": {350: 1.0, 410: 2.0, 450: 3.0},
        "bean_2": {350: 1.5, 410: 2.5, 450: 3.5},
    })
    spec = load_spec_csv(path)
    assert set(spec.keys()) == {"bean_1", "bean_2"}
    assert spec["bean_1"][350] == pytest.approx(1.0)
    assert spec["bean_2"][450] == pytest.approx(3.5)


def test_load_spec_csv_wavelength_as_int(tmp_path):
    path = _make_csv(tmp_path, {"bean_1": {410: 5.5}})
    spec = load_spec_csv(path)
    assert 410 in spec["bean_1"]          # key must be int, not string
    assert spec["bean_1"][410] == pytest.approx(5.5)
```

- [ ] **Step 2: 確認測試失敗**

```bash
cd /home/kyle/KyleClaude && python3 -m pytest tests/test_uv_mold_scan.py::test_load_spec_csv_basic -v
```

Expected: `FAILED` (TypeError: 'NoneType' is not subscriptable)

- [ ] **Step 3: 實作 `load_spec_csv`**

替換 `uv_mold_scan.py` 中的 stub：

```python
def load_spec_csv(path):
    """Return {bean_id: {nm_int: float}} from spec_fingerprint CSV."""
    result = {}
    with open(path) as f:
        reader = csv.DictReader(f)
        bean_keys = [k for k in reader.fieldnames if k.startswith("bean_")]
        for k in bean_keys:
            result[k] = {}
        for row in reader:
            nm = int(float(row["wavelength_nm"]))
            for k in bean_keys:
                result[k][nm] = float(row[k])
    return result
```

- [ ] **Step 4: 確認測試通過**

```bash
cd /home/kyle/KyleClaude && python3 -m pytest tests/test_uv_mold_scan.py::test_load_spec_csv_basic tests/test_uv_mold_scan.py::test_load_spec_csv_wavelength_as_int -v
```

Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
cd /home/kyle/KyleClaude
git add uv_mold_scan.py tests/test_uv_mold_scan.py
git commit -m "feat: implement load_spec_csv with tests"
```

---

### Task 3: `compute_fluorescence`

**Files:**
- Modify: `/home/kyle/KyleClaude/uv_mold_scan.py`
- Modify: `/home/kyle/KyleClaude/tests/test_uv_mold_scan.py`

- [ ] **Step 1: 寫失敗測試**

```python
def test_compute_fluorescence_subtracts_dark():
    uv   = {"bean_1": {410: 5.0, 450: 6.0, 350: 2.0},
            "bean_2": {410: 3.0, 450: 4.0, 350: 1.5}}
    dark = {"bean_1": {410: 1.0, 450: 1.5, 350: 0.5},
            "bean_2": {410: 0.5, 450: 0.5, 350: 0.3}}
    fl = compute_fluorescence(uv, dark)
    assert fl["bean_1"][410] == pytest.approx(4.0)
    assert fl["bean_1"][450] == pytest.approx(4.5)
    assert fl["bean_2"][410] == pytest.approx(2.5)


def test_compute_fluorescence_clamps_negative():
    uv   = {"bean_1": {410: 0.3}}
    dark = {"bean_1": {410: 1.0}}
    fl = compute_fluorescence(uv, dark)
    assert fl["bean_1"][410] == 0.0   # must not go negative
```

- [ ] **Step 2: 確認失敗**

```bash
cd /home/kyle/KyleClaude && python3 -m pytest tests/test_uv_mold_scan.py::test_compute_fluorescence_subtracts_dark -v
```

Expected: `FAILED`

- [ ] **Step 3: 實作 `compute_fluorescence`**

```python
def compute_fluorescence(uv_spec, dark_spec):
    """Subtract dark from UV; clamp to 0 to remove negative noise."""
    fl = {}
    for bean_id, uv_bands in uv_spec.items():
        if bean_id not in dark_spec:
            continue
        fl[bean_id] = {
            nm: max(0.0, val - dark_spec[bean_id].get(nm, 0.0))
            for nm, val in uv_bands.items()
        }
    return fl
```

- [ ] **Step 4: 確認通過**

```bash
cd /home/kyle/KyleClaude && python3 -m pytest tests/test_uv_mold_scan.py::test_compute_fluorescence_subtracts_dark tests/test_uv_mold_scan.py::test_compute_fluorescence_clamps_negative -v
```

Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
cd /home/kyle/KyleClaude
git add uv_mold_scan.py tests/test_uv_mold_scan.py
git commit -m "feat: implement compute_fluorescence with dark-frame subtraction"
```

---

### Task 4: `compute_fl_score` + `flag_suspects`

**Files:**
- Modify: `/home/kyle/KyleClaude/uv_mold_scan.py`
- Modify: `/home/kyle/KyleClaude/tests/test_uv_mold_scan.py`

- [ ] **Step 1: 寫失敗測試**

```python
def test_compute_fl_score_emission_mean_and_norm():
    fl_signal = {
        "bean_1": {350: 0.0, 410: 2.0, 430: 2.0, 450: 2.0, 470: 2.0, 490: 2.0},
        "bean_2": {350: 0.0, 410: 1.0, 430: 1.0, 450: 1.0, 470: 1.0, 490: 1.0},
    }
    uv_spec = {"bean_1": {350: 4.0}, "bean_2": {350: 4.0}}
    fl_score, fl_norm = compute_fl_score(fl_signal, uv_spec)
    assert fl_score["bean_1"] == pytest.approx(2.0)
    assert fl_score["bean_2"] == pytest.approx(1.0)
    assert fl_norm["bean_1"]  == pytest.approx(2.0 / 4.0)
    assert fl_norm["bean_2"]  == pytest.approx(1.0 / 4.0)


def test_compute_fl_score_zero_uv_ref_no_crash():
    fl_signal = {"bean_1": {410: 1.0, 430: 1.0, 450: 1.0, 470: 1.0, 490: 1.0}}
    uv_spec   = {"bean_1": {350: 0.0}}   # UV ref = 0 → must not divide by zero
    fl_score, fl_norm = compute_fl_score(fl_signal, uv_spec)
    assert np.isfinite(fl_norm["bean_1"])


def test_flag_suspects_outlier_flagged():
    fl_norm = {"bean_1": 0.1, "bean_2": 0.1, "bean_3": 0.1,
               "bean_4": 0.1, "bean_5": 1.0}
    flags = flag_suspects(fl_norm, sigma=1.5)
    assert flags["bean_5"] == "SUSPECT"
    assert all(flags[f"bean_{i}"] == "OK" for i in range(1, 5))


def test_flag_suspects_all_identical_no_suspects():
    fl_norm = {"bean_1": 1.0, "bean_2": 1.0, "bean_3": 1.0}
    flags = flag_suspects(fl_norm, sigma=1.5)
    # std=0 → threshold = mean → no bean strictly exceeds mean
    assert all(f == "OK" for f in flags.values())
```

- [ ] **Step 2: 確認失敗**

```bash
cd /home/kyle/KyleClaude && python3 -m pytest tests/test_uv_mold_scan.py::test_compute_fl_score_emission_mean_and_norm -v
```

Expected: `FAILED`

- [ ] **Step 3: 實作 `compute_fl_score` 與 `flag_suspects`**

```python
def compute_fl_score(fl_signal, uv_spec, fl_bands=None, uv_ref_band=None):
    """
    Returns (fl_score, fl_norm).
    fl_score[bean] = mean of emission bands in fl_signal
    fl_norm[bean]  = fl_score / UV reflected band (350nm) for illumination normalization
    """
    if fl_bands is None:
        fl_bands = FL_BANDS
    if uv_ref_band is None:
        uv_ref_band = UV_REF_BAND
    fl_score, fl_norm = {}, {}
    for bean_id, spec in fl_signal.items():
        vals = [spec.get(nm, 0.0) for nm in fl_bands]
        score = float(np.mean(vals))
        uv_ref = uv_spec[bean_id].get(uv_ref_band, 0.0)
        fl_score[bean_id] = score
        fl_norm[bean_id]  = score / (uv_ref + 1e-6)
    return fl_score, fl_norm


def flag_suspects(fl_norm, sigma=1.5):
    """Return {bean_id: 'SUSPECT'|'OK'}. Threshold = mean + sigma * std."""
    vals = np.array(list(fl_norm.values()), dtype=float)
    threshold = vals.mean() + sigma * vals.std()
    return {bid: ("SUSPECT" if v > threshold else "OK") for bid, v in fl_norm.items()}
```

- [ ] **Step 4: 確認所有測試通過**

```bash
cd /home/kyle/KyleClaude && python3 -m pytest tests/test_uv_mold_scan.py -v
```

Expected: `8 passed`（Tasks 2–4 累計）

- [ ] **Step 5: Commit**

```bash
cd /home/kyle/KyleClaude
git add uv_mold_scan.py tests/test_uv_mold_scan.py
git commit -m "feat: implement compute_fl_score and flag_suspects with tests"
```

---

### Task 5: Subprocess wrappers

**Files:**
- Modify: `/home/kyle/KyleClaude/uv_mold_scan.py` — 實作 5 個 wrapper

- [ ] **Step 1: 實作 `_sdk_env` + `capture_ocf`**

```python
def _sdk_env():
    e = os.environ.copy()
    e["LD_LIBRARY_PATH"] = (
        f"{SDK}:{SDK}/libarm64/spinvcore:{SDK}/libarm64/opencv/lib"
    )
    return e


def capture_ocf(out_path, exposure_us):
    """Call capture_one binary; raises RuntimeError on failure."""
    ret = subprocess.call(
        [CAPTURE_ONE, OCFBS, out_path, str(exposure_us)],
        env=_sdk_env()
    )
    if ret != 0:
        raise RuntimeError(f"capture_one failed (exit={ret})")
```

- [ ] **Step 2: 實作 `extract_gray`**

```python
def extract_gray(ocf_path, gray_png_path):
    """Convert OCF → color PNG via ocf_to_png, then save as grayscale."""
    tmp_png = ocf_path + "_preview.png"
    ret = subprocess.call([OCF_TO_PNG, ocf_path, tmp_png, OCFBS], env=_sdk_env())
    if ret != 0:
        raise RuntimeError(f"ocf_to_png failed (exit={ret})")
    img = cv2.imread(tmp_png)
    if img is None:
        raise RuntimeError(f"Cannot read preview: {tmp_png}")
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    cv2.imwrite(gray_png_path, gray)
    os.remove(tmp_png)
```

- [ ] **Step 3: 實作 `run_segmentation`**

```python
def run_segmentation(session_dir):
    """Run fast_seg_agtron.py; returns detected bean count.
    beans_rois.json is a plain list: [{"id":1,"x0":..,"y0":..,"x1":..,"y1":..}, ...]
    """
    ret = subprocess.call([sys.executable, FAST_SEG, session_dir])
    if ret != 0:
        raise RuntimeError("fast_seg_agtron.py failed")
    rois_path = os.path.join(session_dir, "beans_rois.json")
    with open(rois_path) as f:
        data = json.load(f)  # list, not dict
    return len(data)
```

- [ ] **Step 4: 實作 `run_spec_fingerprint`**

```python
def run_spec_fingerprint(ocf_path, out_csv, session_dir):
    """Run spec_fingerprint binary with existing labelmap from session_dir."""
    rois = os.path.join(session_dir, "beans_rois.json")
    lmap = os.path.join(session_dir, "beans_labelmap.png")
    ret = subprocess.call(
        [SPEC_FINGERPRINT, OCFBS, OCFDB, ocf_path, rois, out_csv, lmap],
        env=_sdk_env()
    )
    if ret != 0:
        raise RuntimeError(f"spec_fingerprint failed (exit={ret})")
```

- [ ] **Step 5: 確認語法無誤**

```bash
cd /home/kyle/KyleClaude && python3 -c "import uv_mold_scan; print('OK')"
```

Expected: `OK`

- [ ] **Step 6: Commit**

```bash
cd /home/kyle/KyleClaude
git add uv_mold_scan.py
git commit -m "feat: add subprocess wrappers for capture/segmentation/spectrometry"
```

---

### Task 6: 視覺化輸出 (`save_report_csv`, `save_labeled_png`, `save_spectrum_plot`)

**Files:**
- Modify: `/home/kyle/KyleClaude/uv_mold_scan.py`
- Modify: `/home/kyle/KyleClaude/tests/test_uv_mold_scan.py`

- [ ] **Step 1: 寫 `save_report_csv` 測試**

```python
def test_save_report_csv(tmp_path):
    fl_score = {"bean_1": 2.0, "bean_2": 1.0}
    fl_norm  = {"bean_1": 0.5, "bean_2": 0.25}
    flags    = {"bean_1": "SUSPECT", "bean_2": "OK"}
    out = str(tmp_path / "report.csv")
    save_report_csv(fl_score, fl_norm, flags, out)

    with open(out) as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 2
    assert rows[0]["bean_id"]  == "bean_1"
    assert rows[0]["flag"]     == "SUSPECT"
    assert float(rows[0]["fl_norm"]) == pytest.approx(0.5, abs=1e-3)
    assert rows[1]["flag"] == "OK"
```

- [ ] **Step 2: 確認失敗**

```bash
cd /home/kyle/KyleClaude && python3 -m pytest tests/test_uv_mold_scan.py::test_save_report_csv -v
```

Expected: `FAILED`

- [ ] **Step 3: 實作 `save_report_csv`**

```python
def save_report_csv(fl_score, fl_norm, flags, out_path):
    with open(out_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["bean_id", "fl_score", "fl_norm", "flag"])
        for bid in sorted(fl_score.keys()):
            writer.writerow([
                bid,
                f"{fl_score[bid]:.4f}",
                f"{fl_norm[bid]:.4f}",
                flags.get(bid, "OK"),
            ])
```

- [ ] **Step 4: 確認通過**

```bash
cd /home/kyle/KyleClaude && python3 -m pytest tests/test_uv_mold_scan.py::test_save_report_csv -v
```

Expected: `1 passed`

- [ ] **Step 5: 實作 `save_labeled_png`**

```python
def save_labeled_png(ref_gray_path, rois_path, fl_norm, flags, out_path):
    img = cv2.imread(ref_gray_path)
    if img is None:
        raise RuntimeError(f"Cannot read: {ref_gray_path}")

    with open(rois_path) as f:
        rois_data = json.load(f)

    vals  = np.array(list(fl_norm.values()), dtype=float)
    v_min = vals.min()
    v_rng = vals.max() - v_min + 1e-6
    cmap  = cm.get_cmap("RdYlGn_r")   # green=low fluorescence, red=high

    for roi in rois_data:   # rois_data is a plain list
        bean_id = f"bean_{roi['id']}"
        if bean_id not in fl_norm:
            continue
        cx = int((roi["x0"] + roi["x1"]) / 2)
        cy = int((roi["y0"] + roi["y1"]) / 2)
        w  = roi["x1"] - roi["x0"]
        h  = roi["y1"] - roi["y0"]
        r  = max(10, int(np.sqrt(w * h / np.pi) * 0.8))
        norm_val = (fl_norm[bean_id] - v_min) / v_rng
        rgba     = cmap(norm_val)
        bgr      = (int(rgba[2]*255), int(rgba[1]*255), int(rgba[0]*255))

        thickness = 4 if flags.get(bean_id) == "SUSPECT" else 2
        cv2.circle(img, (cx, cy), r, bgr, thickness)
        label = f"{fl_norm[bean_id]:.2f}"
        if flags.get(bean_id) == "SUSPECT":
            label += "!"
        cv2.putText(img, label, (cx - 18, cy - r - 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.42, bgr, 1, cv2.LINE_AA)

    cv2.imwrite(out_path, img)
```

- [ ] **Step 6: 實作 `save_spectrum_plot`**

```python
def save_spectrum_plot(fl_signal, fl_norm, flags, out_path):
    all_bands = sorted(next(iter(fl_signal.values())).keys())

    suspect_ids = sorted(
        [b for b, f in flags.items() if f == "SUSPECT"],
        key=lambda b: fl_norm[b], reverse=True
    )[:3]
    normal_ids = [b for b, f in flags.items() if f == "OK"]

    fig, ax = plt.subplots(figsize=(9, 5))

    if normal_ids:
        matrix      = np.array([[fl_signal[b].get(nm, 0) for nm in all_bands] for b in normal_ids])
        median_spec = np.median(matrix, axis=0)
        ax.plot(all_bands, median_spec, color="steelblue", lw=1.5,
                label="Median normal", alpha=0.8)

    colors = ["crimson", "orangered", "darkorange"]
    for i, bid in enumerate(suspect_ids):
        vals = [fl_signal[bid].get(nm, 0) for nm in all_bands]
        ax.plot(all_bands, vals, color=colors[i % 3], lw=2,
                label=f"{bid} fl_norm={fl_norm[bid]:.3f} [SUSPECT]")

    ax.axvspan(410, 490, alpha=0.12, color="gold", label="Emission window 410–490nm")
    ax.set_xlabel("Wavelength (nm)")
    ax.set_ylabel("Fluorescence (UV_on − dark)")
    ax.set_title("UV 365nm Mold Scan — Suspect vs Normal Bean Spectra")
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(out_path, dpi=150)
    plt.close()
```

- [ ] **Step 7: 確認所有測試通過**

```bash
cd /home/kyle/KyleClaude && python3 -m pytest tests/test_uv_mold_scan.py -v
```

Expected: `9 passed`

- [ ] **Step 8: Commit**

```bash
cd /home/kyle/KyleClaude
git add uv_mold_scan.py tests/test_uv_mold_scan.py
git commit -m "feat: add visualization outputs (labeled PNG, spectrum plot, CSV)"
```

---

### Task 7: `main()` 互動主流程

**Files:**
- Modify: `/home/kyle/KyleClaude/uv_mold_scan.py` — 實作 `main()`

- [ ] **Step 1: 實作 `main()`**

替換 stub：

```python
def main():
    parser = argparse.ArgumentParser(description="UV 365nm mold fluorescence scan")
    parser.add_argument("--n-beans", type=int, default=None,
                        help="Expected bean count (informational only)")
    parser.add_argument("--exposure-uv", type=int, default=5000,
                        help="UV & dark capture exposure in microseconds (default: 5000)")
    args = parser.parse_args()

    ts          = datetime.now().strftime("%Y%m%d_%H%M%S")
    session_dir = os.path.expanduser(f"~/Desktop/UV_scan_{ts}")
    os.makedirs(session_dir, exist_ok=True)
    print(f"\n[UV SCAN] Session dir: {session_dir}\n")

    ref_qs   = os.path.join(session_dir, "ref.ocf")
    ref_gray = os.path.join(session_dir, "capture_2500us_gray.png")
    uv_qs    = os.path.join(session_dir, "uv_on.ocf")
    dark_qs  = os.path.join(session_dir, "dark.ocf")
    uv_csv   = os.path.join(session_dir, "uv_on_spec.csv")
    dark_csv = os.path.join(session_dir, "dark_spec.csv")
    rois     = os.path.join(session_dir, "beans_rois.json")
    out_img  = os.path.join(session_dir, "uv_mold_labeled.png")
    out_plot = os.path.join(session_dir, "uv_spectrum_plot.png")
    out_csv  = os.path.join(session_dir, "uv_report.csv")

    # ── Step 1: 白光參考拍攝 → 分割 ──────────────────────────────────────────
    input("[STEP 1/3] 白光開著，豆子擺好。按 Enter 拍分割參考圖...")
    print("  拍攝中...", flush=True)
    capture_ocf(ref_qs, 2500)
    print("  提取灰階...", flush=True)
    extract_gray(ref_qs, ref_gray)
    print("  分割豆子...", flush=True)
    n_detected = run_segmentation(session_dir)
    print(f"  偵測到 {n_detected} 顆豆子")
    if args.n_beans and abs(n_detected - args.n_beans) > 3:
        print(f"  [警告] 預期 {args.n_beans} 顆，實際 {n_detected} 顆，請確認擺放")

    # ── Step 2: UV 拍攝 ───────────────────────────────────────────────────────
    input(f"\n[STEP 2/3] 關掉白光，開 365nm UV LED。按 Enter（曝光 {args.exposure_uv}us）...")
    print("  拍攝中...", flush=True)
    capture_ocf(uv_qs, args.exposure_uv)
    print("  提取光譜...", flush=True)
    run_spec_fingerprint(uv_qs, uv_csv, session_dir)
    print("  完成")

    # ── Step 3: 暗場拍攝 ──────────────────────────────────────────────────────
    input(f"\n[STEP 3/3] 關掉所有光源。按 Enter（曝光 {args.exposure_uv}us）...")
    print("  拍攝中...", flush=True)
    capture_ocf(dark_qs, args.exposure_uv)
    print("  提取光譜...", flush=True)
    run_spec_fingerprint(dark_qs, dark_csv, session_dir)
    print("  完成")

    # ── 分析 ──────────────────────────────────────────────────────────────────
    print("\n[分析] 計算螢光訊號...")
    uv_spec   = load_spec_csv(uv_csv)
    dark_spec = load_spec_csv(dark_csv)
    fl_signal = compute_fluorescence(uv_spec, dark_spec)
    fl_score, fl_norm = compute_fl_score(fl_signal, uv_spec)
    flags     = flag_suspects(fl_norm)

    n_suspect = sum(1 for f in flags.values() if f == "SUSPECT")
    print(f"  {n_detected} 顆豆子中標記 {n_suspect} 顆可疑 (threshold: mean + 1.5σ)")
    for bid in sorted(fl_norm, key=lambda b: fl_norm[b], reverse=True)[:5]:
        mark = "  *** SUSPECT" if flags[bid] == "SUSPECT" else ""
        print(f"  {bid}: fl_norm={fl_norm[bid]:.4f}{mark}")

    # ── 輸出 ──────────────────────────────────────────────────────────────────
    print("\n[輸出] 產生結果...")
    save_labeled_png(ref_gray, rois, fl_norm, flags, out_img)
    save_spectrum_plot(fl_signal, fl_norm, flags, out_plot)
    save_report_csv(fl_score, fl_norm, flags, out_csv)

    print(f"\n[完成] 結果存在 {session_dir}/")
    print(f"  uv_mold_labeled.png")
    print(f"  uv_spectrum_plot.png")
    print(f"  uv_report.csv")
```

- [ ] **Step 2: 確認語法 + 所有測試仍通過**

```bash
cd /home/kyle/KyleClaude && python3 -c "import uv_mold_scan; print('import OK')"
python3 -m pytest tests/test_uv_mold_scan.py -v
```

Expected: `import OK` + `9 passed`

- [ ] **Step 3: 確認 --help 輸出正確**

```bash
cd /home/kyle/KyleClaude && python3 uv_mold_scan.py --help
```

Expected:
```
usage: uv_mold_scan.py [-h] [--n-beans N] [--exposure-uv US]
...
```

- [ ] **Step 4: Commit**

```bash
cd /home/kyle/KyleClaude
git add uv_mold_scan.py
git commit -m "feat: implement main() interactive capture flow"
```

---

### Task 8: 最終驗收 + 手動煙霧測試指引

**Files:**
- 無修改，僅驗收

- [ ] **Step 1: 執行完整測試套件**

```bash
cd /home/kyle/KyleClaude && python3 -m pytest tests/test_uv_mold_scan.py -v
```

Expected: `9 passed, 0 failed`

- [ ] **Step 2: 手動煙霧測試（需要相機 + LED）**

```bash
cd /home/kyle/KyleClaude && python3 uv_mold_scan.py --n-beans 20 --exposure-uv 5000
```

逐步操作：
1. STEP 1：白光開，豆子擺在 DiFluid 豆碟上，按 Enter
   - 確認輸出「偵測到 N 顆豆子」（N 應合理）
2. STEP 2：關白光、開 365nm UV，按 Enter
   - 若畫面一片黑（曝光不足），Ctrl+C 後改用 `--exposure-uv 10000` 重試
3. STEP 3：關所有光，按 Enter
4. 確認 `~/Desktop/UV_scan_<ts>/` 中有三個輸出檔
5. 開啟 `uv_mold_labeled.png`：確認豆子上有彩色圓圈與數值
6. 開啟 `uv_spectrum_plot.png`：確認有光譜曲線與 410-490nm 標示區間

- [ ] **Step 3: 最終 commit**

```bash
cd /home/kyle/KyleClaude
git add docs/superpowers/plans/2026-05-21-uv-mold-scan.md
git commit -m "docs: add UV mold scan implementation plan"
```

---

## 附記：曝光調整指引

| 狀況 | 調整 |
|------|------|
| UV 圖像全黑（過暗） | `--exposure-uv 10000` |
| UV 圖像飽和（過亮） | `--exposure-uv 2500` |
| 螢光訊號雜訊過大 | 確認暗室環境，排除環境光漏光 |
| 所有豆分數相近 | 螢光訊號微弱，考慮補充真實陽性樣品 |
