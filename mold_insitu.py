#!/usr/bin/env python3
"""
mold_insitu.py
用同一張影像的局部白紙背景做 in-situ flat-field 校正，
消除跨場次照明差異，重新做黴菌異常偵測。
"""
import json, os, csv, subprocess
import numpy as np
import cv2
from PIL import Image, ImageDraw

BEAN_DIR  = "/home/kyle/Desktop/GigaImage_20260413_174159"
OUT_DIR   = "/home/kyle/Desktop/mold_detection"
BUILD_DIR = "/home/kyle/KyleClaude/multispectral_demo/build"
QSBS      = "/home/kyle/KyleClaude/camera_new.qsbs"
QSDB      = "/home/kyle/KyleClaude/db_std.qsdb"
SDK       = "/home/kyle/KyleClaude/sdk_extract/linux-sdk-arm64/qssdk-20250817"
QS_FILE   = os.path.join(BEAN_DIR, "capture_000_10000us.qs")

env = os.environ.copy()
env["LD_LIBRARY_PATH"] = f"{SDK}:{SDK}/libarm64/spinvcore:{SDK}/libarm64/opencv/lib"
os.makedirs(OUT_DIR, exist_ok=True)

# ── 1. 重建分割 ───────────────────────────────────────────────────────────────
img_seg = cv2.imread(os.path.join(BEAN_DIR, "capture_001_5000us.png"),
                     cv2.IMREAD_GRAYSCALE)
H, W = img_seg.shape

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
                "x0": int(stats[j, cv2.CC_STAT_LEFT]),
                "y0": int(stats[j, cv2.CC_STAT_TOP]),
                "x1": int(stats[j, cv2.CC_STAT_LEFT] + stats[j, cv2.CC_STAT_WIDTH]),
                "y1": int(stats[j, cv2.CC_STAT_TOP]  + stats[j, cv2.CC_STAT_HEIGHT]),
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

# ── 2. 建立所有豆子的遮罩（用於排除背景 ROI 時避開其他豆）────────────────────
bean_mask = np.zeros((H, W), dtype=np.uint8)
for b in final_beans:
    bean_mask[b["y0"]:b["y1"], b["x0"]:b["x1"]] = 1

# ── 3. 建立 ROI：每顆豆子 + 它周圍的背景採樣框 ───────────────────────────────
PAD = 25          # 豆子外框往外擴多少 px 才開始取背景
BG_W = 20         # 背景框的寬度（px）
rois = []
roi_id = 1
bean_roi_ids = {}    # bean_idx → bean_roi_id
bg_roi_ids   = {}    # bean_idx → list of bg_roi_ids

for i, b in enumerate(final_beans[:20]):
    cx, cy = int(b["cx"]), int(b["cy"])
    bw = b["x1"] - b["x0"]
    bh = b["y1"] - b["y0"]
    r = max(bw, bh) // 2

    # 豆子本身 ROI
    bean_roi_ids[i] = roi_id
    rois.append({"id": roi_id,
                 "x0": max(0, b["x0"]), "y0": max(0, b["y0"]),
                 "x1": min(W, b["x1"]), "y1": min(H, b["y1"])})
    roi_id += 1

    # 上下左右 4 個背景採樣框
    bg_ids = []
    candidates = [
        # top
        (max(0, cx-BG_W), max(0, cy-r-PAD-BG_W), cx+BG_W, max(0, cy-r-PAD)),
        # bottom
        (max(0, cx-BG_W), min(H, cy+r+PAD),       cx+BG_W, min(H, cy+r+PAD+BG_W)),
        # left
        (max(0, cx-r-PAD-BG_W), max(0, cy-BG_W),  max(0, cx-r-PAD), cy+BG_W),
        # right
        (min(W, cx+r+PAD), max(0, cy-BG_W),        min(W, cx+r+PAD+BG_W), cy+BG_W),
    ]
    for (x0, y0, x1, y1) in candidates:
        if x1 <= x0+5 or y1 <= y0+5:
            continue
        # 確認這個框內沒有其他豆子
        region = bean_mask[y0:y1, x0:x1]
        if region.mean() > 0.3:    # 超過 30% 被豆子覆蓋就跳過
            continue
        rois.append({"id": roi_id, "x0": x0, "y0": y0, "x1": x1, "y1": y1})
        bg_ids.append(roi_id)
        roi_id += 1

    bg_roi_ids[i] = bg_ids

print(f"共 {len(rois)} 個 ROI（豆子 + 背景採樣）")

