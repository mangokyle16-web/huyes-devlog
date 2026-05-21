#!/usr/bin/env python3
"""
segment_beans_sam.py
FastSAM (Ultralytics) 咖啡豆分割，輸出格式與 segment_beans.py 相容。

用法：
  python3 segment_beans_sam.py <session_dir> [expected_count] [conf] [imgsz]

範例：
  python3 segment_beans_sam.py /home/kyle/Desktop/GigaImage_20260504_003754 51
  python3 segment_beans_sam.py /home/kyle/Desktop/GigaImage_20260504_003754 51 0.35 640
"""
import sys, os, json, warnings
warnings.filterwarnings("ignore")

import numpy as np
import cv2
from PIL import Image
from scipy.spatial import cKDTree
from scipy.ndimage import gaussian_filter1d

MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "FastSAM-s.pt")


def _mask_iou(m1, m2):
    inter = int((m1 & m2).sum())
    if inter == 0:
        return 0.0
    union = int((m1 | m2).sum())
    return inter / union if union > 0 else 0.0

_SMALL_S = 8  # 1/8 linear scale for IoU → 64x fewer pixels

def _smask(m, ws, hs):
    return cv2.resize(m, (ws, hs), interpolation=cv2.INTER_NEAREST)

def _iou_fast(s1, s2):
    inter = int((s1 & s2).sum())
    if inter == 0: return 0.0
    return inter / max(int((s1 | s2).sum()), 1)


