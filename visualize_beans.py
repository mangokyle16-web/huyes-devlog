#!/usr/bin/env python3
"""
visualize_beans.py
產生標示圖：
  1. 全景圖（橢圓圈出所有豆子，HIGH/MED 特別標示）
  2. 高度懷疑豆子的放大圖
"""
import sys, os, json, csv
import numpy as np
import cv2
from PIL import Image, ImageDraw, ImageFont

SESSION_DIR = sys.argv[1] if len(sys.argv) > 1 else "/home/kyle/Desktop/GigaImage_20260503_011205"
OUT_DIR     = os.path.join(SESSION_DIR, "mold_result")
os.makedirs(OUT_DIR, exist_ok=True)

for _gn in ["capture_1250us_gray.png", "capture_2500us_gray.png", "capture_5000us_gray.png"]:
    GRAY_PNG = os.path.join(SESSION_DIR, _gn)
    if os.path.exists(GRAY_PNG):
        break
SPEC_CSV  = os.path.join(SESSION_DIR, "spec_raw.csv")
ROIS_JSON = os.path.join(SESSION_DIR, "beans_rois.json")
LMAP_PNG  = os.path.join(SESSION_DIR, "beans_labelmap.png")

# ── 讀取 ROI ──────────────────────────────────────────────────────────────────
with open(ROIS_JSON) as f:
    rois_list = json.load(f)
rois = {r["id"]: r for r in rois_list}

# ── 重跑異常分數（同 mold_analysis_51.py）────────────────────────────────────
bands_list, raw = [], {}
with open(SPEC_CSV) as f:
    reader = csv.DictReader(f)
    bkeys = [k for k in reader.fieldnames if k.startswith("bean_")]
    rows  = list(reader)
for bk in bkeys:
    bid = int(bk.split("_")[1])
    raw[bid] = np.array([float(row[bk]) for row in rows])
bands = np.array([int(float(row["wavelength_nm"])) for row in rows])
bean_ids = sorted(raw.keys())
X      = np.array([raw[bid] for bid in bean_ids])
X_mean = X.mean(axis=0)
U, s, Vt = np.linalg.svd(X - X_mean, full_matrices=False)
n_pc = min(6, len(bean_ids) - 1)
pc_scores = U[:, :n_pc] * s[:n_pc]
pc_mean   = pc_scores.mean(0)
pc_std    = pc_scores.std(0) + 1e-9
mahal     = np.sqrt(((pc_scores - pc_mean) / pc_std) ** 2).mean(1)

def band_idx(nm): return int(np.argmin(np.abs(bands - nm)))
uv_bands = [band_idx(nm) for nm in range(350, 460, 20)]
uv_mean  = X[:, uv_bands].mean(axis=1)
uv_z     = (uv_mean - uv_mean.mean()) / (uv_mean.std() + 1e-9)
def norm(v): return (v - v.min()) / (v.max() - v.min() + 1e-9)
score = norm(mahal) * 0.7 + norm(-uv_z) * 0.3
mean_s, std_s = score.mean(), score.std()
levels = {}
for i, bid in enumerate(bean_ids):
    if   score[i] > mean_s + 1.5 * std_s: levels[bid] = "HIGH"
    elif score[i] > mean_s + 0.8 * std_s: levels[bid] = "MED"
    else:                                   levels[bid] = "OK"

# ── 讀取影像和 label map ────────────────────────────────────────────────────────
img_gray = cv2.imread(GRAY_PNG)  # BGR
H, W = img_gray.shape[:2]
lmap = None
if os.path.exists(LMAP_PNG):
    lmap = np.array(Image.open(LMAP_PNG))

def get_ellipse(bid):
    """從 label map 擬合橢圓；fallback 用 bounding box。"""
    if lmap is not None:
        mask = (lmap == bid).astype(np.uint8) * 255
        pts  = cv2.findNonZero(mask)
        if pts is not None and len(pts) >= 5:
            try:
                return cv2.fitEllipse(pts)  # ((cx,cy),(ma,mb),angle)
            except cv2.error:
                pass
    # fallback：bounding box 轉橢圓
    r  = rois[bid]
    cx = (r["x0"] + r["x1"]) / 2.0
    cy = (r["y0"] + r["y1"]) / 2.0
    ma = float(r["x1"] - r["x0"])
    mb = float(r["y1"] - r["y0"])
    return ((cx, cy), (ma, mb), 0.0)

# ── 全景標示圖 ────────────────────────────────────────────────────────────────
vis = img_gray.copy()

color_bgr = {"HIGH": (0, 50, 255), "MED": (0, 165, 255), "OK": (0, 200, 80)}

