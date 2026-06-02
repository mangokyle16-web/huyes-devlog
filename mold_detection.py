#!/usr/bin/env python3
"""
mold_detection.py
針對 20 顆咖啡生豆的多光譜數據做黴菌早期感染偵測
方法：高光譜反射率異常分析（白光 LED 條件下）
  - 指標1：UV-Vis 比 (350nm/490nm) — 黃麴毒素吸收 UV，此比值偏低
  - 指標2：藍光凹谷深度 (450nm vs 410+490nm 插值)
  - 指標3：全波段 Mahalanobis 距離（PCA 空間異常分數）
  - 指標4：NIR 斜率 850-930nm（結構損傷）
"""
import csv, os, json
import numpy as np
from PIL import Image, ImageDraw
import matplotlib
matplotlib.rcParams['font.family'] = 'DejaVu Sans'
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

BEAN_DIR  = "/home/kyle/Desktop/GigaImage_20260413_174159"
OUT_DIR   = "/home/kyle/Desktop/mold_detection"
os.makedirs(OUT_DIR, exist_ok=True)

# ── 1. 讀取 20 顆光譜 CSV ─────────────────────────────────────────────────────
csv_path = os.path.join(BEAN_DIR, "spec_fingerprint_20beans.csv")
bands, specs = [], {}
with open(csv_path) as f:
    reader = csv.DictReader(f)
    bean_keys = [k for k in reader.fieldnames if k.startswith("bean_")]
    for row in reader:
        nm = int(float(row["wavelength_nm"]))
        bands.append(nm)
        for k in bean_keys:
            specs.setdefault(k, []).append(float(row[k]))

bands = np.array(bands)
n_beans = len(bean_keys)
# shape: (20, 30)
X = np.array([specs[k] for k in bean_keys])

def band_idx(nm):
    return np.argmin(np.abs(bands - nm))

# ── 2. 黴菌光譜指標 ───────────────────────────────────────────────────────────
# 指標1：UV相對吸收比 = 350nm / 490nm（黃麴毒素→UV吸收增強→比值↓）
idx_uv  = X[:, band_idx(350)] / (X[:, band_idx(490)] + 1e-9)

# 指標2：藍光凹谷深度（450nm vs 線性插值(410,490)）
b410 = X[:, band_idx(410)]
b450 = X[:, band_idx(450)]
b490 = X[:, band_idx(490)]
interp_450 = b410 + (b490 - b410) * (450 - 410) / (490 - 410)
idx_blue_dip = (interp_450 - b450) / (interp_450 + 1e-9)   # 正值=凹谷存在

# 指標3：全波段 PCA Mahalanobis 距離
from numpy.linalg import eig, inv
X_mean = X.mean(axis=0)
X_c = X - X_mean
cov = np.cov(X_c.T)
# 用前 5 個主成分避免奇異矩陣
U, s, Vt = np.linalg.svd(X_c, full_matrices=False)
pc_scores = U[:, :5] * s[:5]   # (20, 5)
pc_mean = pc_scores.mean(axis=0)
pc_std  = pc_scores.std(axis=0) + 1e-9
idx_pca = np.sqrt(((pc_scores - pc_mean) / pc_std) ** 2).mean(axis=1)

# 指標4：NIR 末端斜率（850→930nm，受損豆結構不同→斜率異常）
b850 = X[:, band_idx(850)]
b930 = X[:, band_idx(930)]
idx_nir_slope = (b930 - b850) / (b850 + 1e-9)   # 通常為負，偏正=異常

# 合成異常分數（各指標歸一化後加總）
def normalize(v):
    mn, mx = v.min(), v.max()
    return (v - mn) / (mx - mn + 1e-9)

# UV比低 = 可疑 → 取反
score = (
    normalize(1 - idx_uv) * 0.35 +    # UV吸收異常（權重最高）
    normalize(idx_blue_dip) * 0.25 +  # 藍光凹谷
    normalize(idx_pca) * 0.25 +       # PCA異常
    normalize(-idx_nir_slope) * 0.15  # NIR斜率異常
)

# ── 3. 判定等級 ───────────────────────────────────────────────────────────────
mean_s, std_s = score.mean(), score.std()
levels = []
for s in score:
    if s > mean_s + 1.5 * std_s:
        levels.append("HIGH")
    elif s > mean_s + 0.8 * std_s:
        levels.append("MED")
    else:
        levels.append("OK")

print("========== 黴菌異常分數排名 ==========")
order = np.argsort(score)[::-1]
for rank, i in enumerate(order):
    bean_num = i + 1
    flag = {"HIGH": "⚠⚠ 高度懷疑", "MED": "⚠  中度懷疑", "OK": "✓  正常"}[levels[i]]
    print(f"  #{rank+1:2d}  Bean {bean_num:2d}  分數={score[i]:.3f}  {flag}")
print("======================================")

