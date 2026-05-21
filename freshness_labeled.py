"""
重建 ROI + 疊加新鮮度指數到豆子影像
"""
import cv2
import numpy as np
import pandas as pd
import json, os

# ── 路徑 ──────────────────────────────────────────────────
IMG_PATH = "/home/kyle/Desktop/GigaImage_20260413_174159/capture_001_5000us.png"
CSV_PATH = "/home/kyle/Desktop/GigaImage_20260413_174159/spec_fingerprint_20beans.csv"
OUT_DIR  = "/home/kyle/Desktop/freshness_analysis"
os.makedirs(OUT_DIR, exist_ok=True)

# ── 載入新鮮度分數 ────────────────────────────────────────
df = pd.read_csv(CSV_PATH, index_col=0)
R_blue = (df.loc[450] + df.loc[470]) / 2.0
R_nir  = (df.loc[890] + df.loc[910]) / 2.0
FI     = R_blue / R_nir

fi_norm    = 1.0 - (FI - FI.min()) / (FI.max() - FI.min())
NIR_slope  = df.loc[910] - df.loc[750]
slope_norm = (NIR_slope - NIR_slope.min()) / (NIR_slope.max() - NIR_slope.min())
blue_depth = 1.0 - (R_blue / df.loc[510])
depth_norm = (blue_depth - blue_depth.min()) / (blue_depth.max() - blue_depth.min())
fresh_score = (fi_norm * 0.5 + slope_norm * 0.3 + depth_norm * 0.2) * 100

scores = {i+1: fresh_score[f"bean_{i+1}"] for i in range(20)}
fi_vals = {i+1: FI[f"bean_{i+1}"] for i in range(20)}

# ── 重建分割 ──────────────────────────────────────────────
img_raw = cv2.imread(IMG_PATH, cv2.IMREAD_GRAYSCALE)
assert img_raw is not None, f"Cannot read {IMG_PATH}"

# 兩段式：t65 找位置，t80 精細輪廓
_, th65 = cv2.threshold(img_raw, 65, 255, cv2.THRESH_BINARY_INV)
_, th80 = cv2.threshold(img_raw, 80, 255, cv2.THRESH_BINARY_INV)

def find_beans(gray, thresh, min_area=800, max_area=8000):
    _, bw = cv2.threshold(gray, thresh, 255, cv2.THRESH_BINARY_INV)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5,5))
    bw = cv2.morphologyEx(bw, cv2.MORPH_OPEN, kernel, iterations=2)
    num, labels, stats, centroids = cv2.connectedComponentsWithStats(bw)
    return [{"cx": int(centroids[j][0]), "cy": int(centroids[j][1]),
             "x": int(stats[j, cv2.CC_STAT_LEFT]),
             "y": int(stats[j, cv2.CC_STAT_TOP]),
             "w": int(stats[j, cv2.CC_STAT_WIDTH]),
             "h": int(stats[j, cv2.CC_STAT_HEIGHT])}
            for j in range(1, num)
            if min_area < stats[j, cv2.CC_STAT_AREA] < max_area]

# 完全沿用 mold_final.py 的兩段式方法
all_blobs = list(find_beans(img_raw, 80))
for b in find_beans(img_raw, 65):
    if not any(np.hypot(b["cx"]-fb["cx"], b["cy"]-fb["cy"]) < 30 for fb in all_blobs):
        all_blobs.append(b)
all_blobs.sort(key=lambda b: (round(b["cy"] / 120) * 120 + b["cx"] / 10000))
print(f"總 blobs: {len(all_blobs)}")

if len(all_blobs) != 20:
    print(f"警告：偵測到 {len(all_blobs)} 顆，預期 20 顆，請調整參數")

# ── 繪製 ROI + 新鮮度標籤 ─────────────────────────────────
# 用 10000us 彩色影像當底圖（如存在），否則用 5000us 灰階轉彩色
img_color_path = "/home/kyle/Desktop/GigaImage_20260413_174159/capture_000_10000us.png"
img_c = cv2.imread(img_color_path)
if img_c is None:
    img_c = cv2.cvtColor(img_raw, cv2.COLOR_GRAY2BGR)

