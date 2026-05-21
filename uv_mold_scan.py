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
    pass  # Task 4

def flag_suspects(fl_norm, sigma=1.5):
    pass  # Task 4


# ── Subprocess wrappers ────────────────────────────────────────────────────────

def _sdk_env():
    pass  # Task 5

def capture_qs(out_path, exposure_us):
    pass  # Task 5

def extract_gray(qs_path, gray_png_path):
    pass  # Task 5

def run_segmentation(session_dir):
    pass  # Task 5

def run_spec_fingerprint(qs_path, out_csv, session_dir):
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