for i, bid in enumerate(bean_ids):
    if bid not in rois:
        continue
    lv    = levels[bid]
    col   = color_bgr[lv]
    ellip = get_ellipse(bid)
    (cx, cy), (ma, mb), angle = ellip

    if lv == "HIGH":
        # 粗紅橢圓 + 外擴 15%
        axes_out = (int(ma * 0.57), int(mb * 0.57))
        cv2.ellipse(vis, (int(cx), int(cy)), axes_out, angle, 0, 360, col, 3)
        # 內層半透明填充（用 addWeighted 模擬）
        overlay = vis.copy()
        cv2.ellipse(overlay, (int(cx), int(cy)), axes_out, angle, 0, 360, col, -1)
        cv2.addWeighted(overlay, 0.12, vis, 0.88, 0, vis)
    elif lv == "MED":
        axes_out = (int(ma * 0.55), int(mb * 0.55))
        cv2.ellipse(vis, (int(cx), int(cy)), axes_out, angle, 0, 360, col, 2)
    else:
        axes_out = (int(ma * 0.52), int(mb * 0.52))
        cv2.ellipse(vis, (int(cx), int(cy)), axes_out, angle, 0, 360, col, 1)

    # 豆號文字
    label = str(bid)
    font  = cv2.FONT_HERSHEY_SIMPLEX
    fs    = 0.58 if lv == "HIGH" else 0.45
    fw    = 2    if lv == "HIGH" else 1
    (tw, th), _ = cv2.getTextSize(label, font, fs, fw)
    tx = int(cx) - tw // 2
    ty = int(cy) + th // 2
    cv2.rectangle(vis, (tx - 2, ty - th - 2), (tx + tw + 2, ty + 2), (0, 0, 0), -1)
    cv2.putText(vis, label, (tx, ty), font, fs, col, fw, cv2.LINE_AA)

# 圖例
legend_y = 20
for lv, col in color_bgr.items():
    count = sum(1 for b in bean_ids if levels[b] == lv)
    cv2.ellipse(vis, (20, legend_y + 10), (12, 8), 0, 0, 360, col,
                3 if lv == "HIGH" else (2 if lv == "MED" else 1))
    cv2.putText(vis, f"{lv} ({count})", (38, legend_y + 15),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, col, 2, cv2.LINE_AA)
    legend_y += 30

out_overview = os.path.join(OUT_DIR, "overview_labeled.png")
cv2.imwrite(out_overview, vis)
print(f"全景圖 → {out_overview}")

# ── HIGH 豆子放大圖 ───────────────────────────────────────────────────────────
high_beans = [(i, bid) for i, bid in enumerate(bean_ids) if levels[bid] == "HIGH"]
print(f"\nHIGH 豆子: {[bid for _, bid in high_beans]}")

pad  = 70
crops = []
for rank, (i, bid) in enumerate(sorted(high_beans, key=lambda x: -score[bean_ids.index(x[1])])):
    r  = rois[bid]
    x0 = max(0, r["x0"] - pad);  y0 = max(0, r["y0"] - pad)
    x1 = min(W, r["x1"] + pad);  y1 = min(H, r["y1"] + pad)
    crop = vis[y0:y1, x0:x1].copy()

    title   = f"Bean {bid} [HIGH]  Mahal={mahal[i]:.3f}  UV_z={uv_z[i]:+.2f}"
    title_h = 36
    banner  = np.zeros((title_h, crop.shape[1], 3), dtype=np.uint8)
    banner[:] = (30, 30, 30)
    cv2.putText(banner, title, (6, 24),
                cv2.FONT_HERSHEY_SIMPLEX, 0.62, (0, 80, 255), 2, cv2.LINE_AA)
    crops.append(np.vstack([banner, crop]))

if crops:
    max_w = max(c.shape[1] for c in crops)
    crops_padded = []
    for c in crops:
        if c.shape[1] < max_w:
            pad_r = np.zeros((c.shape[0], max_w - c.shape[1], 3), dtype=np.uint8)
            c = np.hstack([c, pad_r])
        crops_padded.append(c)

    max_h = max(c.shape[0] for c in crops_padded)
    crops_same_h = []
    for c in crops_padded:
        if c.shape[0] < max_h:
            pad_b = np.zeros((max_h - c.shape[0], c.shape[1], 3), dtype=np.uint8)
            c = np.vstack([c, pad_b])
        crops_same_h.append(c)

    n_col = 2
    rows_imgs = []
    for r_idx in range(0, len(crops_same_h), n_col):
        row_imgs = crops_same_h[r_idx:r_idx + n_col]
        if len(row_imgs) < n_col:
            row_imgs.append(np.zeros_like(row_imgs[0]))
        rows_imgs.append(np.hstack(row_imgs))

    combined = np.vstack(rows_imgs)
    out_high = os.path.join(OUT_DIR, "high_beans_zoom.png")
    cv2.imwrite(out_high, combined)
    print(f"HIGH 放大圖 → {out_high}")

print("\n完成！")
