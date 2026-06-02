#!/usr/bin/env python3
"""
mold_intrabean.py
對 HIGH/MED 可疑豆子做豆內網格分析（5x5），
找出豆內哪個區塊光譜最異常，只圈出異常區域。
"""
import csv, os, json, subprocess
import numpy as np
import cv2
from PIL import Image, ImageDraw

BEAN_DIR  = "/home/kyle/Desktop/GigaImage_20260413_174159"
OUT_DIR   = "/home/kyle/Desktop/mold_detection"
BUILD_DIR = "/home/kyle/KyleClaude/multispectral_demo/build"
QSBS      = "/home/kyle/KyleClaude/camera_new.qsbs"
QSDB      = "/home/kyle/KyleClaude/db_std.qsdb"
SDK       = "/home/kyle/KyleClaude/sdk_extract/linux-sdk-arm64/qssdk-20250817"
WHITE_REF = "/home/kyle/Desktop/GigaImage_20260413_165855/capture_001.qs"
QS_FILE   = os.path.join(BEAN_DIR, "capture_000_10000us.qs")

env = os.environ.copy()
env["LD_LIBRARY_PATH"] = f"{SDK}:{SDK}/libarm64/spinvcore:{SDK}/libarm64/opencv/lib"

os.makedirs(OUT_DIR, exist_ok=True)

# ── 1. 重建分割，取得各豆位置 ─────────────────────────────────────────────────
img_seg = cv2.imread(os.path.join(BEAN_DIR, "capture_001_5000us.png"),
                     cv2.IMREAD_GRAYSCALE)

def find_beans(gray, thresh, min_area=800, max_area=8000):
    _, bw = cv2.threshold(gray, thresh, 255, cv2.THRESH_BINARY_INV)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5,5))
    bw = cv2.morphologyEx(bw, cv2.MORPH_OPEN, kernel, iterations=2)
    num, labels, stats, centroids = cv2.connectedComponentsWithStats(bw)
    beans = []
    for j in range(1, num):
        area = stats[j, cv2.CC_STAT_AREA]
        if min_area < area < max_area:
            beans.append({
                "cx": centroids[j][0], "cy": centroids[j][1],
                "x0": stats[j, cv2.CC_STAT_LEFT],
                "y0": stats[j, cv2.CC_STAT_TOP],
                "x1": stats[j, cv2.CC_STAT_LEFT] + stats[j, cv2.CC_STAT_WIDTH],
                "y1": stats[j, cv2.CC_STAT_TOP]  + stats[j, cv2.CC_STAT_HEIGHT],
            })
    return beans

beans_t80 = find_beans(img_seg, 80)
beans_t65 = find_beans(img_seg, 65)
final_beans = list(beans_t80)
for b65 in beans_t65:
    if not any(np.hypot(b65["cx"]-b["cx"], b65["cy"]-b["cy"]) < 30 for b in final_beans):
        final_beans.append(b65)
final_beans.sort(key=lambda b: (round(b["cy"]/120)*120 + b["cx"]/10000))
print(f"分割到 {len(final_beans)} 顆豆子")

# ── 2. 可疑豆（Bean 17=idx16, Bean 18=idx17, Bean 5=idx4）─────────────────────
# 從昨天分析結果，0-indexed
SUSPECT = {16: "HIGH", 17: "HIGH", 4: "MED"}

# ── 3. 讀正常豆的平均光譜作為基準 ────────────────────────────────────────────
csv_path = os.path.join(BEAN_DIR, "spec_fingerprint_20beans.csv")
bands, all_specs = [], {}
with open(csv_path) as f:
    reader = csv.DictReader(f)
    keys = [k for k in reader.fieldnames if k.startswith("bean_")]
    for row in reader:
        bands.append(int(float(row["wavelength_nm"])))
        for k in keys:
            all_specs.setdefault(k, []).append(float(row[k]))
bands = np.array(bands)

