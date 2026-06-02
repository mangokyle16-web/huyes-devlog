#!/usr/bin/env python3
"""
mold_analysis_51.py
針對新場次的 51 顆（實際 48 顆有效）咖啡豆進行黴菌異常偵測：
  - 主指標：Mahalanobis distance（PCA 前 6 主成分）
  - 輔助：UV z-score（350-450nm）
  - in-situ 局部背景校正（每顆豆用周圍的深色背景）
"""
import csv, os, json, sys
import numpy as np
import cv2
import matplotlib
matplotlib.rcParams['font.family'] = 'DejaVu Sans'
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec

SESSION_DIR = sys.argv[1] if len(sys.argv) > 1 else "/home/kyle/Desktop/GigaImage_20260503_011205"
OUT_DIR     = os.path.join(SESSION_DIR, "mold_result")
os.makedirs(OUT_DIR, exist_ok=True)

# 視覺化背景圖：優先 1250us，再 5000us，再 2500us
for _gn in ["capture_1250us_gray.png", "capture_5000us_gray.png", "capture_2500us_gray.png"]:
    GRAY_PNG = os.path.join(SESSION_DIR, _gn)
    if os.path.exists(GRAY_PNG):
        break
SPEC_CSV    = os.path.join(SESSION_DIR, "spec_raw.csv")

# ── 1. 讀取光譜 CSV ───────────────────────────────────────────────────────────
bands_list, raw = [], {}
with open(SPEC_CSV) as f:
    reader = csv.DictReader(f)
    bkeys = [k for k in reader.fieldnames if k.startswith("bean_")]
    rows  = list(reader)

for bk in bkeys:
    bid = int(bk.split("_")[1])
    raw[bid] = np.array([float(row[bk]) for row in rows])
bands = np.array([int(float(row["wavelength_nm"])) for row in rows])
n_beans = len(raw)
bean_ids = sorted(raw.keys())
print(f"讀取 {n_beans} 顆豆子光譜（{bands[0]}–{bands[-1]} nm，{len(bands)} 波段）")

# ── 2. 讀取 ROI 位置 ──────────────────────────────────────────────────────────
with open(os.path.join(SESSION_DIR, "beans_rois.json")) as f:
    rois_list = json.load(f)
rois = {r["id"]: r for r in rois_list}

# ── 3. in-situ 背景校正 ───────────────────────────────────────────────────────
# 策略：每顆豆周圍取深色背景（黑盒底部），但黑底幾乎是 0
# 改用：不做背景校正，直接用原始光譜做相對比較
# （黑盒子沒有白紙參考，各豆子的絕對值相近，比相對差異更可靠）
print("使用原始光譜（黑底，無白紙參考）做相對異常偵測")
spectra = {bid: raw[bid] for bid in bean_ids}

# ── 4. 異常偵測 ───────────────────────────────────────────────────────────────
def band_idx(nm):
    return int(np.argmin(np.abs(bands - nm)))

X      = np.array([spectra[bid] for bid in bean_ids])
X_mean = X.mean(axis=0)

# PCA-based Mahalanobis distance
U, s, Vt = np.linalg.svd(X - X_mean, full_matrices=False)
n_pc = min(6, len(bean_ids) - 1)
pc_scores = U[:, :n_pc] * s[:n_pc]
pc_mean   = pc_scores.mean(0)
pc_std    = pc_scores.std(0) + 1e-9
mahal     = np.sqrt(((pc_scores - pc_mean) / pc_std) ** 2).mean(1)

# UV z-score（350–450nm 平均）
uv_bands = [band_idx(nm) for nm in range(350, 460, 20)]
uv_mean  = X[:, uv_bands].mean(axis=1)
uv_z     = (uv_mean - uv_mean.mean()) / (uv_mean.std() + 1e-9)

# 綜合異常分數
def norm(v):
    return (v - v.min()) / (v.max() - v.min() + 1e-9)

score = norm(mahal) * 0.7 + norm(-uv_z) * 0.3
mean_s, std_s = score.mean(), score.std()
levels = []
for s_ in score:
    if   s_ > mean_s + 1.5 * std_s: levels.append("HIGH")
    elif s_ > mean_s + 0.8 * std_s: levels.append("MED")
    else:                             levels.append("OK")

# ── 5. 列印結果 ───────────────────────────────────────────────────────────────
print("\n========== 黴菌異常偵測結果（48 顆）==========")
label_str = {"HIGH": "⚠⚠ 高度懷疑", "MED": "⚠  中度懷疑", "OK": "✓  正常"}
sorted_idx = np.argsort(score)[::-1]
for rank, i in enumerate(sorted_idx):
    bid   = bean_ids[i]
    flag  = label_str[levels[i]]
    print(f"  #{rank+1:2d}  Bean {bid:2d}  Mahal={mahal[i]:.3f}  UV_z={uv_z[i]:+.2f}  分數={score[i]:.3f}  {flag}")
print("=================================================")

# HIGH/MED 豆子摘要
high_med = [(bean_ids[i], levels[i], mahal[i], uv_z[i]) for i in sorted_idx if levels[i] != "OK"]
if high_med:
    print(f"\n⚠ 疑似黴菌豆子（共 {len(high_med)} 顆）:")
    for bid, lv, mh, uz in high_med:
        print(f"   Bean {bid:2d}  [{lv}]  Mahal={mh:.3f}  UV_z={uz:+.2f}")
else:
    print("\n✓ 所有豆子正常，無異常偵測")

# ── 6. 視覺化：用 labelmap 真實輪廓標示 ──────────────────────────────────────
img_gray  = cv2.imread(GRAY_PNG, cv2.IMREAD_GRAYSCALE)
labelmap  = cv2.imread(os.path.join(SESSION_DIR, "beans_labelmap.png"), cv2.IMREAD_GRAYSCALE)

