#!/usr/bin/env python3
"""
update_cylinder_mask.py <image_path>
Detects the cylinder circular boundary from a white-paper image and saves
the result to ~/KyleClaude/cylinder_mask.json.

The white paper inside the cylinder is bright; the cylinder walls outside
are black — this gives a clean circle boundary via Otsu thresholding.
"""
import sys, json, cv2, numpy as np

img_path = sys.argv[1] if len(sys.argv) > 1 else "/home/kyle/KyleClaude/cylinder_white_ref.png"
OUT_JSON  = "/home/kyle/KyleClaude/cylinder_mask.json"

img = cv2.imread(img_path, cv2.IMREAD_GRAYSCALE)
if img is None:
    print(f"[cylinder] ERROR: cannot read {img_path}")
    sys.exit(1)

H, W = img.shape
print(f"[cylinder] Image {W}x{H}  mean={img.mean():.1f}", flush=True)

# Otsu threshold: auto-separates bright (white paper) from dark (cylinder walls)
thresh_val, binary = cv2.threshold(img, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
print(f"[cylinder] Otsu threshold={thresh_val:.0f}", flush=True)

# Morphological close to fill small gaps at the boundary
kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))
binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)

cnts, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
if not cnts:
    print("[cylinder] ERROR: no contours found")
    sys.exit(1)

largest = max(cnts, key=cv2.contourArea)
area    = cv2.contourArea(largest)
if area < 0.05 * W * H:
    print(f"[cylinder] ERROR: largest contour area {area:.0f} < 5% of image ({0.05*W*H:.0f})")
    sys.exit(1)

(cx, cy), r = cv2.minEnclosingCircle(largest)

result = {
    "cx":       float(cx),
    "cy":       float(cy),
    "r":        float(r),
    "image_w":  W,
    "image_h":  H,
    "source":   "white_paper",
    "otsu_threshold": float(thresh_val),
    "image_used": img_path
}
with open(OUT_JSON, "w") as f:
    json.dump(result, f, indent=2)

print(f"[cylinder] c=({cx:.0f},{cy:.0f}) r={r:.0f}  coverage={area/(W*H)*100:.1f}%")
print(f"[cylinder] Saved → {OUT_JSON}")

# Save a debug visualization
vis = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
cv2.circle(vis, (int(cx), int(cy)), int(r), (0, 255, 0), 4)
cv2.circle(vis, (int(cx), int(cy)), 8, (0, 0, 255), -1)
cv2.putText(vis, f"c=({int(cx)},{int(cy)}) r={int(r)}", (20, 50),
            cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 255, 255), 2)
debug_path = "/home/kyle/KyleClaude/cylinder_mask_debug.png"
cv2.imwrite(debug_path, cv2.resize(vis, (800, 600)))
print(f"[cylinder] Debug → {debug_path}")