# 縮放到相同尺寸
if img_c.shape[:2] != img_raw.shape[:2]:
    img_c = cv2.resize(img_c, (img_raw.shape[1], img_raw.shape[0]))

overlay = img_c.copy()

def score_to_bgr(score):
    """0=紅(老)  50=黃  100=綠(新鮮)"""
    r = int(max(0, min(255, 255 * (1 - score/100) * 2)))
    g = int(max(0, min(255, 255 * (score/100) * 2)))
    b = 30
    return (b, g, r)

for idx, b in enumerate(all_blobs):
    bean_id = idx + 1
    cx, cy = b["cx"], b["cy"]
    w, h = b["w"], b["h"]
    r = int(max(w, h) / 2 + 5)  # 圓半徑略大於豆子

    score = scores.get(bean_id, 50)
    fi    = fi_vals.get(bean_id, 0)
    color = score_to_bgr(score)

    # 畫圓圈
    cv2.circle(overlay, (cx, cy), r, color, 2)

    # 豆子編號（圓圈內上方）
    label = str(bean_id)
    fs = 0.45
    (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, fs, 1)
    cv2.putText(overlay, label,
                (cx - tw//2, cy - r + th + 2),
                cv2.FONT_HERSHEY_SIMPLEX, fs, (255,255,255), 2, cv2.LINE_AA)
    cv2.putText(overlay, label,
                (cx - tw//2, cy - r + th + 2),
                cv2.FONT_HERSHEY_SIMPLEX, fs, color, 1, cv2.LINE_AA)

    # 分數（圓圈下方）
    score_str = f"{score:.0f}"
    (sw, sh), _ = cv2.getTextSize(score_str, cv2.FONT_HERSHEY_SIMPLEX, 0.4, 1)
    cv2.putText(overlay, score_str,
                (cx - sw//2, cy + r + sh + 2),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0,0,0), 3, cv2.LINE_AA)
    cv2.putText(overlay, score_str,
                (cx - sw//2, cy + r + sh + 2),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1, cv2.LINE_AA)

# ── 色條圖例 ──────────────────────────────────────────────
bar_h, bar_w = 15, 200
bar_x, bar_y = 10, overlay.shape[0] - 35
for i in range(bar_w):
    s = i / bar_w * 100
    cv2.line(overlay, (bar_x+i, bar_y), (bar_x+i, bar_y+bar_h), score_to_bgr(s), 1)
cv2.rectangle(overlay, (bar_x, bar_y), (bar_x+bar_w, bar_y+bar_h), (200,200,200), 1)
cv2.putText(overlay, "Old", (bar_x, bar_y-4),
            cv2.FONT_HERSHEY_SIMPLEX, 0.35, (80,80,255), 1)
cv2.putText(overlay, "Fresh", (bar_x+bar_w-28, bar_y-4),
            cv2.FONT_HERSHEY_SIMPLEX, 0.35, (80,200,80), 1)
cv2.putText(overlay, "Freshness Score", (bar_x+50, bar_y+bar_h+12),
            cv2.FONT_HERSHEY_SIMPLEX, 0.35, (220,220,220), 1)

# ── 儲存 ─────────────────────────────────────────────────
out_path = f"{OUT_DIR}/freshness_labeled.png"
cv2.imwrite(out_path, overlay)
print(f"\n已儲存：{out_path}")

# 也儲存 ROI JSON 到 /tmp（順便重建）
rois = []
for idx, b in enumerate(all_blobs):
    rois.append({"bean_id": idx+1, "cx": b["cx"], "cy": b["cy"],
                 "x": b["x"], "y": b["y"], "w": b["w"], "h": b["h"]})
with open("/tmp/beans_rois_new.json", "w") as f:
    json.dump([{k: int(v) if hasattr(v, 'item') else v for k, v in r.items()} for r in rois], f, indent=2)
print("ROI JSON 已重建：/tmp/beans_rois_new.json")