# Resize labelmap if resolution mismatch
if labelmap.shape != img_gray.shape:
    labelmap = cv2.resize(labelmap, (img_gray.shape[1], img_gray.shape[0]),
                          interpolation=cv2.INTER_NEAREST)

vis = cv2.cvtColor(img_gray, cv2.COLOR_GRAY2BGR)

# BGR: OK=green, MED=orange, HIGH=red (Apple palette)
color_bgr  = {"OK": (89, 199, 52), "MED": (10, 149, 255), "HIGH": (56, 68, 255)}
thickness  = {"OK": 2,             "MED": 3,               "HIGH": 4}

for i, bid in enumerate(bean_ids):
    mask = (labelmap == bid).astype(np.uint8) * 255
    if mask.sum() == 0:
        continue
    lv    = levels[i]
    col   = color_bgr[lv]
    thick = thickness[lv]

    # Draw actual contour (not rectangle)
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(vis, cnts, -1, col, thick, cv2.LINE_AA)

    # Label at centroid
    M = cv2.moments(mask)
    if M["m00"] > 0:
        cx = int(M["m10"] / M["m00"])
        cy = int(M["m01"] / M["m00"])
        txt = str(bid) if lv == "OK" else f"{bid}!{lv[:1]}"  # e.g. "7!H"
        # Small background rect for readability
        (tw, th), _ = cv2.getTextSize(txt, cv2.FONT_HERSHEY_SIMPLEX, 0.40, 1)
        cv2.rectangle(vis, (cx - 2, cy - th - 2), (cx + tw + 2, cy + 2),
                      (0, 0, 0), -1)
        cv2.putText(vis, txt, (cx, cy),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.40, col, 1, cv2.LINE_AA)

out_labeled = os.path.join(OUT_DIR, "mold_labeled.png")
cv2.imwrite(out_labeled, vis)
print(f"\n標示圖 → {out_labeled}")

# ── 7. 報告圖 ─────────────────────────────────────────────────────────────────
fig = plt.figure(figsize=(16, 10))
gs  = gridspec.GridSpec(2, 3, figure=fig)

# (a) 光譜曲線
ax1 = fig.add_subplot(gs[0, :2])
cmap_lines = plt.cm.RdYlGn_r
for i, bid in enumerate(bean_ids):
    col = cmap_lines(score[i])
    ax1.plot(bands, spectra[bid], color=col, alpha=0.6, linewidth=1.2)
ax1.set_xlabel("Wavelength (nm)")
ax1.set_ylabel("Radiance (raw)")
ax1.set_title(f"Spectral Curves - {n_beans} Beans (red=anomalous)")
ax1.grid(True, alpha=0.3)

# (b) Mahalanobis 排名
ax2 = fig.add_subplot(gs[0, 2])
sorted_mahal = [(bean_ids[i], mahal[i], levels[i]) for i in np.argsort(mahal)[::-1]]
colors_bar = [{"HIGH":"#e74c3c","MED":"#e67e22","OK":"#2ecc71"}[lv] for _, _, lv in sorted_mahal]
ax2.barh([f"Bean {bid}" for bid,_,_ in sorted_mahal], [m for _,m,_ in sorted_mahal], color=colors_bar)
ax2.axvline(x=mahal.mean() + 1.5*mahal.std(), color='red', linestyle='--', label='HIGH thresh')
ax2.axvline(x=mahal.mean() + 0.8*mahal.std(), color='orange', linestyle='--', label='MED thresh')
ax2.set_xlabel("Mahalanobis Distance")
ax2.set_title("Anomaly Ranking")
ax2.legend(fontsize=7)
plt.setp(ax2.get_yticklabels(), fontsize=6)

# (c) UV z-score
ax3 = fig.add_subplot(gs[1, 0])
uv_sorted = np.argsort(uv_z)[::-1]
ax3.barh([f"Bean {bean_ids[i]}" for i in uv_sorted], [uv_z[i] for i in uv_sorted],
         color=["#e74c3c" if uv_z[i] < -1 else "#2ecc71" for i in uv_sorted])
ax3.axvline(x=-1, color='red', linestyle='--', label='UV absorb')
ax3.set_xlabel("UV z-score")
ax3.set_title("UV Absorption (low=suspicious)")
ax3.legend(fontsize=7)
plt.setp(ax3.get_yticklabels(), fontsize=6)

# (d) 綜合分數散點
ax4 = fig.add_subplot(gs[1, 1:])
ax4.scatter(mahal, uv_z,
            c=score, cmap='RdYlGn_r', s=80, alpha=0.8, edgecolors='gray', linewidths=0.5)
for i, bid in enumerate(bean_ids):
    if levels[i] != "OK":
        ax4.annotate(f"Bean {bid}", (mahal[i], uv_z[i]),
                     fontsize=8, ha='left', va='bottom',
                     color={"HIGH":"red","MED":"orange"}[levels[i]])
ax4.axvline(x=mahal.mean() + 1.5*mahal.std(), color='red', linestyle='--', alpha=0.5)
ax4.axhline(y=-1, color='red', linestyle=':', alpha=0.5)
ax4.set_xlabel("Mahalanobis Distance")
ax4.set_ylabel("UV z-score")
ax4.set_title("Mahal vs UV (anomalies marked)")
ax4.grid(True, alpha=0.3)

plt.suptitle(f"Mold Detection Report — {n_beans} Beans\n{SESSION_DIR.split('/')[-1]}",
             fontsize=12, fontweight='bold')
plt.tight_layout()

out_report = os.path.join(OUT_DIR, "mold_report.png")
plt.savefig(out_report, dpi=120, bbox_inches='tight')
plt.close()
print(f"分析報告 → {out_report}")
print("\n完成！")