# 正常豆（非 HIGH/MED 的 0-indexed）
ok_indices = [i for i in range(20) if i not in SUSPECT]
normal_mean = np.mean([all_specs[f"bean_{i+1}"] for i in ok_indices], axis=0)
normal_std  = np.std( [all_specs[f"bean_{i+1}"] for i in ok_indices], axis=0) + 1e-9

def anomaly_score(spec):
    """相對於正常均值的 z-score 平均"""
    z = np.abs((np.array(spec) - normal_mean) / normal_std)
    # 加重 UV 及藍光區（350-490nm 為黴菌指標波段）
    weights = np.where(bands <= 490, 2.0, 1.0)
    return np.average(z, weights=weights)

# ── 4. 對每顆可疑豆做 5x5 細格分析 ──────────────────────────────────────────
GRID = 5       # 豆內網格大小
MIN_CELL = 10  # 最小格子邊長（像素）
ANOMALY_TOP = 0.30  # 取最異常的前 30% 格子圈起來

all_suspect_cells = {}   # bean_idx → [(cx,cy,score), ...]

for bean_idx in SUSPECT:
    if bean_idx >= len(final_beans):
        print(f"[WARN] Bean {bean_idx+1} 超出分割範圍，跳過")
        continue
    b = final_beans[bean_idx]
    bw = int(b["x1"] - b["x0"])
    bh = int(b["y1"] - b["y0"])

    cell_w = max(bw // GRID, MIN_CELL)
    cell_h = max(bh // GRID, MIN_CELL)
    actual_cols = bw // cell_w
    actual_rows = bh // cell_h
    print(f"\nBean {bean_idx+1}：bbox={bw}x{bh}px → {actual_rows}x{actual_cols} 格")

    # 建 ROI list
    rois, cell_map = [], []
    roi_id = 1
    for row in range(actual_rows):
        for col in range(actual_cols):
            x0 = int(b["x0"]) + col * cell_w + 2
            y0 = int(b["y0"]) + row * cell_h + 2
            x1 = x0 + cell_w - 4
            y1 = y0 + cell_h - 4
            if x1 <= x0 or y1 <= y0:
                continue
            rois.append({"id": roi_id, "x0": x0, "y0": y0, "x1": x1, "y1": y1})
            cell_map.append({"id": roi_id, "row": row, "col": col,
                             "cx": (x0+x1)//2, "cy": (y0+y1)//2})
            roi_id += 1

    # 建 label map
    lmap = np.zeros((1200, 1600), dtype=np.uint8)
    for r in rois:
        lmap[r["y0"]:r["y1"], r["x0"]:r["x1"]] = r["id"]
    lmap_path = os.path.join(OUT_DIR, f"bean{bean_idx+1}_lmap.png")
    Image.fromarray(lmap).save(lmap_path)

    rois_path = os.path.join(OUT_DIR, f"bean{bean_idx+1}_rois.json")
    with open(rois_path, "w") as f:
        json.dump(rois, f)

    csv_out = os.path.join(OUT_DIR, f"bean{bean_idx+1}_grid_spec.csv")
    cmd = [f"{BUILD_DIR}/spec_fingerprint",
           QSBS, QSDB, QS_FILE, rois_path, csv_out, lmap_path, WHITE_REF]
    ret = subprocess.run(cmd, env=env, capture_output=True, text=True)
    if ret.returncode != 0:
        print(f"  [ERROR] {ret.stderr[-300:]}")
        continue

    # 讀 CSV → 計算每格異常分數
    grid_scores = {}
    with open(csv_out) as f:
        reader = csv.DictReader(f)
        bkeys = [k for k in reader.fieldnames if k.startswith("bean_")]
        rows_data = list(reader)

    for bk in bkeys:
        cell_id = int(bk.split("_")[1])
        spec = [float(row[bk]) for row in rows_data]
        grid_scores[cell_id] = anomaly_score(spec)

    # 排序，取前 TOP% 格子
    sorted_cells = sorted(grid_scores.items(), key=lambda x: x[1], reverse=True)
    n_top = max(1, int(len(sorted_cells) * ANOMALY_TOP))
    top_ids = {cid for cid, _ in sorted_cells[:n_top]}

    suspect_cells = []
    for cm in cell_map:
        if cm["id"] in top_ids:
            suspect_cells.append((cm["cx"], cm["cy"], grid_scores[cm["id"]],
                                  cell_w-4, cell_h-4))
    all_suspect_cells[bean_idx] = suspect_cells
    print(f"  異常格：{len(suspect_cells)}/{len(grid_scores)} 個")

# ── 5. 在原圖標示 ────────────────────────────────────────────────────────────
orig = cv2.cvtColor(
    cv2.imread(os.path.join(BEAN_DIR, "capture_001_5000us.png")),
    cv2.COLOR_BGR2RGB)
vis = Image.fromarray(orig).convert("RGBA")

for bean_idx, level in SUSPECT.items():
    if bean_idx >= len(final_beans):
        continue
    b = final_beans[bean_idx]
    cx, cy = int(b["cx"]), int(b["cy"])
    bw = int(b["x1"]-b["x0"])

    # 豆子外框（細線）
    border_color = (255, 60, 60) if level == "HIGH" else (255, 165, 0)
    draw = ImageDraw.Draw(vis)
    r = bw // 2 + 6
    for lw in range(2):
        draw.ellipse([cx-r-lw, cy-r-lw, cx+r+lw, cy+r+lw],
                     outline=border_color + (200,))

    # 豆號標籤
    draw.rectangle([cx-18, cy-r-22, cx+30, cy-r-4], fill=(0,0,0,160))
    draw.text((cx-14, cy-r-20), f"B{bean_idx+1} {level}", fill=border_color+(255,))

    # 豆內異常區域：半透明橢圓
    if bean_idx in all_suspect_cells:
        overlay = Image.new("RGBA", vis.size, (0,0,0,0))
        ov_draw = ImageDraw.Draw(overlay)
        cells = all_suspect_cells[bean_idx]
        max_s = max(s for _,_,s,_,_ in cells) if cells else 1
        for (ccx, ccy, sc, cw, ch) in cells:
            alpha = int(80 + 120 * sc / max_s)
            rw, rh = cw//2+2, ch//2+2
            ov_draw.ellipse([ccx-rw, ccy-rh, ccx+rw, ccy+rh],
                            fill=(255, 30, 30, alpha),
                            outline=(255, 80, 80, 220))
        vis = Image.alpha_composite(vis, overlay)

# 正常豆加淡綠框
draw = ImageDraw.Draw(vis)
for i, b in enumerate(final_beans[:20]):
    if i in SUSPECT:
        continue
    cx, cy = int(b["cx"]), int(b["cy"])
    r = int((b["x1"]-b["x0"])//2) + 4
    draw.ellipse([cx-r, cy-r, cx+r, cy+r], outline=(80, 200, 80, 160))
    draw.rectangle([cx-14, cy-r-18, cx+18, cy-r-4], fill=(0,0,0,120))
    draw.text((cx-10, cy-r-16), f"B{i+1}", fill=(80,220,80,255))

# 圖例
draw.rectangle([8, 8, 220, 90], fill=(0,0,0,180))
draw.text((14, 12), "Mold Risk Detection", fill=(255,255,255,255))
draw.ellipse([14,30,26,42], outline=(255,60,60,255))
draw.text((32, 30), "HIGH - anomalous region", fill=(255,160,160,255))
draw.ellipse([14,48,26,60], outline=(255,165,0,255))
draw.text((32, 48), "MED  - anomalous region", fill=(255,220,160,255))
draw.ellipse([14,66,26,78], outline=(80,200,80,255))
draw.text((32, 66), "Normal bean", fill=(160,255,160,255))

out_path = os.path.join(OUT_DIR, "mold_intrabean_labeled.png")
vis.convert("RGB").save(out_path)
print(f"\n[OK] 豆內異常標示圖：{out_path}")
