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
    for bid in bean_ids:
        if set(spec[bid].keys()) != set(all_nms):
            raise ValueError(f"{bid} has different wavelengths from other beans")
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
    if len(common) == 0:
        return {}
    if len(common) == 1:
        return {common[0]: "LOW"}

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


def save_scatter_plot(mahal: dict, fl_norm: dict, suspects: dict, out_path: str, sigma: float = 1.5):
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
    ax.axvline(m_arr.mean() + sigma * m_arr.std(), color="gray", ls="--", lw=0.8, alpha=0.6)
    ax.axhline(f_arr.mean() + sigma * f_arr.std(), color="gray", ls="--", lw=0.8, alpha=0.6)
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
    if not cv2.imwrite(out_path, img):
        raise RuntimeError(f"cv2.imwrite failed: {out_path}")
