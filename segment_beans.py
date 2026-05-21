#!/usr/bin/env python3
"""
segment_beans.py
距離轉換 + peak_local_max Watershed，自動偵測碗的圓形區域，
只在碗內分割，過濾邊緣反光雜訊，輸出每顆豆子的輪廓線（非方框）。

用法：
  python3 segment_beans.py <session_dir> [expected_count]
"""
import sys, os, json
import numpy as np
import cv2
from PIL import Image
from scipy import ndimage as ndi
from skimage.feature import peak_local_max
from skimage.segmentation import watershed

SESSION_DIR    = sys.argv[1] if len(sys.argv) > 1 else "/home/kyle/Desktop/GigaImage_20260503_223027"
EXPECTED_BEANS = int(sys.argv[2]) if len(sys.argv) > 2 else 51
# 優先順序：1250us差分 > 2500us差分 > 原始灰階
_d1250 = os.path.join(SESSION_DIR, "diff_1250us.png")
_d2500 = os.path.join(SESSION_DIR, "diff_gray.png")
_gray  = os.path.join(SESSION_DIR, "capture_2500us_gray.png")
GRAY_PNG = _d1250 if os.path.exists(_d1250) else (_d2500 if os.path.exists(_d2500) else _gray)
OUT_VIZ        = os.path.join(SESSION_DIR, "beans_contour.png")
OUT_ROIS       = os.path.join(SESSION_DIR, "beans_rois.json")
OUT_LMAP       = os.path.join(SESSION_DIR, "beans_labelmap.png")

# ── 讀取影像 ───────────────────────────────────────────────────────────────────
img = cv2.imread(GRAY_PNG, cv2.IMREAD_GRAYSCALE)
if img is None:
    print(f"[FAIL] 無法讀取 {GRAY_PNG}"); sys.exit(1)
H, W = img.shape
print(f"影像: {W}x{H}  mean={img.mean():.1f}")

# ── Step 1: 前景遮罩 + CLAHE ──────────────────────────────────────────────────
clahe   = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(16, 16))
img_eq  = clahe.apply(img)
th, bw  = cv2.threshold(img_eq, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
print(f"Otsu 閾值: {th:.0f}")

k3    = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
bw    = cv2.morphologyEx(bw, cv2.MORPH_OPEN, k3, iterations=2)
# 閉運算填豆子中間裂縫：差分圖背景乾淨用小核（7px），原圖用17px
close_k = 7 if GRAY_PNG.endswith("diff_gray.png") else 17
kc    = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (close_k, close_k))
bw_cl = cv2.morphologyEx(bw, cv2.MORPH_CLOSE, kc, iterations=1)

# ── Step 2: 有效區域遮罩 ──────────────────────────────────────────────────────
using_diff = GRAY_PNG.endswith("diff_gray.png") or GRAY_PNG.endswith("diff_1250us.png")
if using_diff:
    # 差分圖已乾淨，不需要碗半徑過濾，直接用全圖前景
    bw_inner  = bw_cl
    fy, fx    = np.where(bw_cl)
    bowl_cx   = float(fx.mean())
    bowl_cy   = float(fy.mean())
    bowl_r_inner = float(np.sqrt((W/2)**2 + (H/2)**2))  # 設很大，不做距離過濾
    print(f"使用差分圖，跳過碗邊界過濾")
else:
    fy, fx = np.where(bw_cl)
    bowl_cx = float(fx.mean())
    bowl_cy = float(fy.mean())
    dists   = np.sqrt((fx - bowl_cx)**2 + (fy - bowl_cy)**2)
    bowl_r  = float(np.percentile(dists, 92))
    bowl_r_inner = bowl_r * 0.96
    print(f"碗心: ({bowl_cx:.0f}, {bowl_cy:.0f})  半徑: {bowl_r:.0f}  有效半徑: {bowl_r_inner:.0f}")
    yy, xx  = np.mgrid[0:H, 0:W]
    bowl_mask = ((xx - bowl_cx)**2 + (yy - bowl_cy)**2) <= bowl_r_inner**2
    bw_inner  = bw_cl & bowl_mask.astype(np.uint8)