# ── 4. 建 label map 並執行 spec_fingerprint ───────────────────────────────────
lmap = np.zeros((H, W), dtype=np.uint8)
for r in rois:
    lmap[r["y0"]:r["y1"], r["x0"]:r["x1"]] = r["id"]

lmap_path  = os.path.join(OUT_DIR, "insitu_lmap.png")
rois_path  = os.path.join(OUT_DIR, "insitu_rois.json")
csv_out    = os.path.join(OUT_DIR, "insitu_spec.csv")
Image.fromarray(lmap).save(lmap_path)
with open(rois_path, "w") as f:
    json.dump(rois, f)

print("執行 spec_fingerprint（不帶 white_ref，用原始值）...")
cmd = [f"{BUILD_DIR}/spec_fingerprint",
       QSBS, QSDB, QS_FILE, rois_path, csv_out, lmap_path]
ret = subprocess.run(cmd, env=env, capture_output=True, text=True)
if ret.returncode != 0:
    print(f"[ERROR]\n{ret.stderr[-500:]}")
    exit(1)
print(ret.stdout.strip())

# ── 5. 讀 CSV，計算局部校正光譜 ──────────────────────────────────────────────
bands_list, raw = [], {}
with open(csv_out) as f:
    reader = csv.DictReader(f)
    bkeys = [k for k in reader.fieldnames if k.startswith("bean_")]
    rows = list(reader)
for bk in bkeys:
    rid = int(bk.split("_")[1])
    raw[rid] = np.array([float(row[bk]) for row in rows])
bands = np.array([int(float(row["wavelength_nm"])) for row in rows])

# 局部校正：每顆豆的光譜 ÷ 周圍背景均值
corrected = {}
bg_spectra = {}
for i in range(len(final_beans[:20])):
    bean_id = bean_roi_ids[i]
    bg_ids  = bg_roi_ids[i]
    if bean_id not in raw:
        print(f"  [WARN] Bean {i+1} ROI 無數據")
        continue
    bean_spec = raw[bean_id]
    # 背景：取有效的背景框均值
    bg_available = [raw[bid] for bid in bg_ids if bid in raw]
    if not bg_available:
        print(f"  [WARN] Bean {i+1} 無背景採樣")
        corrected[i] = bean_spec
        continue
    bg_mean = np.mean(bg_available, axis=0)
    bg_spectra[i] = bg_mean
    corrected[i] = bean_spec / (bg_mean + 1e-9)   # 局部校正反射率

print(f"\n成功校正 {len(corrected)} 顆豆子")

# ── 6. 異常分數（同前，但用局部校正後的光譜）─────────────────────────────────
X = np.array([corrected[i] for i in range(len(corrected))])
n = len(X)
X_mean = X.mean(axis=0)
X_std  = X.std(axis=0) + 1e-9

def band_idx(nm):
    return np.argmin(np.abs(bands - nm))

idx_uv       = X[:, band_idx(350)] / (X[:, band_idx(490)] + 1e-9)
b410 = X[:, band_idx(410)]; b450 = X[:, band_idx(450)]; b490 = X[:, band_idx(490)]
interp_450   = b410 + (b490 - b410) * (450-410)/(490-410)
idx_blue_dip = (interp_450 - b450) / (interp_450 + 1e-9)
U, s, Vt     = np.linalg.svd(X - X_mean, full_matrices=False)
pc_scores    = U[:,:5] * s[:5]
idx_pca      = np.sqrt(((pc_scores - pc_scores.mean(0)) / (pc_scores.std(0)+1e-9))**2).mean(1)
idx_nir      = (X[:, band_idx(930)] - X[:, band_idx(850)]) / (X[:, band_idx(850)] + 1e-9)

def norm(v): return (v - v.min()) / (v.max() - v.min() + 1e-9)

score = (norm(1 - idx_uv)*0.35 + norm(idx_blue_dip)*0.25 +
         norm(idx_pca)*0.25    + norm(-idx_nir)*0.15)
mean_s, std_s = score.mean(), score.std()
levels = ["HIGH" if s > mean_s+1.5*std_s else "MED" if s > mean_s+0.8*std_s else "OK"
          for s in score]

print("\n========== in-situ 校正後 黴菌異常分數 ==========")
for rank, i in enumerate(np.argsort(score)[::-1]):
    flag = {"HIGH":"⚠⚠ 高度懷疑","MED":"⚠  中度懷疑","OK":"✓  正常"}[levels[i]]
    print(f"  #{rank+1:2d}  Bean {i+1:2d}  分數={score[i]:.3f}  {flag}")
