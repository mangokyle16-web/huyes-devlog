#!/usr/bin/env python3
"""
agtron_fast.py <session_dir> <qsbs> <qsdb> <qs_path> [gray_png]

Fast Agtron without FastSAM.
- If gray_png is provided: OpenCV threshold + contour detection → per-bean ROIs
  → per-bean distribution histogram  (~15-20s total)
- Otherwise: single whole-cylinder ROI  (fallback, no distribution)
"""
import sys, os, json
import numpy as np
import cv2

SESSION_DIR = sys.argv[1]
QSBS        = sys.argv[2]
QSDB        = sys.argv[3]
QS_PATH     = sys.argv[4]
GRAY_PNG    = sys.argv[5] if len(sys.argv) > 5 else None

SF_BIN     = "/home/kyle/KyleClaude/multispectral_demo/build/spec_fingerprint"
GLOBAL_CYL = "/home/kyle/KyleClaude/cylinder_mask.json"

# ── 1. Load cylinder mask ─────────────────────────────────────────────────────
cyl_path = os.path.join(SESSION_DIR, "cylinder_mask.json")
if not os.path.exists(cyl_path):
    cyl_path = GLOBAL_CYL
if not os.path.exists(cyl_path):
    cyl = {"cx": 800, "cy": 600, "r": 800, "image_w": 1600, "image_h": 1200}
else:
    with open(cyl_path) as f:
        cyl = json.load(f)

cx, cy, r = cyl["cx"], cyl["cy"], cyl["r"]
IW, IH = cyl["image_w"], cyl["image_h"]

rois_path = os.path.join(SESSION_DIR, "beans_rois.json")
lmap_path = os.path.join(SESSION_DIR, "beans_labelmap.png")
raw_csv   = os.path.join(SESSION_DIR, "agtron_raw_spec.csv")

# ── 2. Bean detection: contours from gray image ───────────────────────────────
def detect_beans_from_gray(gray_path, cx, cy, r, IW, IH):
    """
    OpenCV threshold + contour detection.
    Returns (rois_list, labelmap_ndarray).
    Bean IDs start from 1 (0 = background in labelmap).
    """
    img = cv2.imread(gray_path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        return None, None
    H, W = img.shape

    # Cylinder circle mask (scaled to image size)
    sx, sy = W / IW, H / IH
    Y_g, X_g = np.ogrid[:H, :W]
    cyl_mask = ((X_g - cx*sx)**2 + (Y_g - cy*sy)**2 <= (r*min(sx,sy))**2)

    # Black-out outside cylinder
    masked = img.copy()
    masked[~cyl_mask] = 0

    # Otsu threshold inside cylinder only.
    # Coffee beans are DARKER than the cylinder floor, so we keep pixels
    # that are (a) inside the cylinder and (b) <= Otsu threshold.
    in_vals = masked[cyl_mask]
    thresh_val, _ = cv2.threshold(in_vals.reshape(-1,1), 0, 255,
                                   cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    binary = (cyl_mask & (masked <= thresh_val) & (masked > 0)).astype(np.uint8) * 255

    # Morphology: close small gaps, then erode to separate touching beans
    k_close = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
    k_erode = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    closed  = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, k_close)
    eroded  = cv2.erode(closed, k_erode, iterations=2)

    # Find contours
    cnts, _ = cv2.findContours(eroded, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    # Filter by area: reject too-small (noise) and too-large (merged blobs)
    areas  = [cv2.contourArea(c) for c in cnts]
    if not areas:
        return None, None
    median_area = float(np.median(areas))
    min_area = median_area * 0.15
    max_area = median_area * 4.0

    rois, lmap = [], np.zeros((H, W), dtype=np.uint8)
    bid = 1
    for cnt in cnts:
        a = cv2.contourArea(cnt)
        if a < min_area or a > max_area:
            continue
        x_b, y_b, w_b, h_b = cv2.boundingRect(cnt)
        # Scale ROI back to capture resolution (1600x1200)
        rois.append({
            "id": bid,
            "x0": int(x_b / sx),
            "y0": int(y_b / sy),
            "x1": int((x_b + w_b) / sx),
            "y1": int((y_b + h_b) / sy),
        })
        cv2.drawContours(lmap, [cnt], -1, int(bid), -1)
        bid += 1

    # Scale labelmap back to capture resolution
    lmap_full = cv2.resize(lmap, (IW, IH), interpolation=cv2.INTER_NEAREST)
    print(f"[agtron_fast] Contour detection: {len(rois)} regions "
          f"(Otsu={thresh_val:.0f}, median_area={median_area:.0f}px²)", flush=True)
    return rois, lmap_full

# ── 3. Build ROIs and labelmap ────────────────────────────────────────────────
rois = None
lmap_full = None

gray_path = GRAY_PNG or os.path.join(SESSION_DIR, "capture_2500us_gray.png")
if os.path.exists(gray_path):
    rois, lmap_full = detect_beans_from_gray(gray_path, cx, cy, r, IW, IH)

if not rois:
    # Fallback: single whole-cylinder inscribed rectangle
    print("[agtron_fast] Falling back to single-ROI mode", flush=True)
    half = r / (2 ** 0.5)
    x0 = max(0,  int(cx - half))
    y0 = max(0,  int(cy - half))
    x1 = min(IW, int(cx + half))
    y1 = min(IH, int(cy + half))
    rois = [{"id": 1, "x0": x0, "y0": y0, "x1": x1, "y1": y1}]
    lmap_full = np.zeros((IH, IW), dtype=np.uint8)
    Y_l, X_l = np.ogrid[:IH, :IW]
    lmap_full[(X_l - cx)**2 + (Y_l - cy)**2 <= r**2] = 1

with open(rois_path, "w") as f:
    json.dump(rois, f)
cv2.imwrite(lmap_path, lmap_full)
print(f"[agtron_fast] {len(rois)} ROIs written, labelmap {IW}x{IH}", flush=True)

# ── 4. spec_fingerprint → agtron_raw_spec.csv + channel images ───────────────
cmd = (f'"{SF_BIN}" "{QSBS}" "{QSDB}" "{QS_PATH}" '
       f'"{rois_path}" "{raw_csv}" "{lmap_path}" 2>&1')
print("[agtron_fast] Running spec_fingerprint...", flush=True)
ret = os.system(cmd)
if ret != 0 or not os.path.exists(raw_csv):
    print(f"[agtron_fast] spec_fingerprint failed (exit={ret})", flush=True)
    sys.exit(1)

# ── 5. agtron_analysis.py ────────────────────────────────────────────────────
cmd2 = f'python3 /home/kyle/KyleClaude/agtron_analysis.py "{SESSION_DIR}" 2>&1'
print("[agtron_fast] Running agtron_analysis...", flush=True)
ret2 = os.system(cmd2)
print(f"[agtron_fast] Done (exit={ret2})", flush=True)
