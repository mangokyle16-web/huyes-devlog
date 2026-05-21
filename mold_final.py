#!/usr/bin/env python3
"""
mold_final.py
最終黴菌異常偵測：
  - 主指標：Mahalanobis distance（PCA 空間，全波段相關性）
  - 差分圖：z-score per band（偏差幾個 sigma，方便與 365nm UV 對齊比較）
  - 特別標注 UV 區（350-450nm）的 z-score，最接近 365nm 螢光指標
"""
import csv, os, json
import numpy as np
import cv2
from PIL import Image, ImageDraw
import matplotlib
matplotlib.rcParams['font.family'] = 'DejaVu Sans'
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec

BEAN_DIR = "/home/kyle/Desktop/GigaImage_20260413_174159"
OUT_DIR  = "/home/kyle/Desktop/mold_detection"
os.makedirs(OUT_DIR, exist_ok=True)

# ── 1. 重建 in-situ 校正光譜（同 mold_insitu.py）─────────────────────────────
def find_beans(gray, thresh, min_area=800, max_area=8000):
    _, bw = cv2.threshold(gray, thresh, 255, cv2.THRESH_BINARY_INV)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5,5))
    bw = cv2.morphologyEx(bw, cv2.MORPH_OPEN, kernel, iterations=2)
    num, labels, stats, centroids = cv2.connectedComponentsWithStats(bw)
    return [{"cx":centroids[j][0],"cy":centroids[j][1],
             "x0":int(stats[j,cv2.CC_STAT_LEFT]),
             "y0":int(stats[j,cv2.CC_STAT_TOP]),
             "x1":int(stats[j,cv2.CC_STAT_LEFT]+stats[j,cv2.CC_STAT_WIDTH]),
             "y1":int(stats[j,cv2.CC_STAT_TOP]+stats[j,cv2.CC_STAT_HEIGHT])}
            for j in range(1,num)
            if min_area < stats[j,cv2.CC_STAT_AREA] < max_area]

img_seg = cv2.imread(f"{BEAN_DIR}/capture_001_5000us.png", cv2.IMREAD_GRAYSCALE)
H, W = img_seg.shape
final_beans = list(find_beans(img_seg, 80))
for b in find_beans(img_seg, 65):
    if not any(np.hypot(b["cx"]-fb["cx"],b["cy"]-fb["cy"])<30 for fb in final_beans):
        final_beans.append(b)
final_beans.sort(key=lambda b:(round(b["cy"]/120)*120+b["cx"]/10000))

bean_mask = np.zeros((H,W), dtype=np.uint8)
for b in final_beans: bean_mask[b["y0"]:b["y1"],b["x0"]:b["x1"]] = 1

PAD, BG_W = 25, 20
bean_roi_ids, bg_roi_ids = {}, {}
roi_id = 1
for i, b in enumerate(final_beans[:20]):
    cx,cy = int(b["cx"]),int(b["cy"])
    r = max(b["x1"]-b["x0"],b["y1"]-b["y0"])//2
    bean_roi_ids[i] = roi_id; roi_id += 1
    bg_ids = []
    for (x0,y0,x1,y1) in [
        (max(0,cx-BG_W),max(0,cy-r-PAD-BG_W),cx+BG_W,max(0,cy-r-PAD)),
        (max(0,cx-BG_W),min(H,cy+r+PAD),cx+BG_W,min(H,cy+r+PAD+BG_W)),
        (max(0,cx-r-PAD-BG_W),max(0,cy-BG_W),max(0,cx-r-PAD),cy+BG_W),
        (min(W,cx+r+PAD),max(0,cy-BG_W),min(W,cx+r+PAD+BG_W),cy+BG_W),
    ]:
        if x1<=x0+5 or y1<=y0+5: continue
        if bean_mask[y0:y1,x0:x1].mean()>0.3: continue
        bg_ids.append(roi_id); roi_id += 1
    bg_roi_ids[i] = bg_ids