def run(session_dir, n_beans=51, model=None, sam_conf=0.35, sam_imgsz=640):
    """Run FastSAM bean segmentation. Returns detected bean count.
    model: pre-loaded FastSAM instance (for daemon use); if None, loads from MODEL_PATH.
    """
    import time

    SESSION_DIR    = session_dir
    EXPECTED_BEANS = n_beans
    SAM_CONF       = sam_conf
    SAM_IMGSZ      = sam_imgsz

    OUT_VIZ  = os.path.join(SESSION_DIR, "beans_contour.png")
    OUT_ROIS = os.path.join(SESSION_DIR, "beans_rois.json")
    OUT_LMAP = os.path.join(SESSION_DIR, "beans_labelmap.png")

    # ── 選擇 SAM 輸入影像（高曝光優先，紋理對比對 SAM 更好）────────────────────
    _sam_candidates = [
        os.path.join(SESSION_DIR, "capture_2500us_gray.png"),  # 優先
        os.path.join(SESSION_DIR, "capture_1250us_gray.png"),
        os.path.join(SESSION_DIR, "diff_1250us.png"),
        os.path.join(SESSION_DIR, "diff_gray.png"),
    ]
    GRAY_PNG = next((p for p in _sam_candidates if os.path.exists(p)), None)
    if GRAY_PNG is None:
        print("[FAIL] 找不到輸入影像"); return 0
    print(f"SAM 輸入影像: {os.path.basename(GRAY_PNG)}")

    gray = cv2.imread(GRAY_PNG, cv2.IMREAD_GRAYSCALE)
    if gray is None:
        print(f"[FAIL] 無法讀取 {GRAY_PNG}"); return 0
    H, W = gray.shape
    W_S, H_S = max(1, W // _SMALL_S), max(1, H // _SMALL_S)  # small-mask dims for fast IoU

    print(f"影像尺寸: {W}x{H}")

    # 2500us 等效影像：優先用實際 2500us 檔案，否則用 ×2 clip 合成
    # ×2 clip 複製高曝光的豆子飽和效果，使豆子/背景對比拉大，SAM 偵測更準
    _gray2500_path = os.path.join(SESSION_DIR, "capture_2500us_gray.png")
    if os.path.exists(_gray2500_path):
        img2500 = cv2.imread(_gray2500_path, cv2.IMREAD_GRAYSCALE)
        if img2500 is None:
            img2500 = np.clip(gray.astype(np.uint16) * 2, 0, 255).astype(np.uint8)
    else:
        img2500 = np.clip(gray.astype(np.uint16) * 2, 0, 255).astype(np.uint8)

    # SAM 輸入和 local_contrast 都用 img2500
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(16, 16))
    gray_eq = clahe.apply(img2500)
    img_bgr = cv2.cvtColor(gray_eq, cv2.COLOR_GRAY2BGR)

    # ── FastSAM 推理 ──────────────────────────────────────────────────────────
    if model is None:
        from ultralytics import FastSAM as _FastSAM
        print(f"載入 FastSAM 模型 ({MODEL_PATH})...")
        model = _FastSAM(MODEL_PATH)

    print(f"推理中 (conf={SAM_CONF}, imgsz={SAM_IMGSZ})...")
    t0 = time.time()
    results = model(
        img_bgr,
        device="cpu",
        retina_masks=True,
        conf=SAM_CONF,
        iou=0.9,
        imgsz=SAM_IMGSZ,
        max_det=80,
        verbose=False,
    )
    print(f"推理完成: {time.time()-t0:.1f}s，原始遮罩: {len(results[0].masks) if results[0].masks else 0} 個")

    if not results[0].masks:
        print("[FAIL] FastSAM 未偵測到任何遮罩"); return 0

    # ── 建立前景遮罩（優先用 diff 影像，無則用 Otsu）────────────────────────
    diff_path = os.path.join(SESSION_DIR, "diff_1250us.png")
    if not os.path.exists(diff_path):
        diff_path = os.path.join(SESSION_DIR, "diff_gray.png")

    if os.path.exists(diff_path):
        diff_img = cv2.imread(diff_path, cv2.IMREAD_GRAYSCALE)
        _, fg_base = cv2.threshold(diff_img, 15, 255, cv2.THRESH_BINARY)
        # fg_mask：7px 擴張，用於面積重疊計算
        fg_mask = cv2.morphologyEx(fg_base, cv2.MORPH_DILATE,
                                   cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7)))
        # fg_center：30px 擴張，用於中心點檢查（更寬鬆，不漏邊緣豆）
        fg_center = cv2.morphologyEx(fg_base, cv2.MORPH_DILATE,
                                     cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (30, 30)))
        fg_pixels = int(np.count_nonzero(fg_mask))
        print(f"前景遮罩: diff 影像 ({os.path.basename(diff_path)})，前景像素: {fg_pixels}")
    else:
        diff_img = None
        fg_base  = None
        _, bw_otsu = cv2.threshold(gray_eq, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        fg_mask = cv2.morphologyEx(bw_otsu, cv2.MORPH_OPEN,
                                   cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)), iterations=2)
        fg_center = fg_mask  # 無 diff 時不做中心點篩選
        fg_pixels = int(np.count_nonzero(fg_mask))
        print(f"前景遮罩: Otsu（無 diff 影像），前景像素: {fg_pixels}")

    exp_area = fg_pixels / max(EXPECTED_BEANS, 1)
    min_area = exp_area * 0.30
    max_area = exp_area * 3.0
    print(f"期望豆子面積: {exp_area:.0f}px | 過濾範圍: [{min_area:.0f}, {max_area:.0f}]")

    # ── 遮罩過濾（第一輪）──────────────────────────────────────────────────────
    raw_masks = results[0].masks.data.numpy().astype(np.uint8)  # (N, H, W)

    beans_raw = []
    for i, mask in enumerate(raw_masks):
        # 調整到原始影像尺寸（SAM 可能輸出 imgsz 解析度）
        if mask.shape != (H, W):
            mask = (cv2.resize(mask.astype(np.float32), (W, H),
                               interpolation=cv2.INTER_LINEAR) >= 0.5).astype(np.uint8)
        area = int(mask.sum())
        if area < min_area or area > max_area:
            continue

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            continue
        cnt = max(contours, key=cv2.contourArea)
        if len(cnt) < 5:
            continue
        try:
            ellipse = cv2.fitEllipse(cnt)
        except cv2.error:
            continue

        (ecx, ecy), (ma, mb), angle = ellipse
        if mb < 8 or ma / max(mb, 1) > 4.5:
            continue

        perimeter = cv2.arcLength(cnt, True)
        circularity = 4 * np.pi * area / (perimeter ** 2) if perimeter > 0 else 0
        if circularity < 0.45:
            continue

        diff_mean = float(diff_img[mask.astype(bool)].mean()) if diff_img is not None else 99.0
        if diff_mean < 13:
            continue

        fg_cover = float((diff_img[mask.astype(bool)] > 20).mean()) if diff_img is not None else 1.0
        if fg_cover < 0.30:
            continue

        cx_i, cy_i = int(ecx), int(ecy)
        center_in_fg = fg_center[min(cy_i, H-1), min(cx_i, W-1)] > 0
        fg_overlap = float((mask & (fg_mask > 0).astype(np.uint8)).sum()) / max(area, 1)
        if center_in_fg:
            if fg_overlap < 0.15:
                continue
        else:
            if fg_overlap < 0.55:
                continue

        x, y, bw_box, bh_box = cv2.boundingRect(cnt)
        beans_raw.append({
            "mask": mask,
            "mask_small": _smask(mask, W_S, H_S),
            "contour": cnt,
            "ellipse": ellipse,
            "cx": float(ecx), "cy": float(ecy),
            "x0": x, "y0": y, "x1": x + bw_box, "y1": y + bh_box,
            "area": area,
        })

    print(f"面積過濾後: {len(beans_raw)} 顆")

    # ── 第二輪補偵測：對被嚴格篩選擋掉的 SAM 遮罩，用放寬條件 + 不與現有重疊 ──
    for i, mask in enumerate(raw_masks):
        if mask.shape != (H, W):
            mask = (cv2.resize(mask.astype(np.float32), (W, H),
                               interpolation=cv2.INTER_LINEAR) >= 0.5).astype(np.uint8)
        area = int(mask.sum())
        if area < min_area or area > max_area:
            continue
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            continue
        cnt = max(contours, key=cv2.contourArea)
        if len(cnt) < 5:
            continue
        try:
            ellipse = cv2.fitEllipse(cnt)
        except cv2.error:
            continue
        (ecx, ecy), (ma, mb), _ = ellipse
        if mb < 8 or ma / max(mb, 1) > 4.5:
            continue
        perimeter = cv2.arcLength(cnt, True)
        circularity = 4 * np.pi * area / (perimeter ** 2) if perimeter > 0 else 0
        if circularity < 0.55:
            continue
        diff_mean = float(diff_img[mask.astype(bool)].mean()) if diff_img is not None else 99.0
        fg_cover = float((diff_img[mask.astype(bool)] > 20).mean()) if diff_img is not None else 1.0
        # 局部對比度：mask 均值 vs 周圍 15px 環形均值（2500us 影像）
        k_lc = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))
        ring = cv2.dilate(mask, k_lc).astype(bool) & ~mask.astype(bool)
        bean_I = float(img2500[mask.astype(bool)].mean())
        ring_I = float(img2500[ring].mean()) if ring.any() else bean_I
        local_contrast = abs(bean_I - ring_I)
        passes_diff = (diff_mean >= 10 and fg_cover >= 0.22)
        passes_lc   = (local_contrast >= 12.0)
        if not (passes_diff or passes_lc):
            continue
        ms = _smask(mask, W_S, H_S)
        if any(_iou_fast(ms, b["mask_small"]) > 0.15 for b in beans_raw):
            continue
        x, y, bw_box, bh_box = cv2.boundingRect(cnt)
        beans_raw.append({
            "mask": mask, "mask_small": ms, "contour": cnt, "ellipse": ellipse,
            "cx": float(ecx), "cy": float(ecy),
            "x0": x, "y0": y, "x1": x + bw_box, "y1": y + bh_box,
            "area": area,
        })

    print(f"第二輪補偵測後: {len(beans_raw)} 顆")

    # ── IoU NMS（像素遮罩）──────────────────────────────────────────────────
    IOU_THRESH = 0.25

    beans_nms = []
    for b in sorted(beans_raw, key=lambda x: -x["area"]):
        if any(_iou_fast(b["mask_small"], a["mask_small"]) > IOU_THRESH for a in beans_nms):
            continue
        beans_nms.append(b)

    removed = len(beans_raw) - len(beans_nms)
    if removed:
        print(f"IoU NMS 移除重複: {removed} 個")

    beans = beans_nms

    # ── 遮罩清潔：先平滑再解決重疊，確保 blur 不會重新製造重疊 ──────────────
    k_close = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    for b in beans:
        m = cv2.morphologyEx(b["mask"], cv2.MORPH_CLOSE, k_close)
        m_f = cv2.GaussianBlur(m.astype(np.float32), (0, 0), sigmaX=2.0)
        b["mask"] = (m_f >= 0.5).astype(np.uint8)

    # ── 重疊解決：在平滑後的 mask 上做，確保最終無重疊 ──────────────────────
    overlap_count = np.zeros((H, W), dtype=np.uint8)
    for b in beans:
        overlap_count += b["mask"]
    conflict_mask = overlap_count >= 2

    n_conflicts = int(conflict_mask.sum())
    if n_conflicts > 0 and len(beans) > 1:
        print(f"重疊像素: {n_conflicts} px → 分配給最近中心點")
        centers = np.array([[b["cy"], b["cx"]] for b in beans], dtype=np.float32)
        ys, xs = np.where(conflict_mask)
        _, assignments = cKDTree(centers).query(np.column_stack([ys, xs]))
        for b in beans:
            b["mask"][conflict_mask] = 0
        for idx in range(len(ys)):
            beans[assignments[idx]]["mask"][ys[idx], xs[idx]] = 1

    # 更新輪廓與 bounding box
    for b in beans:
        cnts, _ = cv2.findContours(b["mask"], cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if cnts:
            b["contour"] = max(cnts, key=cv2.contourArea)
            x, y2, bw2, bh2 = cv2.boundingRect(b["contour"])
            b["x0"], b["y0"], b["x1"], b["y1"] = x, y2, x + bw2, y2 + bh2

    # ── 後處理：移除過小遮罩 ─────────────────────────────────────────────────
    min_final_area = exp_area * 0.37
    before_area_filter = len(beans)
    beans = [b for b in beans if b["mask"].sum() >= min_final_area]
    if len(beans) < before_area_filter:
        print(f"後處理小面積過濾: {before_area_filter} → {len(beans)} 顆（移除 {before_area_filter - len(beans)} 個）")

    # ── K-means 拆分過大遮罩（兩顆豆合併）──────────────────────────────────
    SPLIT_RATIO = 2.0   # Gaussian blur 使面積微增，需更保守的門檻
    beans_split = []
    for b in beans:
        if b["mask"].sum() > exp_area * SPLIT_RATIO:
            # 形狀檢查：單顆豆圓度高（circ > 0.65），不應拆分
            cnt_b   = b["contour"]
            perim_b = cv2.arcLength(cnt_b, True)
            area_b  = float(b["mask"].sum())
            circ_b  = 4 * np.pi * area_b / (perim_b ** 2) if perim_b > 0 else 0
            (_, _), (ma_b, mb_b), _ = b["ellipse"]
            aspect_b = ma_b / max(mb_b, 1)
            # 若圓度高（單顆）或長寬比低（非花生形），不拆
            if circ_b > 0.65 or aspect_b < 1.6:
                beans_split.append(b)
                continue
            ys_b, xs_b = np.where(b["mask"])
            pts = np.column_stack([xs_b, ys_b]).astype(np.float32)
            criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 100, 1.0)
            try:
                _, lbl, _ = cv2.kmeans(pts, 2, None, criteria, 5, cv2.KMEANS_PP_CENTERS)
                groups = [pts[lbl.flatten() == k] for k in range(2)]
                min_sub = exp_area * 0.45  # 子豆不能太小，避免把單顆大豆拆成碎片
                if all(len(g) >= min_sub for g in groups):
                    for g in groups:
                        sub_mask = np.zeros((H, W), dtype=np.uint8)
                        gx = np.clip(g[:, 0].astype(int), 0, W - 1)
                        gy = np.clip(g[:, 1].astype(int), 0, H - 1)
                        sub_mask[gy, gx] = 1
                        cnts2, _ = cv2.findContours(sub_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                        if not cnts2:
                            continue
                        cnt2 = max(cnts2, key=cv2.contourArea)
                        x2, y2b, bw2, bh2 = cv2.boundingRect(cnt2)
                        try:
                            ell2 = cv2.fitEllipse(cnt2)
                            (ecx2, ecy2), _, _ = ell2
                        except Exception:
                            ecx2, ecy2 = float(g[:, 0].mean()), float(g[:, 1].mean())
                            ell2 = b["ellipse"]
                        beans_split.append({
                            "mask": sub_mask, "contour": cnt2, "ellipse": ell2,
                            "cx": ecx2, "cy": ecy2,
                            "x0": x2, "y0": y2b, "x1": x2 + bw2, "y1": y2b + bh2,
                            "area": int(sub_mask.sum()),
                        })
                    print(f"K-means 拆分: cx={b['cx']:.0f} cy={b['cy']:.0f} area={b['mask'].sum()} → 2 顆")
                    continue
            except Exception:
                pass
        beans_split.append(b)
    beans = beans_split

    # ── CC 補偵測：用未覆蓋前景找回 FastSAM 漏掉的豆子 ────────────────────
    if diff_img is not None and fg_base is not None:
        covered = np.zeros((H, W), dtype=np.uint8)
        for b in beans:
            covered |= b["mask"]

        fg_eroded = cv2.morphologyEx(fg_base, cv2.MORPH_ERODE,
                                      cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7)))
        uncovered = ((fg_eroded > 0).astype(np.uint8)) & (~covered.astype(bool)).astype(np.uint8)
        uncovered = cv2.morphologyEx(uncovered, cv2.MORPH_OPEN,
                                      cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7)))

        n_cc, cc_labels, cc_stats, _ = cv2.connectedComponentsWithStats(uncovered, connectivity=8)
        cc_added = 0
        for cc_id in range(1, n_cc):
            cc_area = int(cc_stats[cc_id, cv2.CC_STAT_AREA])
            if cc_area < min_final_area or cc_area > exp_area * 1.8:
                continue
            cc_mask = (cc_labels == cc_id).astype(np.uint8)

            cc_fg_cover = float((diff_img[cc_mask.astype(bool)] > 20).mean())
            if cc_fg_cover < 0.30:
                continue

            cnts_cc, _ = cv2.findContours(cc_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if not cnts_cc:
                continue
            cnt_cc = max(cnts_cc, key=cv2.contourArea)
            if len(cnt_cc) < 5:
                continue

            perim_cc = cv2.arcLength(cnt_cc, True)
            circ_cc = 4 * np.pi * cc_area / (perim_cc ** 2) if perim_cc > 0 else 0
            print(f"  [CC候選] cx={int(cc_stats[cc_id,0]+cc_stats[cc_id,2]//2):4d} cy={int(cc_stats[cc_id,1]+cc_stats[cc_id,3]//2):4d} area={cc_area:6d} circ={circ_cc:.2f} fg_cover={cc_fg_cover:.2f}")
            if circ_cc < 0.50:
                continue

            try:
                ell_cc = cv2.fitEllipse(cnt_cc)
            except cv2.error:
                continue
            (ecx_cc, ecy_cc), (ma_cc, mb_cc), _ = ell_cc
            if mb_cc < 8 or ma_cc / max(mb_cc, 1) > 4.0:
                continue

            x_cc, y_cc, bw_cc, bh_cc = cv2.boundingRect(cnt_cc)
            beans.append({
                "mask": cc_mask, "contour": cnt_cc, "ellipse": ell_cc,
                "cx": float(ecx_cc), "cy": float(ecy_cc),
                "x0": x_cc, "y0": y_cc, "x1": x_cc + bw_cc, "y1": y_cc + bh_cc,
                "area": cc_area,
            })
            covered |= cc_mask
            cc_added += 1
            print(f"  CC補偵測: cx={ecx_cc:.0f} cy={ecy_cc:.0f} area={cc_area} circ={circ_cc:.2f} fg_cover={cc_fg_cover:.2f}")
        if cc_added:
            print(f"CC 補偵測: 新增 {cc_added} 顆")

    # ── 排序（上→下，左→右）────────────────────────────────────────────────
    beans.sort(key=lambda b: (round(b["cy"] / 80) * 80 + b["cx"] / 10000))

    print(f"\n最終豆子數: {len(beans)} 顆（目標 {EXPECTED_BEANS}）")
    if beans:
        areas = [b["area"] for b in beans]
        print(f"面積: min={min(areas)}  max={max(areas)}  mean={np.mean(areas):.0f}")

    # ── 建立 label map 和 ROI JSON ─────────────────────────────────────────
    lmap = np.zeros((H, W), dtype=np.uint8)
    rois = []
    for new_id, b in enumerate(beans, start=1):
        b["id"] = new_id
        lmap[b["mask"].astype(bool)] = new_id
        rois.append({"id": new_id,
                     "x0": b["x0"], "y0": b["y0"],
                     "x1": b["x1"], "y1": b["y1"]})

    Image.fromarray(lmap).save(OUT_LMAP)
    with open(OUT_ROIS, "w") as f:
        json.dump(rois, f, indent=2)
    print(f"Label map → {OUT_LMAP}")
    print(f"ROIs JSON → {OUT_ROIS}")

    # ── 視覺化（輪廓 + 編號）────────────────────────────────────────────────
    vis_src = cv2.imread(
        os.path.join(SESSION_DIR, "capture_1250us_gray.png") if os.path.exists(
            os.path.join(SESSION_DIR, "capture_1250us_gray.png")) else GRAY_PNG,
        cv2.IMREAD_GRAYSCALE,
    )
    vis = cv2.cvtColor(vis_src if vis_src is not None else gray, cv2.COLOR_GRAY2BGR)

    palette = [
        (0, 220, 80), (0, 180, 255), (255, 100, 0), (200, 50, 255),
        (0, 255, 200), (255, 200, 0), (100, 220, 100), (255, 80, 180),
        (80, 200, 255), (255, 160, 40),
    ]

    for b in beans:
        nid = b["id"]
        col = palette[(nid - 1) % len(palette)]
        # 直接從平滑後的 mask 取輪廓（不做 convex hull 填補，避免越界到鄰豆）
        cnts_v, _ = cv2.findContours(b["mask"], cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        cnt_f = max(cnts_v, key=cv2.contourArea) if cnts_v else b["contour"]
        pts = cnt_f.squeeze()
        if pts.ndim == 2 and len(pts) > 6:
            sx = gaussian_filter1d(pts[:, 0].astype(np.float32), sigma=5, mode='wrap')
            sy = gaussian_filter1d(pts[:, 1].astype(np.float32), sigma=5, mode='wrap')
            cnt_smooth = np.stack([sx, sy], axis=1).astype(np.int32).reshape(-1, 1, 2)
            cv2.drawContours(vis, [cnt_smooth], -1, col, 2, cv2.LINE_AA)
        else:
            cv2.drawContours(vis, [cnt_f], -1, col, 2, cv2.LINE_AA)

        label = str(nid)
        fs, fw = 0.42, 1
        cx_i, cy_i = int(b["cx"]), int(b["cy"])
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, fs, fw)
        cv2.rectangle(vis, (cx_i - tw//2 - 1, cy_i - th - 1),
                           (cx_i + tw//2 + 1, cy_i + 2), (0, 0, 0), -1)
        cv2.putText(vis, label, (cx_i - tw//2, cy_i),
                    cv2.FONT_HERSHEY_SIMPLEX, fs, col, fw, cv2.LINE_AA)

    cv2.putText(vis, f"Beans: {len(beans)} [FastSAM]", (12, 36),
                cv2.FONT_HERSHEY_SIMPLEX, 1.1, (0, 255, 80), 3, cv2.LINE_AA)
    cv2.imwrite(OUT_VIZ, vis)
    print(f"輪廓圖 → {OUT_VIZ}")
    print(f"\n完成！FastSAM 分割 {len(beans)} 顆（目標 {EXPECTED_BEANS}）")
    return len(beans)


if __name__ == "__main__":
    SESSION_DIR    = sys.argv[1] if len(sys.argv) > 1 else "/home/kyle/Desktop/GigaImage_20260504_003754"
    EXPECTED_BEANS = int(sys.argv[2])   if len(sys.argv) > 2 else 51
    SAM_CONF       = float(sys.argv[3]) if len(sys.argv) > 3 else 0.35
    SAM_IMGSZ      = int(sys.argv[4])   if len(sys.argv) > 4 else 1024

    from ultralytics import FastSAM
    _model = FastSAM(MODEL_PATH)
    run(SESSION_DIR, EXPECTED_BEANS, _model, SAM_CONF, SAM_IMGSZ)
