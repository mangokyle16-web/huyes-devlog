#!/usr/bin/env python3
"""
grind_analysis.py <image_path> <output_dir> [--px-per-mm FLOAT]

Detects coffee grind particles via Otsu threshold + watershed.
Reads optional calibration from ~/KyleClaude/grind_calibration.json.
Saves: grind_labeled.png, grind_histogram.png, grind_result.json
"""
import sys, os, json, math
import numpy as np
import cv2

# ── Args ──────────────────────────────────────────────────
img_path = sys.argv[1] if len(sys.argv) > 1 else None
out_dir  = sys.argv[2] if len(sys.argv) > 2 else os.path.dirname(img_path)
px_per_mm_arg = None
for i, a in enumerate(sys.argv):
    if a == '--px-per-mm' and i + 1 < len(sys.argv):
        px_per_mm_arg = float(sys.argv[i + 1])

# ── Calibration ───────────────────────────────────────────
CAL_PATH = "/home/kyle/KyleClaude/grind_calibration.json"
if px_per_mm_arg is not None:
    px_per_mm  = px_per_mm_arg
    calibrated = True
elif os.path.exists(CAL_PATH):
    with open(CAL_PATH) as f:
        cal = json.load(f)
    px_per_mm  = cal.get("px_per_mm")
    calibrated = px_per_mm is not None
else:
    px_per_mm  = None
    calibrated = False

unit = "µm" if calibrated else "px"
print(f"[grind] calibrated={calibrated}  px_per_mm={px_per_mm}  unit={unit}", flush=True)

# ── Load image ────────────────────────────────────────────
img = cv2.imread(img_path, cv2.IMREAD_GRAYSCALE)
if img is None:
    print(f"[grind] Cannot load {img_path}", flush=True)
    sys.exit(1)
H, W = img.shape
print(f"[grind] image {W}x{H}  mean={img.mean():.1f}", flush=True)

# ── Segment ───────────────────────────────────────────────
blurred = cv2.GaussianBlur(img, (5, 5), 0)

# Auto polarity: bright background → particles are darker
inv = blurred.mean() > 128
flags = cv2.THRESH_OTSU | (cv2.THRESH_BINARY_INV if inv else cv2.THRESH_BINARY)
_, binary = cv2.threshold(blurred, 0, 255, flags)

kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=2)
binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN,  kernel, iterations=1)

# Watershed to split touching particles
dist = cv2.distanceTransform(binary, cv2.DIST_L2, 5)
_, fg = cv2.threshold(dist, 0.45 * dist.max(), 255, 0)
fg = fg.astype(np.uint8)
bg = cv2.dilate(binary, kernel, iterations=3)
unknown = cv2.subtract(bg, fg)

_, markers = cv2.connectedComponents(fg)
markers += 1
markers[unknown == 255] = 0
img_bgr = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
markers  = cv2.watershed(img_bgr, markers)

