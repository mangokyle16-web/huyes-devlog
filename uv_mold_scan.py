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

def save_labeled_png(ref_gray_path, rois_path, fl_norm, flags, out_path):
    img = cv2.imread(ref_gray_path)
    if img is None:
        raise RuntimeError(f"Cannot read: {ref_gray_path}")

    with open(rois_path) as f:
        rois_data = json.load(f)   # plain list

    vals  = np.array(list(fl_norm.values()), dtype=float)
    v_min = vals.min()
    v_rng = vals.max() - v_min + 1e-6
    cmap  = cm.get_cmap("RdYlGn_r")   # green=low fluorescence, red=high

    for roi in rois_data:
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


# ── Main ───────────────────────────────────────────────────────────────────────

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

    ref_qs   = os.path.join(session_dir, "ref.qs")
    ref_gray = os.path.join(session_dir, "capture_2500us_gray.png")
    uv_qs    = os.path.join(session_dir, "uv_on.qs")
    dark_qs  = os.path.join(session_dir, "dark.qs")
    uv_csv   = os.path.join(session_dir, "uv_on_spec.csv")
    dark_csv = os.path.join(session_dir, "dark_spec.csv")
    rois     = os.path.join(session_dir, "beans_rois.json")
    out_img  = os.path.join(session_dir, "uv_mold_labeled.png")
    out_plot = os.path.join(session_dir, "uv_spectrum_plot.png")
    out_csv  = os.path.join(session_dir, "uv_report.csv")

    # ── Step 1: 白光參考拍攝 → 分割 ──────────────────────────────────────────
    input("[STEP 1/3] 白光開著，豆子擺好。按 Enter 拍分割參考圖...")
    print("  拍攝中...", flush=True)
    capture_qs(ref_qs, 2500)
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
    capture_qs(uv_qs, args.exposure_uv)
    print("  提取光譜...", flush=True)
    run_spec_fingerprint(uv_qs, uv_csv, session_dir)
    print("  完成")

    # ── Step 3: 暗場拍攝 ──────────────────────────────────────────────────────
    input(f"\n[STEP 3/3] 關掉所有光源。按 Enter（曝光 {args.exposure_uv}us）...")
    print("  拍攝中...", flush=True)
    capture_qs(dark_qs, args.exposure_uv)
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


if __name__ == "__main__":
    main()