fg_pixels = int(np.count_nonzero(bw_inner))
print(f"前景像素: {fg_pixels}  ({fg_pixels/(H*W)*100:.1f}%)")

# ── Step 3: 連通元件 + K-means 分割 + 橢圓擬合 ───────────────────────────────
exp_area   = fg_pixels / max(EXPECTED_BEANS, 1)
min_single = exp_area * 0.15   # 小於此值視為雜訊

n_cc, cc_labels, cc_stats, cc_cents = cv2.connectedComponentsWithStats(bw_inner)

beans = []   # 每個 entry: {"ellipse": (cx,cy,ma,mb,angle), "pixels": np.array}

for cid in range(1, n_cc):
    area = int(cc_stats[cid, cv2.CC_STAT_AREA])
    if area < min_single:
        continue

    # 估計此連通域包含幾顆豆（只在面積 > 2.5x 才分割，避免大豆被錯切成兩半）
    n_est = max(1, round(area / exp_area)) if area > exp_area * 2.5 else 1

    ys, xs = np.where(cc_labels == cid)
    pts = np.column_stack([xs, ys]).astype(np.float32)

    if n_est == 1:
        # 直接擬合橢圓
        groups = [pts]
    else:
        # K-means 分群
        criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 200, 0.5)
        attempts = 10
        try:
            _, lbl, centers = cv2.kmeans(pts, n_est, None, criteria, attempts,
                                         cv2.KMEANS_PP_CENTERS)
            groups = [pts[lbl.flatten() == k] for k in range(n_est)]
            groups = [g for g in groups if len(g) >= 5]
        except Exception:
            groups = [pts]

    for g in groups:
        if len(g) < 5:
            continue
        try:
            ellipse = cv2.fitEllipse(g)   # ((cx,cy),(ma,mb),angle)
        except cv2.error:
            continue
        (ecx, ecy), (ma, mb), angle = ellipse
        # 過濾極小、極扁、或超大（超大 = 覆蓋多顆豆的錯誤橢圓）
        max_axis = 3.2 * np.sqrt(exp_area / np.pi)  # ~3.2 倍豆子半徑
        if mb < 10 or ma / max(mb, 1) > 4.0 or ma > max_axis:
            continue
        x0 = max(0, int(ecx - ma/2 - 5))
        y0 = max(0, int(ecy - mb/2 - 5))
        x1 = min(W, int(ecx + ma/2 + 5))
        y1 = min(H, int(ecy + mb/2 + 5))
        beans.append({
            "ellipse": ellipse,
            "cx": float(ecx), "cy": float(ecy),
            "x0": x0, "y0": y0, "x1": x1, "y1": y1,
            "area": len(g),
            "pixels": g,
        })

# ── IoU NMS：用橢圓實際重疊面積判斷重複（比純距離更可靠）─────────────────────
def ellipse_iou(e1, e2):
    """計算兩個橢圓的 Intersection-over-Union（填充像素遮罩）"""
    m1 = np.zeros((H, W), dtype=np.uint8)
    m2 = np.zeros((H, W), dtype=np.uint8)
    (cx1, cy1), (ma1, mb1), ang1 = e1
    (cx2, cy2), (ma2, mb2), ang2 = e2
    # 快速篩選：中心距離 > 兩橢圓最大半軸之和 → 絕對不重疊
    if np.sqrt((cx1-cx2)**2 + (cy1-cy2)**2) > (ma1 + ma2) / 2:
        return 0.0
    cv2.ellipse(m1, (int(cx1),int(cy1)), (max(1,int(ma1/2)),max(1,int(mb1/2))), ang1, 0, 360, 1, -1)
    cv2.ellipse(m2, (int(cx2),int(cy2)), (max(1,int(ma2/2)),max(1,int(mb2/2))), ang2, 0, 360, 1, -1)
    inter = int((m1 & m2).sum())
    union = int((m1 | m2).sum())
    return inter / union if union > 0 else 0.0

IOU_THRESH = 0.25  # 超過 25% 重疊視為同一顆豆
beans_nms = []
for b in sorted(beans, key=lambda x: -x["area"]):  # 面積大的優先保留
    dup = any(ellipse_iou(b["ellipse"], a["ellipse"]) > IOU_THRESH for a in beans_nms)
    if not dup:
        beans_nms.append(b)