print("====================================================")

# ── 7. 視覺化：標示圖 ─────────────────────────────────────────────────────────
orig = cv2.cvtColor(cv2.imread(os.path.join(BEAN_DIR, "capture_001_5000us.png")),
                    cv2.COLOR_BGR2RGB)
vis = Image.fromarray(orig).convert("RGBA")

border_map = {"HIGH":(255,60,60),"MED":(255,165,0),"OK":(80,200,80)}

for i, b in enumerate(final_beans[:20]):
    lv = levels[i]; sc = score[i]
    cx, cy = int(b["cx"]), int(b["cy"])
    r  = max(b["x1"]-b["x0"], b["y1"]-b["y0"])//2 + 5
    bc = border_map[lv]
    draw = ImageDraw.Draw(vis)
    lw = 3 if lv == "HIGH" else 2
    for d in range(lw):
        draw.ellipse([cx-r-d, cy-r-d, cx+r+d, cy+r+d], outline=bc+(220,))

    # 背景採樣框（淡藍色，小框）
    for bid in bg_roi_ids.get(i, []):
        roi = next((r for r in rois if r["id"]==bid), None)
        if roi:
            draw.rectangle([roi["x0"],roi["y0"],roi["x1"],roi["y1"]],
                           outline=(100,180,255,120))

    # 標籤
    draw.rectangle([cx-16, cy-r-20, cx+32, cy-r-4], fill=(0,0,0,160))
    draw.text((cx-12, cy-r-18), f"B{i+1}", fill=bc+(255,))
    if lv != "OK":
        draw.text((cx+4,  cy-r-18), f"{lv}", fill=bc+(255,))

# 圖例
draw = ImageDraw.Draw(vis)
draw.rectangle([8,8,240,100], fill=(0,0,0,180))
draw.text((14,12), "In-situ Flat-Field Correction", fill=(255,255,255,255))
draw.ellipse([14,30,26,42], outline=(255,60,60,255))
draw.text((32,30), "HIGH - suspected mold", fill=(255,160,160,255))
draw.ellipse([14,48,26,60], outline=(255,165,0,255))
draw.text((32,48), "MED  - monitor",        fill=(255,220,160,255))
draw.ellipse([14,66,26,78], outline=(80,200,80,255))
draw.text((32,66), "OK   - normal",         fill=(160,255,160,255))
draw.rectangle([14,82,26,90], fill=(100,180,255,160))
draw.text((32,82), "local BG sample",       fill=(180,220,255,255))

out_path = os.path.join(OUT_DIR, "mold_insitu_labeled.png")
vis.convert("RGB").save(out_path)
print(f"\n[OK] {out_path}")

# ── 8. 光譜比較圖 ────────────────────────────────────────────────────────────
import matplotlib
matplotlib.rcParams['font.family'] = 'DejaVu Sans'
import matplotlib.pyplot as plt

high_idx = [i for i,l in enumerate(levels) if l=="HIGH"]
med_idx  = [i for i,l in enumerate(levels) if l=="MED"]
ok_idx   = [i for i,l in enumerate(levels) if l=="OK"]

fig, ax = plt.subplots(figsize=(13,5))
for i in ok_idx:
    ax.plot(bands, X[i], color='green', alpha=0.2, lw=1)
ok_mean_c = X[ok_idx].mean(axis=0) if ok_idx else X.mean(axis=0)
ax.plot(bands, ok_mean_c, 'g--', lw=2, label='Normal mean')
for i in med_idx:
    ax.plot(bands, X[i], color='orange', lw=1.8, alpha=0.8, label=f"Bean {i+1} MED")
for i in high_idx:
    ax.plot(bands, X[i], color='red', lw=2.2, label=f"Bean {i+1} HIGH")
ax.axhline(1.0, color='gray', ls='--', lw=1)
ax.set_title("In-situ corrected spectra (bean / local background)", fontsize=12, fontweight='bold')
ax.set_xlabel("Wavelength (nm)")
ax.set_ylabel("Local-corrected reflectance")
ax.legend(fontsize=8)
ax.grid(True, alpha=0.3)
ax.set_xticks(bands)
ax.set_xticklabels([str(b) for b in bands], rotation=45, fontsize=7)
plt.tight_layout()
plt.savefig(os.path.join(OUT_DIR, "mold_insitu_spectrum.png"), dpi=150)
plt.close()
print(f"[OK] 光譜圖已存")