raw = {}
with open(f"{OUT_DIR}/insitu_spec.csv") as f:
    reader = csv.DictReader(f)
    bkeys = [k for k in reader.fieldnames if k.startswith("bean_")]
    rows = list(reader)
for bk in bkeys:
    raw[int(bk.split("_")[1])] = np.array([float(row[bk]) for row in rows])
bands = np.array([int(float(row["wavelength_nm"])) for row in rows])

corrected = {}
for i in range(20):
    bid = bean_roi_ids[i]
    if bid not in raw: continue
    bg = [raw[k] for k in bg_roi_ids.get(i,[]) if k in raw]
    corrected[i] = raw[bid] / (np.mean(bg,axis=0)+1e-9) if bg else raw[bid]

X = np.array([corrected[i] for i in range(20)])   # (20, 30)

# ── 2. Mahalanobis distance（PCA 空間）────────────────────────────────────────
X_mean = X.mean(axis=0)
X_c    = X - X_mean
U, s, Vt = np.linalg.svd(X_c, full_matrices=False)
n_pc = 6   # 保留前 6 個主成分
pc_scores = U[:,:n_pc] * s[:n_pc]   # (20, 6)
pc_mean = pc_scores.mean(axis=0)
pc_cov  = np.cov(pc_scores.T) + np.eye(n_pc)*1e-6
pc_cov_inv = np.linalg.inv(pc_cov)

mahal = np.array([
    float(np.sqrt((pc_scores[i]-pc_mean) @ pc_cov_inv @ (pc_scores[i]-pc_mean)))
    for i in range(20)
])

# ── 3. Z-score per band ───────────────────────────────────────────────────────
X_std = X.std(axis=0) + 1e-9
Z = (X - X_mean) / X_std   # (20, 30)  每顆豆在各波段的 z-score

# UV 區平均 z-score（350-450nm，最接近 365nm UV 指標）
uv_mask = bands <= 450
uv_z = Z[:, uv_mask].mean(axis=1)   # 負值 = UV 反射偏低 = 可疑

# ── 4. 綜合判定 ───────────────────────────────────────────────────────────────
# 主要用 Mahalanobis，UV z-score 作為輔助確認
mahal_mean, mahal_std = mahal.mean(), mahal.std()
levels = []
for i in range(20):
    if mahal[i] > mahal_mean + 1.5*mahal_std:
        levels.append("HIGH")
    elif mahal[i] > mahal_mean + 0.8*mahal_std:
        levels.append("MED")
    else:
        levels.append("OK")

print("========== 最終黴菌異常偵測（Mahalanobis + UV z-score）==========")
print(f"  {'Bean':>6} {'Mahal':>7} {'UV z-score':>11} {'Level':>6}  備註")
for rank, i in enumerate(np.argsort(mahal)[::-1]):
    uv_flag = " ← UV 吸收異常" if uv_z[i] < -0.5 else ""
    lv_sym  = {"HIGH":"⚠⚠","MED":"⚠ ","OK":"✓ "}[levels[i]]
    print(f"  #{rank+1:2d}  Bean {i+1:2d}  {mahal[i]:>6.2f}  {uv_z[i]:>+10.2f}  {lv_sym} {levels[i]}{uv_flag}")
print("==================================================================")

high_idx = [i for i,l in enumerate(levels) if l=="HIGH"]
med_idx  = [i for i,l in enumerate(levels) if l=="MED"]
ok_idx   = [i for i,l in enumerate(levels) if l=="OK"]
ok_mean  = X[ok_idx].mean(axis=0)
ok_std   = X[ok_idx].std(axis=0) + 1e-9

# ── 5. 主圖：3 欄 ─────────────────────────────────────────────────────────────
# 左：光譜疊加  中：z-score 熱力圖（20豆×30波段）  右：Mahalanobis 排名
fig = plt.figure(figsize=(18, 8))
gs  = gridspec.GridSpec(1, 3, width_ratios=[2, 2.5, 1.2], wspace=0.35)