ws_mask   = (markers > 1).astype(np.uint8) * 255
contours, _ = cv2.findContours(ws_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

# ── Filter contours by area ───────────────────────────────
# 4 px–200 px equivalent diameter range
MIN_D_PX, MAX_D_PX = 4, 200
min_area = math.pi * (MIN_D_PX / 2) ** 2
max_area = math.pi * (MAX_D_PX / 2) ** 2

diams_px = []
valid    = []
for cnt in contours:
    area = cv2.contourArea(cnt)
    if area < min_area or area > max_area:
        continue
    diams_px.append(2.0 * math.sqrt(area / math.pi))
    valid.append(cnt)

n = len(diams_px)
print(f"[grind] {n} particles detected", flush=True)

if n == 0:
    print("[grind] No particles found — check image contrast", flush=True)
    sys.exit(1)

diams = np.array(diams_px)
if calibrated and px_per_mm:
    diams = diams * (1000.0 / px_per_mm)   # px → µm

d10  = float(np.percentile(diams, 10))
d50  = float(np.percentile(diams, 50))
d90  = float(np.percentile(diams, 90))
dmn  = float(np.mean(diams))
print(f"[grind] D10={d10:.1f} D50={d50:.1f} D90={d90:.1f} Mean={dmn:.1f} {unit}", flush=True)

# ── Labeled image ─────────────────────────────────────────
labeled = img_bgr.copy()
for i, cnt in enumerate(valid):
    d = diams[i]
    # blue=fine  green=medium  red=coarse
    if   d < d50 * 0.70: color = (200,  80,  30)
    elif d > d50 * 1.40: color = ( 30,  60, 220)
    else:                 color = ( 30, 180,  60)
    (cx, cy), r = cv2.minEnclosingCircle(cnt)
    cv2.circle(labeled, (int(cx), int(cy)), max(1, int(r)), color, 1, cv2.LINE_AA)

for i, (txt, col) in enumerate([
    (f"D10: {d10:.0f} {unit}",  (200, 200,  80)),
    (f"D50: {d50:.0f} {unit}",  ( 80, 220,  80)),
    (f"D90: {d90:.0f} {unit}",  ( 80, 140, 220)),
    (f"N = {n}",                 (200, 200, 200)),
]):
    y = 24 + i * 24
    cv2.putText(labeled, txt, (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,0,0),   3, cv2.LINE_AA)
    cv2.putText(labeled, txt, (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, col,        1, cv2.LINE_AA)

cv2.imwrite(out_dir + "/grind_labeled.png", labeled)

# ── Histogram ─────────────────────────────────────────────
HH, WW = 480, 800
hist_img = np.full((HH, WW, 3), 26, dtype=np.uint8)

LPAD, RPAD, TPAD, BPAD = 70, 24, 36, 60
pw = WW - LPAD - RPAD
ph = HH - TPAD - BPAD

d_lo = max(0.0, diams.min() * 0.8)
d_hi = diams.max() * 1.2
N_BINS = 40
bins   = np.linspace(d_lo, d_hi, N_BINS + 1)
counts, _ = np.histogram(diams, bins=bins)
max_c = max(counts.max(), 1)

def xpx(d):
    return int(LPAD + (d - d_lo) / (d_hi - d_lo) * pw)

# Bars
bar_w = pw / N_BINS
for i, c in enumerate(counts):
    x0 = int(LPAD + i * bar_w)
    x1 = int(LPAD + (i + 1) * bar_w) - 1
    bh = int(c / max_c * ph)
    cv2.rectangle(hist_img, (x0, TPAD + ph - bh), (x1, TPAD + ph),
                  (80, 130, 200), -1)

# D10 / D50 / D90 lines
for d_val, lbl, clr in [
    (d10, f"D10={d10:.0f}", (200, 200, 80)),
    (d50, f"D50={d50:.0f}", ( 80, 220, 80)),
    (d90, f"D90={d90:.0f}", ( 80, 140, 220)),
]:
    xd = xpx(d_val)
    if LPAD <= xd <= LPAD + pw:
        cv2.line(hist_img, (xd, TPAD), (xd, TPAD + ph), clr, 2, cv2.LINE_AA)
        cv2.putText(hist_img, lbl, (xd + 3, TPAD + 15),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.40, clr, 1, cv2.LINE_AA)

# Frame + ticks
cv2.rectangle(hist_img, (LPAD, TPAD), (LPAD + pw, TPAD + ph), (80, 80, 80), 1)
for i in range(7):
    d_t = d_lo + i * (d_hi - d_lo) / 6
    xt  = xpx(d_t)
    cv2.line(hist_img, (xt, TPAD + ph), (xt, TPAD + ph + 5), (120, 120, 120), 1)
    cv2.putText(hist_img, f"{d_t:.0f}", (xt - 14, TPAD + ph + 18),
                cv2.FONT_HERSHEY_SIMPLEX, 0.32, (180, 180, 180), 1, cv2.LINE_AA)

# Labels
cv2.putText(hist_img, f"Particle Diameter ({unit})",
            (LPAD + pw // 2 - 70, HH - 8),
            cv2.FONT_HERSHEY_SIMPLEX, 0.46, (200, 200, 200), 1, cv2.LINE_AA)
cv2.putText(hist_img, "Count", (4, TPAD + ph // 2),
            cv2.FONT_HERSHEY_SIMPLEX, 0.40, (200, 200, 200), 1, cv2.LINE_AA)
cv2.putText(hist_img, f"Grind Size Distribution   N={n}",
            (LPAD, TPAD - 10),
            cv2.FONT_HERSHEY_SIMPLEX, 0.52, (220, 220, 220), 1, cv2.LINE_AA)

cv2.imwrite(out_dir + "/grind_histogram.png", hist_img)

# ── JSON result ───────────────────────────────────────────
result = {
    "n_particles": n,
    "d10": round(d10, 1),
    "d50": round(d50, 1),
    "d90": round(d90, 1),
    "d_mean": round(dmn, 1),
    "unit": unit,
    "calibrated": calibrated,
    "px_per_mm": px_per_mm,
}
with open(out_dir + "/grind_result.json", "w") as f:
    json.dump(result, f, indent=2)
print(json.dumps(result), flush=True)
