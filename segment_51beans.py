#!/usr/bin/env python3
"""
segment_51beans.py
針對黑底白豆的影像進行分割（Watershed），輸出：
  - beans_contour.png   : 輪廓視覺化
  - beans_rois.json     : ROI 列表（供 spec_fingerprint 使用）
  - beans_labelmap.png  : label map（像素值 = 豆 ID，最大 255）

用法：
  python3 segment_51beans.py <session_dir> [expected_count]
"""
import sys, os, json
import numpy as np
import cv2
from PIL import Image
from scipy import ndimage as ndi

SESSION_DIR    = sys.argv[1] if len(sys.argv) > 1 else "/home/kyle/Desktop/GigaImage_20260503_011205"
EXPECTED_BEANS = int(sys.argv[2]) if len(sys.argv) > 2 else 51
GRAY_PNG       = os.path.join(SESSION_DIR, "capture_2500us_gray.png")
OUT_VIZ        = os.path.join(SESSION_DIR, "beans_contour.png")
OUT_ROIS       = os.path.join(SESSION_DIR, "beans_rois.json")
OUT_LMAP       = os.path.join(SESSION_DIR, "beans_labelmap.png")

# ── 讀取灰階影像 ──────────────────────────────────────────────────────────────
img_gray = cv2.imread(GRAY_PNG, cv2.IMREAD_GRAYSCALE)
if img_gray is None:
    print(f"[FAIL] 無法讀取 {GRAY_PNG}"); sys.exit(1)

H, W = img_gray.shape
print(f"影像尺寸: {W}x{H}  mean={img_gray.mean():.1f}")

# ── Step 1: 二值化（豆子是亮的，背景是暗的）──────────────────────────────────
# 2500us 正常曝光：t=50 足夠區分豆子和黑底
_, bw = cv2.threshold(img_gray, 50, 255, cv2.THRESH_BINARY)
print(f"使用閾值: 50")

# 輕量開運算去雜訊
k3 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
bw = cv2.morphologyEx(bw, cv2.MORPH_OPEN, k3, iterations=1)

# 顯示 blob 統計
num0, labels0, stats0, _ = cv2.connectedComponentsWithStats(bw)
all_blobs = sorted([(stats0[j,cv2.CC_STAT_AREA], j) for j in range(1,num0) if stats0[j,cv2.CC_STAT_AREA]>100], reverse=True)
print(f"初步 blob 數量: {len(all_blobs)}")
for a, j in all_blobs[:15]:
    x0=stats0[j,cv2.CC_STAT_LEFT]; y0=stats0[j,cv2.CC_STAT_TOP]
    w2=stats0[j,cv2.CC_STAT_WIDTH]; h2=stats0[j,cv2.CC_STAT_HEIGHT]
    print(f"  area={a:6d}  ({x0},{y0})  {w2}x{h2}")

# ── Step 2: 估計豆子大小，選合適的 min_dist ───────────────────────────────────
# 判斷是否大部分豆子已分開（最大 blob / 總面積 < 30%）
bean_area_total = sum(a for a,_ in all_blobs if a > 300)
max_blob_area   = all_blobs[0][0] if all_blobs else 0
small_blobs     = sum(1 for a,_ in all_blobs if 500 < a < 20000)
print(f"\n豆子總面積: {bean_area_total}  最大 blob: {max_blob_area}  小 blob 數: {small_blobs}")

# 從面積估計半徑
if small_blobs >= EXPECTED_BEANS * 0.5:
    # 大部分豆子已分開，直接用 CC 即可
    est_area_per_bean = bean_area_total / max(small_blobs, 1)
else:
    est_area_per_bean = bean_area_total / EXPECTED_BEANS

est_radius = max(10, int(np.sqrt(est_area_per_bean / np.pi)))
# 2500us 影像：豆子有中間裂縫，需先 closing 填縫再找峰值
# 經測試：close_k=19 + min_dist=70 → 剛好 51 peaks
CLOSE_K  = 19
min_dist = 70
print(f"估計每顆面積: {est_area_per_bean:.0f}  半徑: {est_radius}  close_k: {CLOSE_K}  min_dist: {min_dist}")

# ── Step 3: Watershed（豆子都接觸，必須用 Watershed）────────────────────────
if False:   # 保留 CC 分支但不走
    pass