# ── 4. 重建豆子輪廓位置（two-stage 分割）─────────────────────────────────────
import cv2

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
            cx, cy = centroids[j]
            x0 = stats[j, cv2.CC_STAT_LEFT]
            y0 = stats[j, cv2.CC_STAT_TOP]
            w  = stats[j, cv2.CC_STAT_WIDTH]
            h  = stats[j, cv2.CC_STAT_HEIGHT]
            beans.append({"cx": cx, "cy": cy,
                          "x0": x0, "y0": y0, "x1": x0+w, "y1": y0+h,
                          "area": area, "label": j})
    return beans

beans_t65 = find_beans(img_seg, 65)
beans_t80 = find_beans(img_seg, 80)
print(f"\n分割結果：t65={len(beans_t65)} 顆，t80={len(beans_t80)} 顆")

# 用 t80 為主，t65 補回不足的
def center_dist(a, b):
    return np.sqrt((a["cx"]-b["cx"])**2 + (a["cy"]-b["cy"])**2)

final_beans = list(beans_t80)
for b65 in beans_t65:
    matched = any(center_dist(b65, b80) < 30 for b80 in final_beans)
    if not matched:
        final_beans.append(b65)

# 按位置排序（左上到右下）
final_beans.sort(key=lambda b: (round(b["cy"]/120)*120 + b["cx"]/10000))
print(f"最終豆子數：{len(final_beans)}")

if len(final_beans) != 20:
    print(f"[WARN] 分割到 {len(final_beans)} 顆，非 20 顆，仍繼續分析")
    n_match = min(len(final_beans), 20)
else:
    n_match = 20

# ── 5. 在原圖標示可疑豆子 ─────────────────────────────────────────────────────
orig = cv2.imread(os.path.join(BEAN_DIR, "capture_001_5000us.png"))
orig_rgb = cv2.cvtColor(orig, cv2.COLOR_BGR2RGB)
vis = Image.fromarray(orig_rgb).convert("RGBA")
overlay = Image.new("RGBA", vis.size, (0,0,0,0))
draw_ov = ImageDraw.Draw(overlay)
draw    = ImageDraw.Draw(vis)

color_map = {
    "HIGH": (255,  50,  50, 180),
    "MED":  (255, 165,   0, 160),
    "OK":   ( 80, 200,  80, 100),
}
border_map = {
    "HIGH": (255,  50,  50),
    "MED":  (255, 165,   0),
    "OK":   ( 60, 180,  60),
}

for i in range(n_match):
    b   = final_beans[i]
    lv  = levels[i]
    sc  = score[i]
    cx, cy = int(b["cx"]), int(b["cy"])
    r = max(int((b["x1"]-b["x0"]) / 2), int((b["y1"]-b["y0"]) / 2)) + 4

    # 橢圓填色
    draw_ov.ellipse([cx-r, cy-r, cx+r, cy+r], fill=color_map[lv])
    vis = Image.alpha_composite(vis, overlay)
    overlay = Image.new("RGBA", vis.size, (0,0,0,0))
    draw_ov = ImageDraw.Draw(overlay)

    draw = ImageDraw.Draw(vis)
    # 邊框（可疑豆加粗）
    lw = 4 if lv == "HIGH" else 3 if lv == "MED" else 2
    for dw in range(lw):
        draw.ellipse([cx-r-dw, cy-r-dw, cx+r+dw, cy+r+dw],
                     outline=border_map[lv])

    # 標籤
    label_text = f"B{i+1}"
    if lv != "OK":
        label_text += f"\n{lv}"
    tx, ty = cx - 12, cy - r - 26 if lv != "OK" else cy - r - 18
    bg_color = (255, 255, 255, 200)
    draw.rectangle([tx-2, ty-2, tx+38, ty+30 if lv!="OK" else ty+16],
                   fill=bg_color)
    draw.text((tx, ty), f"B{i+1}", fill=border_map[lv])
    if lv != "OK":
        draw.text((tx, ty+14), lv, fill=border_map[lv])

# 圖例
legend_x, legend_y = 10, 10
draw.rectangle([legend_x, legend_y, legend_x+180, legend_y+80], fill=(0,0,0,180))
draw.text((legend_x+8, legend_y+6),  "Mold Risk Level", fill=(255,255,255))
draw.rectangle([legend_x+8, legend_y+24, legend_x+22, legend_y+36], fill=(255,50,50))
draw.text((legend_x+28, legend_y+24), "HIGH - Suspected", fill=(255,200,200))
draw.rectangle([legend_x+8, legend_y+42, legend_x+22, legend_y+54], fill=(255,165,0))
draw.text((legend_x+28, legend_y+42), "MED  - Monitor",   fill=(255,220,180))
draw.rectangle([legend_x+8, legend_y+60, legend_x+22, legend_y+72], fill=(80,200,80))
draw.text((legend_x+28, legend_y+60), "OK   - Normal",    fill=(180,255,180))

labeled_path = os.path.join(OUT_DIR, "mold_detection_labeled.png")
vis.convert("RGB").save(labeled_path)
print(f"\n[OK] 標示圖：{labeled_path}")

