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
    save_scatter_plot, save_cross_labeled_png,
    save_report_csv as save_cross_report_csv,
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
    rois_path   = os.path.join(session_dir, "beans_rois.json")

    # ── Step 1：白光灰階參考 → 分割 ──────────────────────────────────────────
    input("[STEP 1/4] 白光開，UV 關。豆子擺好。按 Enter 拍攝...")
    print("  拍攝灰階參考...", flush=True)
    try:
        capture_qs(ref_qs, EXPOSURE_WHITE)
        extract_gray(ref_qs, ref_gray)
        n = run_segmentation(session_dir)
        print(f"  偵測到 {n} 顆豆子")
    except RuntimeError as e:
        print(f"[錯誤] 步驟 1 失敗：{e}")
        sys.exit(1)

    # ── Step 2：白光 FPI 全波段掃描 → Mahalanobis ─────────────────────────────
    input(f"\n[STEP 2/4] 白光保持開啟。按 Enter 拍 FPI 全波段（{EXPOSURE_WHITE}us）...")
    print("  FPI 掃描中...", flush=True)
    try:
        capture_qs(white_qs, EXPOSURE_WHITE)
        run_spec_fingerprint(white_qs, white_csv, session_dir)
        white_spec = load_spec_csv(white_csv)
        mahal = compute_mahalanobis(white_spec)
        print(f"  Mahalanobis 完成，{len(mahal)} 顆")
    except RuntimeError as e:
        print(f"[錯誤] 步驟 2 失敗：{e}")
        sys.exit(1)

    # ── Step 3：UV 螢光拍攝 ───────────────────────────────────────────────────
    input(f"\n[STEP 3/4] 關白光，開 UV 365nm，蓋上遮光盒。按 Enter（{EXPOSURE_UV}us）...")
    print("  UV 拍攝中...", flush=True)
    try:
        capture_qs(uv_qs, EXPOSURE_UV)
        run_spec_fingerprint(uv_qs, uv_csv, session_dir)
    except RuntimeError as e:
        print(f"[錯誤] 步驟 3 失敗：{e}")
        sys.exit(1)

    # ── Step 4：暗場 ──────────────────────────────────────────────────────────
    input(f"\n[STEP 4/4] 關所有光。按 Enter 拍暗場（{EXPOSURE_UV}us）...")
    print("  暗場拍攝中...", flush=True)
    try:
        capture_qs(dark_qs, EXPOSURE_UV)
        run_spec_fingerprint(dark_qs, dark_csv, session_dir)
    except RuntimeError as e:
        print(f"[錯誤] 步驟 4 失敗：{e}")
        sys.exit(1)

    # ── 交叉分析 ──────────────────────────────────────────────────────────────
    print("\n[分析] 計算螢光 + 交叉驗證...", flush=True)
    uv_spec   = load_spec_csv(uv_csv)
    dark_spec = load_spec_csv(dark_csv)
    fl_signal = compute_fluorescence(uv_spec, dark_spec)
    _, fl_norm = compute_fl_score(fl_signal, uv_spec)
    suspects  = cross_validate(mahal, fl_norm, sigma=args.sigma)

    missing = [bid for bid in suspects if bid not in mahal or bid not in fl_norm]
    if missing:
        print(f"  [警告] {len(missing)} 顆豆子在兩個感測器間不對齊: {missing[:3]}")

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
    save_scatter_plot(mahal, fl_norm, suspects, scatter_png, sigma=args.sigma)
    if not os.path.exists(rois_path):
        print("[警告] ROI 檔案不存在，跳過 labeled.png")
    else:
        save_cross_labeled_png(ref_gray, rois_path, mahal, fl_norm, suspects, labeled_png)
    save_cross_report_csv(mahal, fl_norm, suspects, report_csv)

    print(f"\n[完成] {session_dir}/")
    print(f"  scatter.png    ← 二維散點圖（Mahalanobis vs fl_norm）")
    print(f"  labeled.png    ← 豆子位置標注（紅=HIGH 橘=MID）")
    print(f"  report.csv     ← 每顆豆完整數據")
    if n_high:
        print(f"\n  *** {n_high} 顆 HIGH 可疑豆，請分離並觀察 48 小時 ***")


if __name__ == "__main__":
    main()
