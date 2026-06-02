#!/usr/bin/env python3
"""
uv_overlay.py
將 UV 365nm 手機照片與多光譜分析結果做影像配準與疊加比對。
配準方法：
  1. SIFT 特徵點匹配 + RANSAC Homography（優先）
  2. 碗圓邊緣偵測配準（fallback）
"""
import cv2
import numpy as np
from PIL import Image
import json, os, sys

SESSION_DIR = sys.argv[1] if len(sys.argv) > 1 else "/home/kyle/Desktop/GigaImage_20260504_003754"
UV_DIR      = sys.argv[2] if len(sys.argv) > 2 else "/home/kyle/Downloads"
OUT_DIR     = os.path.join(UV_DIR, "uv_overlay_result")
os.makedirs(OUT_DIR, exist_ok=True)

HIGH_BEANS = [14, 19, 27, 32, 41, 53]
MED_BEANS  = [15, 25, 44, 45]

# ── 讀取多光譜影像 ──────────────────────────────────────────────────────────────
ms_gray = cv2.imread(os.path.join(SESSION_DIR, "capture_1250us_gray.png"), cv2.IMREAD_GRAYSCALE)
H_ms, W_ms = ms_gray.shape
lmap = np.array(Image.open(os.path.join(SESSION_DIR, "beans_labelmap.png")))

# 預計算每顆豆子的橢圓
bean_ellipses = {}
for bid in HIGH_BEANS + MED_BEANS:
    mask_b = (lmap == bid).astype(np.uint8) * 255
    pts = cv2.findNonZero(mask_b)
    if pts is not None and len(pts) >= 5:
        try:
            bean_ellipses[bid] = cv2.fitEllipse(pts)
        except cv2.error:
            pass

print(f"多光譜影像: {W_ms}x{H_ms}")
print(f"已提取橢圓: {list(bean_ellipses.keys())}")

# ── 讀取所有 UV 照片 ────────────────────────────────────────────────────────────
uv_photos = sorted([f for f in os.listdir(UV_DIR) if f.endswith('.jpg')])
print(f"\nUV 照片: {uv_photos}")

def find_bowl_circle(img_gray, label=""):
    """用 HoughCircles 偵測碗的圓形邊緣"""
    blurred = cv2.GaussianBlur(img_gray, (9, 9), 2)
    # 嘗試不同參數
    for dp, p1, p2 in [(1, 50, 30), (1.5, 40, 25), (1, 30, 20)]:
        circles = cv2.HoughCircles(
            blurred, cv2.HOUGH_GRADIENT, dp=dp,
            minDist=img_gray.shape[0]//2,
            param1=p1, param2=p2,
            minRadius=int(min(img_gray.shape)*0.25),
            maxRadius=int(min(img_gray.shape)*0.60)
        )
        if circles is not None:
            c = np.round(circles[0, 0]).astype(int)
            print(f"  {label} 碗圓: 中心({c[0]},{c[1]}) 半徑={c[2]}")
            return c[0], c[1], c[2]
    return None

def homography_sift(ms_gray, uv_gray):
    """SIFT 特徵點配準，返回 (M, inliers) 或 None"""
    sift = cv2.SIFT_create(nfeatures=8000)
    kp1, des1 = sift.detectAndCompute(ms_gray, None)
    kp2, des2 = sift.detectAndCompute(uv_gray, None)
    if des1 is None or des2 is None or len(kp1) < 10 or len(kp2) < 10:
        return None, 0
    bf = cv2.BFMatcher()
    matches = bf.knnMatch(des1, des2, k=2)
    good = [m for m, n in matches if m.distance < 0.75 * n.distance]
    print(f"  SIFT 匹配點: {len(good)}")
    if len(good) < 10:
        return None, 0
    src = np.float32([kp1[m.queryIdx].pt for m in good]).reshape(-1,1,2)
    dst = np.float32([kp2[m.trainIdx].pt for m in good]).reshape(-1,1,2)
    M, mask = cv2.findHomography(src, dst, cv2.RANSAC, 5.0)
    inliers = int(mask.sum()) if mask is not None else 0
    print(f"  RANSAC 內點: {inliers}")
    return M, inliers

def homography_circle(ms_gray, uv_gray, H_uv, W_uv):
    """碗圓配準，返回 M 或 None"""
    ms_circle = find_bowl_circle(ms_gray, "多光譜")
    uv_circle = find_bowl_circle(uv_gray, "UV")
    if ms_circle is None or uv_circle is None:
        return None
    cx_ms, cy_ms, r_ms = ms_circle
    cx_uv, cy_uv, r_uv = uv_circle
    # 建立相似變換（平移+縮放）
    scale = r_uv / r_ms
    tx = cx_uv - cx_ms * scale
    ty = cy_uv - cy_ms * scale
    M = np.array([[scale, 0, tx],
                  [0, scale, ty],
                  [0,     0,  1]], dtype=np.float64)
    print(f"  圓形配準: scale={scale:.3f} tx={tx:.0f} ty={ty:.0f}")
    return M