# ── 左：光譜疊加 ──────────────────────────────────────────────────────────────
ax_spec = fig.add_subplot(gs[0])
for i in ok_idx:
    ax_spec.plot(bands, X[i], color='#2ecc71', alpha=0.25, lw=1)
ax_spec.plot(bands, ok_mean, color='#27ae60', lw=2, ls='--', label='Normal mean')
ax_spec.fill_between(bands, ok_mean-ok_std, ok_mean+ok_std,
                     alpha=0.12, color='green', label='±1 std')
for i in med_idx:
    ax_spec.plot(bands, X[i], color='#f39c12', lw=1.8, alpha=0.85,
                 label=f"Bean {i+1} (MED)")
for i in high_idx:
    ax_spec.plot(bands, X[i], color='#e74c3c', lw=2.2,
                 label=f"Bean {i+1} (HIGH)")
ax_spec.axvspan(350, 450, alpha=0.10, color='purple', label='UV zone (365nm ref)')
ax_spec.axhline(1.0, color='gray', ls=':', lw=1)
ax_spec.set_title("Spectral Fingerprint\n(in-situ corrected)", fontsize=10, fontweight='bold')
ax_spec.set_xlabel("Wavelength (nm)"); ax_spec.set_ylabel("Local reflectance")
ax_spec.legend(fontsize=7, loc='upper left')
ax_spec.grid(True, alpha=0.25)
ax_spec.set_xticks(bands[::3])
ax_spec.set_xticklabels([str(b) for b in bands[::3]], rotation=45, fontsize=7)

# ── 中：z-score 熱力圖 ────────────────────────────────────────────────────────
ax_heat = fig.add_subplot(gs[1])
order   = np.argsort(mahal)[::-1]   # 從最異常到最正常排列
Z_sorted = Z[order]
labels_sorted = [f"B{i+1}" for i in order]
levels_sorted = [levels[i] for i in order]

im = ax_heat.imshow(Z_sorted, aspect='auto', cmap='RdBu_r',
                    vmin=-3, vmax=3, interpolation='nearest')
plt.colorbar(im, ax=ax_heat, label='z-score', fraction=0.046)
ax_heat.set_xticks(range(len(bands)))
ax_heat.set_xticklabels([str(b) for b in bands], rotation=90, fontsize=6)
ax_heat.set_yticks(range(20))
ax_heat.set_yticklabels([
    f"{'⚠' if lv!='OK' else ' '} {lbl}" for lbl,lv in zip(labels_sorted,levels_sorted)
], fontsize=8)
ax_heat.set_title("Z-score Heatmap\n(red=low, blue=high vs normal mean)", fontsize=10, fontweight='bold')
ax_heat.set_xlabel("Wavelength (nm)")
# 標注 UV 區
uv_start = np.searchsorted(bands, 350)
uv_end   = np.searchsorted(bands, 450)
ax_heat.axvline(uv_start-0.5, color='purple', lw=1.5, alpha=0.6)
ax_heat.axvline(uv_end-0.5,   color='purple', lw=1.5, alpha=0.6, label='UV zone')
ax_heat.text((uv_start+uv_end)//2 - 1, -0.8, '365nm\nzone',
             fontsize=6, color='purple', ha='center')
# 高亮可疑豆
for rank, i in enumerate(order):
    if levels[i] == "HIGH":
        ax_heat.axhline(rank, color='#e74c3c', lw=2, alpha=0.4, xmin=0, xmax=1)
    elif levels[i] == "MED":
        ax_heat.axhline(rank, color='#f39c12', lw=1.5, alpha=0.35, xmin=0, xmax=1)