removed = len(beans) - len(beans_nms)
if removed:
    print(f"IoU NMS 移除重複橢圓: {removed} 個（IoU > {IOU_THRESH}）")
beans = beans_nms

# 排序（左→右, 上→下）
beans.sort(key=lambda b: (round(b["cy"] / 80) * 80 + b["cx"] / 10000))
print(f"\n有效豆子: {len(beans)} 顆（目標 {EXPECTED_BEANS}）")
if beans:
    areas = [b["area"] for b in beans]
    print(f"面積: min={min(areas)}  max={max(areas)}  mean={np.mean(areas):.0f}")

# ── Step 6: 建立 label map 和 ROI JSON ───────────────────────────────────────
lmap = np.zeros((H, W), dtype=np.uint8)
rois = []
for new_id, b in enumerate(beans, start=1):
    b["id"] = new_id
    # 用橢圓填充 label map
    ellipse = b["ellipse"]
    (ecx, ecy), (ma, mb), angle = ellipse
    axes = (max(1, int(ma/2)), max(1, int(mb/2)))
    cv2.ellipse(lmap, (int(ecx), int(ecy)), axes, angle, 0, 360, new_id, -1)
    rois.append({"id": new_id,
                 "x0": b["x0"], "y0": b["y0"],
                 "x1": b["x1"], "y1": b["y1"]})

Image.fromarray(lmap).save(OUT_LMAP)
with open(OUT_ROIS, "w") as f:
    json.dump(rois, f, indent=2)
print(f"Label map → {OUT_LMAP}")
print(f"ROIs JSON → {OUT_ROIS}")

# ── Step 7: 視覺化（橢圓輪廓）────────────────────────────────────────────────
# 視覺化背景：優先 1250us，再 2500us
_vis_1250 = os.path.join(SESSION_DIR, "capture_1250us_gray.png")
_vis_2500 = os.path.join(SESSION_DIR, "capture_2500us_gray.png")
orig_gray = cv2.imread(_vis_1250 if os.path.exists(_vis_1250) else _vis_2500, cv2.IMREAD_GRAYSCALE)
if orig_gray is None:
    orig_gray = img
vis = cv2.cvtColor(orig_gray, cv2.COLOR_GRAY2BGR)

if not using_diff:
    cv2.circle(vis, (int(bowl_cx), int(bowl_cy)), int(bowl_r_inner),
               (255, 180, 0), 2, cv2.LINE_AA)

palette = [
    (0,220,80), (0,180,255), (255,100,0), (200,50,255),
    (0,255,200), (255,200,0), (100,220,100), (255,80,180),
    (80,200,255), (255,160,40),
]

for b in beans:
    nid = b["id"]
    col = palette[(nid - 1) % len(palette)]
    (ecx, ecy), (ma, mb), angle = b["ellipse"]
    axes = (max(1, int(ma/2)), max(1, int(mb/2)))
    cv2.ellipse(vis, (int(ecx), int(ecy)), axes, angle, 0, 360, col, 2)

    cx_i, cy_i = int(ecx), int(ecy)
    label = str(nid)
    fs, fw = 0.42, 1
    (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, fs, fw)
    cv2.rectangle(vis, (cx_i - tw//2 - 1, cy_i - th - 1),
                       (cx_i + tw//2 + 1, cy_i + 2), (0, 0, 0), -1)
    cv2.putText(vis, label, (cx_i - tw//2, cy_i),
                cv2.FONT_HERSHEY_SIMPLEX, fs, col, fw, cv2.LINE_AA)

cv2.putText(vis, f"Beans: {len(beans)}", (12, 36),
            cv2.FONT_HERSHEY_SIMPLEX, 1.1, (0, 255, 80), 3, cv2.LINE_AA)
cv2.imwrite(OUT_VIZ, vis)
print(f"輪廓圖 → {OUT_VIZ}")
print(f"\n完成！共分割 {len(beans)} 顆（目標 {EXPECTED_BEANS}）")