# ── 6. 光譜指紋比較圖（正常 vs 可疑）────────────────────────────────────────
high_idx = [i for i,l in enumerate(levels) if l=="HIGH"]
med_idx  = [i for i,l in enumerate(levels) if l=="MED"]
ok_idx   = [i for i,l in enumerate(levels) if l=="OK"]

fig, axes = plt.subplots(2, 1, figsize=(13, 9))

ax1 = axes[0]
for i in ok_idx:
    ax1.plot(bands, X[i], color='green', alpha=0.3, linewidth=1)
for i in med_idx:
    ax1.plot(bands, X[i], color='orange', alpha=0.7, linewidth=1.5,
             label=f"Bean {i+1} (MED)")
for i in high_idx:
    ax1.plot(bands, X[i], color='red', linewidth=2,
             label=f"Bean {i+1} (HIGH)")
if ok_idx:
    ok_mean = X[ok_idx].mean(axis=0)
    ax1.plot(bands, ok_mean, color='green', linewidth=2, linestyle='--',
             label="Normal mean")

ax1.axvspan(340, 420, alpha=0.08, color='purple', label='UV zone (mold indicator)')
ax1.axvspan(430, 470, alpha=0.08, color='blue',   label='Blue dip zone')
ax1.set_title("Spectral Fingerprint: Normal vs Suspected Mold", fontsize=12, fontweight='bold')
ax1.set_xlabel("Wavelength (nm)")
ax1.set_ylabel("Reflectance (flat-field corrected)")
ax1.legend(fontsize=8)
ax1.grid(True, alpha=0.3)
ax1.set_xticks(bands)
ax1.set_xticklabels([str(b) for b in bands], rotation=45, fontsize=7)

# 下圖：各豆差分（個豆 - 正常平均）
ax2 = axes[1]
if ok_idx:
    ok_mean = X[ok_idx].mean(axis=0)
    for i in ok_idx:
        ax2.plot(bands, X[i]-ok_mean, color='green', alpha=0.2, linewidth=1)
    for i in med_idx:
        ax2.plot(bands, X[i]-ok_mean, color='orange', alpha=0.8, linewidth=1.5,
                 label=f"Bean {i+1} (MED)")
    for i in high_idx:
        ax2.plot(bands, X[i]-ok_mean, color='red', linewidth=2,
                 label=f"Bean {i+1} (HIGH)")
    ax2.axhline(0, color='gray', linestyle='--', linewidth=1)
    ax2.axvspan(340, 420, alpha=0.08, color='purple')
    ax2.axvspan(430, 470, alpha=0.08, color='blue')
ax2.set_title("Differential Spectrum (each bean - normal mean)", fontsize=12, fontweight='bold')
ax2.set_xlabel("Wavelength (nm)")
ax2.set_ylabel("Delta Reflectance")
ax2.legend(fontsize=8)
ax2.grid(True, alpha=0.3)
ax2.set_xticks(bands)
ax2.set_xticklabels([str(b) for b in bands], rotation=45, fontsize=7)

plt.tight_layout()
spec_path = os.path.join(OUT_DIR, "mold_spectral_comparison.png")
plt.savefig(spec_path, dpi=150)
plt.close()
print(f"[OK] 光譜比較圖：{spec_path}")

# ── 7. 指標雷達圖 ─────────────────────────────────────────────────────────────
suspicious = high_idx + med_idx
if suspicious:
    n = len(suspicious)
    categories = ['UV Absorption\n(350/490)', 'Blue Dip\n(450nm)',
                  'PCA Anomaly', 'NIR Slope\n(850-930)']
    fig2, axes2 = plt.subplots(1, min(n, 4), figsize=(4*min(n,4), 4),
                               subplot_kw=dict(polar=True))
    if n == 1:
        axes2 = [axes2]
    angles = np.linspace(0, 2*np.pi, len(categories), endpoint=False).tolist()
    angles += angles[:1]

    ind_vals = np.column_stack([
        normalize(1 - idx_uv),
        normalize(idx_blue_dip),
        normalize(idx_pca),
        normalize(-idx_nir_slope)
    ])

    for pi, i in enumerate(suspicious[:4]):
        ax = axes2[pi]
        vals = ind_vals[i].tolist() + [ind_vals[i][0]]
        ax.plot(angles, vals, 'o-', linewidth=2,
                color='red' if levels[i]=="HIGH" else 'orange')
        ax.fill(angles, vals, alpha=0.25,
                color='red' if levels[i]=="HIGH" else 'orange')
        ax.set_xticks(angles[:-1])
        ax.set_xticklabels(categories, fontsize=7)
        ax.set_ylim(0, 1)
        ax.set_title(f"Bean {i+1}\n[{levels[i]}] score={score[i]:.2f}",
                     fontsize=9, fontweight='bold')
        ax.grid(True)

    plt.suptitle("Mold Indicator Radar Chart (Suspected Beans)", fontsize=11)
    plt.tight_layout()
    radar_path = os.path.join(OUT_DIR, "mold_radar.png")
    plt.savefig(radar_path, dpi=150)
    plt.close()
    print(f"[OK] 雷達圖：{radar_path}")

print(f"\n所有結果存於：{OUT_DIR}")