# ── 右：Mahalanobis 橫條圖 ───────────────────────────────────────────────────
ax_bar = fig.add_subplot(gs[2])
colors_bar = ['#e74c3c' if l=="HIGH" else '#f39c12' if l=="MED" else '#2ecc71'
              for l in levels_sorted]
bars = ax_bar.barh(range(20), mahal[order], color=colors_bar, alpha=0.85, height=0.7)
ax_bar.axvline(mahal_mean + 1.5*mahal_std, color='red',    ls='--', lw=1.2, label='HIGH threshold')
ax_bar.axvline(mahal_mean + 0.8*mahal_std, color='orange', ls='--', lw=1.0, label='MED threshold')
ax_bar.set_yticks(range(20))
ax_bar.set_yticklabels(labels_sorted, fontsize=8)
ax_bar.invert_yaxis()
ax_bar.set_title("Mahalanobis\nDistance", fontsize=10, fontweight='bold')
ax_bar.set_xlabel("Distance")
ax_bar.legend(fontsize=6, loc='lower right')
ax_bar.grid(True, alpha=0.25, axis='x')
# 數值標注
for rank, i in enumerate(order):
    ax_bar.text(mahal[order[rank]]+0.02, rank, f"{mahal[order[rank]]:.2f}",
                va='center', fontsize=7,
                color='#c0392b' if levels_sorted[rank]=="HIGH" else
                      '#d68910' if levels_sorted[rank]=="MED" else '#1e8449')

plt.suptitle("Coffee Bean Mold Risk Assessment — In-situ Flat-Field Corrected",
             fontsize=13, fontweight='bold', y=1.01)
plt.tight_layout()
out = f"{OUT_DIR}/mold_final_report.png"
plt.savefig(out, dpi=150, bbox_inches='tight')
plt.close()
print(f"\n[OK] {out}")

# ── 6. 標示圖 ─────────────────────────────────────────────────────────────────
orig = cv2.cvtColor(cv2.imread(f"{BEAN_DIR}/capture_001_5000us.png"), cv2.COLOR_BGR2RGB)
vis  = Image.fromarray(orig).convert("RGBA")
draw = ImageDraw.Draw(vis)

for i, b in enumerate(final_beans[:20]):
    cx, cy = int(b["cx"]), int(b["cy"])
    r  = max(b["x1"]-b["x0"], b["y1"]-b["y0"])//2 + 5
    lv = levels[i]
    bc = {"HIGH":(255,60,60),"MED":(255,165,0),"OK":(80,200,80)}[lv]
    lw = 3 if lv=="HIGH" else 2
    for d in range(lw):
        draw.ellipse([cx-r-d,cy-r-d,cx+r+d,cy+r+d], outline=bc+(220,))
    draw.rectangle([cx-16,cy-r-22,cx+46,cy-r-4], fill=(0,0,0,170))
    draw.text((cx-12,cy-r-20), f"B{i+1}", fill=bc+(255,))
    if lv != "OK":
        draw.text((cx+6, cy-r-20), f"z={uv_z[i]:+.1f}", fill=bc+(255,))

draw.rectangle([8,8,230,110], fill=(0,0,0,185))
draw.text((14,12),  "Mahalanobis + UV z-score",    fill=(255,255,255,255))
draw.ellipse([14,32,26,44], outline=(255,60,60,255))
draw.text((32,32), "HIGH  Mahal outlier",          fill=(255,160,160,255))
draw.ellipse([14,52,26,64], outline=(255,165,0,255))
draw.text((32,52), "MED   moderate outlier",       fill=(255,220,160,255))
draw.ellipse([14,72,26,84], outline=(80,200,80,255))
draw.text((32,72), "OK    normal",                 fill=(160,255,160,255))
draw.text((14,90), "z=UV zone z-score (365nm ref)",fill=(200,200,255,255))

out2 = f"{OUT_DIR}/mold_final_labeled.png"
vis.convert("RGB").save(out2)
print(f"[OK] {out2}")
