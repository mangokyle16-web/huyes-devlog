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
QSBS     = "/home/kyle/KyleClaude/camera_new.qsbs"
QSDB     = "/home/kyle/KyleClaude/db_std.qsdb"
FAST_SEG = "/home/kyle/KyleClaude/fast_seg_agtron.py"
SDK      = "/home/kyle/KyleClaude/sdk_extract/linux-sdk-arm64/qssdk-20250817"

CAPTURE_ONE      = os.path.join(BUILD, "capture_one")
QS_TO_PNG        = os.path.join(BUILD, "qs_to_png")
SPEC_FINGERPRINT = os.path.join(BUILD, "spec_fingerprint")

# ── Analysis constants ─────────────────────────────────────────────────────────
FL_BANDS    = [410, 430, 450, 470, 490]  # aflatoxin B1 emission region
UV_REF_BAND = 350                        # reflected UV band for normalization


# ── Pure analysis functions (unit-testable) ────────────────────────────────────

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


# ── Subprocess wrappers ────────────────────────────────────────────────────────

def _sdk_env():
    e = os.environ.copy()
    e["LD_LIBRARY_PATH"] = (
        f"{SDK}:{SDK}/libarm64/spinvcore:{SDK}/libarm64/opencv/lib"
    )
    return e

def capture_qs(out_path, exposure_us):
    """Call capture_one binary; raises RuntimeError on failure."""
    ret = subprocess.call(
        [CAPTURE_ONE, QSBS, out_path, str(exposure_us)],
        env=_sdk_env()
    )
    if ret != 0:
        raise RuntimeError(f"capture_one failed (exit={ret})")

def extract_gray(qs_path, gray_png_path):
    """Convert QS → color PNG via qs_to_png, then save as grayscale."""
    tmp_png = qs_path + "_preview.png"
    ret = subprocess.call([QS_TO_PNG, qs_path, tmp_png, QSBS], env=_sdk_env())
    if ret != 0:
        raise RuntimeError(f"qs_to_png failed (exit={ret})")
    img = cv2.imread(tmp_png)
    if img is None:
        raise RuntimeError(f"Cannot read preview: {tmp_png}")
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    cv2.imwrite(gray_png_path, gray)
    os.remove(tmp_png)

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

def run_spec_fingerprint(qs_path, out_csv, session_dir):
    """Run spec_fingerprint binary with existing labelmap from session_dir."""
    rois = os.path.join(session_dir, "beans_rois.json")
    lmap = os.path.join(session_dir, "beans_labelmap.png")
    ret = subprocess.call(
        [SPEC_FINGERPRINT, QSBS, QSDB, qs_path, rois, out_csv, lmap],
        env=_sdk_env()
    )
    if ret != 0:
        raise RuntimeError(f"spec_fingerprint failed (exit={ret})")


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
