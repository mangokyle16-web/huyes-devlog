#!/usr/bin/env python3
"""
fast_seg_agtron.py  —  OpenCV-based fast bean segmentation for Agtron path
Usage: python3 fast_seg_agtron.py <session_dir>

Reads:  capture_2500us_gray.png, cylinder_mask.json (global or session)
Writes: beans_rois.json, beans_labelmap.png
Output: {"bean_count": N} on stdout

~0.5s on Pi5 vs FastSAM's 14-20s.
Sufficient for Agtron ndiff calculation — doesn't need perfect per-bean boundaries.
"""
import sys, os, json, time
import numpy as np
import cv2

t0 = time.time()

sdir = sys.argv[1] if len(sys.argv) > 1 else "."
gray_path  = os.path.join(sdir, "capture_2500us_gray.png")
rois_path  = os.path.join(sdir, "beans_rois.json")
lmap_path  = os.path.join(sdir, "beans_labelmap.png")

# ── Load gray image ───────────────────────────────────────────────────────────
img = cv2.imread(gray_path, cv2.IMREAD_GRAYSCALE)
if img is None:
    print(json.dumps({"bean_count": 0, "error": "cannot load gray image"}), flush=True)
    sys.exit(1)

H, W = img.shape

# ── Load cylinder mask ────────────────────────────────────────────────────────
cyl_json = os.path.join(sdir, "cylinder_mask.json")
if not os.path.exists(cyl_json):
    cyl_json = "/home/kyle/KyleClaude/cylinder_mask.json"

cx, cy, cr = W / 2, H / 2, min(W, H) * 0.45  # defaults
if os.path.exists(cyl_json):
    c = json.load(open(cyl_json))
    # Scale cylinder params from JSON resolution to current image resolution
    sx = W / c.get("image_w", W)
    sy = H / c.get("image_h", H)
    cx = c["cx"] * sx
    cy = c["cy"] * sy
    cr = c["r"] * min(sx, sy)

# Build cylinder mask
Y, X = np.mgrid[0:H, 0:W]
cyl_mask = ((X - cx)**2 + (Y - cy)**2) <= cr**2

# ── Detect beans (dark objects on lighter background) ─────────────────────────
# Slight blur to suppress noise
blurred = cv2.GaussianBlur(img, (7, 7), 0)

# Otsu threshold inside cylinder only
roi_pixels = blurred[cyl_mask]
thresh, _ = cv2.threshold(roi_pixels, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
# Beans are dark → invert: bean pixels < thresh
bean_mask = (blurred < thresh).astype(np.uint8) * 255
bean_mask[~cyl_mask] = 0

# Morphological cleanup: close small gaps, remove tiny noise
kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
bean_mask = cv2.morphologyEx(bean_mask, cv2.MORPH_CLOSE, kernel)
kernel_open = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
bean_mask = cv2.morphologyEx(bean_mask, cv2.MORPH_OPEN, kernel_open)

# ── Connected components → individual beans ───────────────────────────────────
n_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(
    bean_mask, connectivity=8)

# Filter by area: reject background (label 0) + tiny noise + huge blobs
# Typical bean area at 1600×1200 with ~50 beans: roughly 500–40000 px²
total_area = int(cyl_mask.sum())
min_area = max(200, total_area // 300)   # at least 1/300 of cylinder
max_area = total_area // 3               # no single blob > 1/3 of cylinder

rois = []
labelmap = np.zeros((H, W), dtype=np.uint8)
bean_id = 1

for lbl in range(1, n_labels):
    area = stats[lbl, cv2.CC_STAT_AREA]
    if area < min_area or area > max_area:
        continue
    x0 = stats[lbl, cv2.CC_STAT_LEFT]
    y0 = stats[lbl, cv2.CC_STAT_TOP]
    x1 = x0 + stats[lbl, cv2.CC_STAT_WIDTH]
    y1 = y0 + stats[lbl, cv2.CC_STAT_HEIGHT]
    rois.append({"id": bean_id, "x0": int(x0), "y0": int(y0),
                 "x1": int(x1), "y1": int(y1)})
    labelmap[labels == lbl] = bean_id
    bean_id += 1
    if bean_id > 254:  # uint8 limit
        break

# ── Write outputs ─────────────────────────────────────────────────────────────
with open(rois_path, "w") as f:
    json.dump(rois, f)
cv2.imwrite(lmap_path, labelmap)

elapsed = time.time() - t0
print(json.dumps({"bean_count": len(rois), "elapsed_s": round(elapsed, 2),
                  "otsu_thresh": int(thresh)}), flush=True)