else:
    print(f"\n⚠ 豆子有合並，使用 Watershed 分割")

    # ── 高光種子法（t=190 找每顆豆的高光 blob 作 Watershed 種子）──────────────
    _, bw_hi = cv2.threshold(img_gray, 190, 255, cv2.THRESH_BINARY)
    bw_hi = cv2.morphologyEx(bw_hi, cv2.MORPH_OPEN, k3, iterations=1)

    n_hi, _, stats_hi, cents_hi = cv2.connectedComponentsWithStats(bw_hi)
    hi_seeds = sorted(
        [(int(cents_hi[j][0]), int(cents_hi[j][1]), int(stats_hi[j, cv2.CC_STAT_AREA]))
         for j in range(1, n_hi) if 100 < stats_hi[j, cv2.CC_STAT_AREA] < 20000],
        key=lambda s: -s[2]
    )[:EXPECTED_BEANS]  # 取面積最大的 N 個高光 blob
    print(f"高光種子: {len(hi_seeds)} 個（目標 {EXPECTED_BEANS}）")

    # 用高光中心建立 Watershed markers
    markers = np.zeros((H, W), dtype=np.int32)
    for idx, (px, py, _) in enumerate(hi_seeds):
        markers[py, px] = idx + 1
    markers[bw == 0] = len(hi_seeds) + 1   # 背景

    # 在距離轉換影像上做 Watershed
    dist = cv2.distanceTransform(bw, cv2.DIST_L2, 5)
    dist_vis = cv2.normalize(dist, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    dist_bgr  = cv2.cvtColor(dist_vis, cv2.COLOR_GRAY2BGR)
    ws_result = cv2.watershed(dist_bgr, markers.copy())

    # 提取每個 basin
    final_beans = []
    for bean_id in range(1, len(hi_seeds) + 1):
        mask = (ws_result == bean_id) & (bw > 0)
        if mask.sum() < 500: continue
        ys2, xs2 = np.where(mask)
        if len(xs2) == 0: continue
        x0, y0 = int(xs2.min()), int(ys2.min())
        x1, y1 = int(xs2.max()) + 1, int(ys2.max()) + 1
        area = int(mask.sum())
        final_beans.append({
            "cx": float(xs2.mean()), "cy": float(ys2.mean()),
            "x0": x0, "y0": y0, "x1": x1, "y1": y1, "area": area,
            "_ws_result_id": bean_id
        })

# 排序
final_beans.sort(key=lambda b: (round(b["cy"] / 80) * 80 + b["cx"] / 10000))
print(f"\n最終分割: {len(final_beans)} 顆豆子（目標 {EXPECTED_BEANS}）")

if not final_beans:
    print("[ERROR] 分割失敗"); sys.exit(1)

areas = [b["area"] for b in final_beans]
print(f"面積: min={min(areas)} max={max(areas)} mean={np.mean(areas):.0f}")

# ── Step 4: 建立 label map 和 ROI JSON ───────────────────────────────────────
lmap = np.zeros((H, W), dtype=np.uint8)   # spec_fingerprint 要求 uint8
rois = []
for i, b in enumerate(final_beans):
    new_id = i + 1
    rid = b.get("_ws_result_id")
    if rid is not None and 'ws_result' in locals():
        pixel_mask = (ws_result == rid) & (bw > 0)
        lmap[pixel_mask] = new_id
    else:
        lmap[b["y0"]:b["y1"], b["x0"]:b["x1"]] = new_id
    rois.append({"id": new_id, "x0": b["x0"], "y0": b["y0"], "x1": b["x1"], "y1": b["y1"]})

# 驗證：每個豆子在 label map 上的像素數
print("\nLabel map 驗證（前10顆）:")
for i in range(min(10, len(final_beans))):
    px = int(np.sum(lmap == i+1))
    print(f"  Bean {i+1}: {px} px")

Image.fromarray(lmap).save(OUT_LMAP)
with open(OUT_ROIS, "w") as f:
    json.dump(rois, f, indent=2)
print(f"Label map → {OUT_LMAP}")
print(f"ROIs JSON → {OUT_ROIS}")

# ── Step 5: 視覺化 ────────────────────────────────────────────────────────────
vis = cv2.cvtColor(img_gray, cv2.COLOR_GRAY2BGR)
cols = [(0,255,0),(0,200,255),(255,100,0),(200,0,255),
        (0,255,200),(255,200,0),(100,255,100),(255,80,200)]
for i, b in enumerate(final_beans):
    col = cols[i % len(cols)]
    cv2.rectangle(vis, (b["x0"], b["y0"]), (b["x1"], b["y1"]), col, 2)
    cx, cy = int(b["cx"]), int(b["cy"])
    cv2.putText(vis, str(i+1), (cx-8, cy+5),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, col, 1, cv2.LINE_AA)

cv2.putText(vis, f"Beans: {len(final_beans)}", (10, 30),
            cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0,255,0), 2, cv2.LINE_AA)
cv2.imwrite(OUT_VIZ, vis)
print(f"輪廓圖 → {OUT_VIZ}")
print(f"\n完成！共分割 {len(final_beans)} 顆（目標 {EXPECTED_BEANS}）")