def draw_overlay(uv_img, M, label=""):
    """在 UV 圖上疊加 HIGH/MED 豆子橢圓"""
    result = uv_img.copy()
    H_uv, W_uv = result.shape[:2]

    for bid, ellipse in bean_ellipses.items():
        (cx, cy), (ma, mb), angle = ellipse
        # 把橢圓中心投影到 UV 座標
        center_ms = np.float32([[[cx, cy]]])
        center_uv = cv2.perspectiveTransform(center_ms, M)
        if center_uv is None:
            continue
        cx_uv, cy_uv = center_uv[0][0]
        if not (0 < cx_uv < W_uv and 0 < cy_uv < H_uv):
            continue

        # 利用 M 的行列式估算局部縮放比例
        scale = np.sqrt(abs(np.linalg.det(M[:2, :2])))
        ma_uv = ma * scale
        mb_uv = mb * scale

        if bid in HIGH_BEANS:
            col = (0, 50, 255)   # 紅
            thickness = 3
            fs, fw = 0.7, 2
        else:
            col = (0, 165, 255)  # 橙
            thickness = 2
            fs, fw = 0.55, 1

        axes = (max(1, int(ma_uv / 2)), max(1, int(mb_uv / 2)))
        cv2.ellipse(result, (int(cx_uv), int(cy_uv)), axes, angle, 0, 360, col, thickness)

        # 內層半透明填充（HIGH only）
        if bid in HIGH_BEANS:
            overlay = result.copy()
            cv2.ellipse(overlay, (int(cx_uv), int(cy_uv)), axes, angle, 0, 360, col, -1)
            cv2.addWeighted(overlay, 0.15, result, 0.85, 0, result)

        lbl = f"Bean {bid}"
        (tw, th), _ = cv2.getTextSize(lbl, cv2.FONT_HERSHEY_SIMPLEX, fs, fw)
        tx_ = int(cx_uv) - tw // 2
        ty_ = int(cy_uv) + th // 2
        cv2.rectangle(result, (tx_-2, ty_-th-2), (tx_+tw+2, ty_+2), (0,0,0), -1)
        cv2.putText(result, lbl, (tx_, ty_), cv2.FONT_HERSHEY_SIMPLEX, fs, col, fw, cv2.LINE_AA)

    # 圖例
    cv2.putText(result, f"HIGH ({len(HIGH_BEANS)})", (12, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0,50,255), 2, cv2.LINE_AA)
    cv2.putText(result, f"MED  ({len(MED_BEANS)})", (12, 58),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0,165,255), 2, cv2.LINE_AA)
    cv2.putText(result, f"[{label}]", (12, 86),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (200,200,200), 1, cv2.LINE_AA)
    return result

# ── 對每張 UV 照片做配準 ────────────────────────────────────────────────────────
best_result = None
best_inliers = 0
best_file = ""

for photo_file in uv_photos:
    path = os.path.join(UV_DIR, photo_file)
    uv_img = cv2.imread(path)
    if uv_img is None:
        continue
    uv_gray = cv2.cvtColor(uv_img, cv2.COLOR_BGR2GRAY)
    H_uv, W_uv = uv_img.shape[:2]
    print(f"\n處理 {photo_file} ({W_uv}x{H_uv})")

    # 先嘗試 SIFT
    M, inliers = homography_sift(ms_gray, uv_gray)

    # SIFT 不足時用圓形配準
    if M is None or inliers < 15:
        print("  → 改用碗圓配準")
        M = homography_circle(ms_gray, uv_gray, H_uv, W_uv)
        inliers = 999 if M is not None else 0  # 強制用圓形結果

    if M is None:
        print("  → 配準失敗，跳過")
        continue

    result = draw_overlay(uv_img, M, label=photo_file)
    out_path = os.path.join(OUT_DIR, f"overlay_{photo_file}")
    cv2.imwrite(out_path, result)
    print(f"  → 儲存: {out_path}")

    if inliers > best_inliers:
        best_inliers = inliers
        best_result = result
        best_file = photo_file

# ── 儲存最佳結果 ────────────────────────────────────────────────────────────────
if best_result is not None:
    best_out = os.path.join(OUT_DIR, "best_overlay.png")
    cv2.imwrite(best_out, best_result)
    print(f"\n最佳疊加圖 → {best_out}  (來源: {best_file}, inliers={best_inliers})")
else:
    print("\n[FAIL] 所有照片配準失敗")
