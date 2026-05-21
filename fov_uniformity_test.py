#!/usr/bin/env python3
"""
fov_uniformity_test.py <white_paper.qs>

針對有圓形套筒遮光的多光譜相機，分析 FOV 內的照明均勻性。

自動偵測圓形照明區域，在圓內放置 1 中心 + 4 方向 + 4 對角 = 9 個取樣點，
比較各位置的光譜是否一致。CV% < 5% = 均勻，< 10% = 可接受。

用法：
  python3 fov_uniformity_test.py /path/to/white_paper.qs
  python3 fov_uniformity_test.py /path/to/session_dir   # 自動找 .qs
"""

import json, os, csv, subprocess, sys
import numpy as np
from PIL import Image, ImageDraw
import matplotlib
matplotlib.rcParams['font.family'] = 'DejaVu Sans'
import matplotlib.pyplot as plt

BUILD_DIR = "/home/kyle/KyleClaude/multispectral_demo/build"
QSBS      = "/home/kyle/KyleClaude/camera_new.qsbs"
QSDB      = "/home/kyle/KyleClaude/db_std.qsdb"
SDK       = "/home/kyle/KyleClaude/sdk_extract/linux-sdk-arm64/qssdk-20250817"
OUT_DIR   = "/home/kyle/Desktop/fov_uniformity_test"
W, H      = 1600, 1200
PATCH_R   = 60    # 每個取樣點的正方形半寬（px）

os.makedirs(OUT_DIR, exist_ok=True)
env = os.environ.copy()
env["LD_LIBRARY_PATH"] = f"{SDK}:{SDK}/libarm64/spinvcore:{SDK}/libarm64/opencv/lib"


# ── 解析輸入路徑 ──────────────────────────────────────────────────────────────
arg = sys.argv[1] if len(sys.argv) > 1 else "."
if arg.endswith(".qs") and os.path.isfile(arg):
    QS_FILE = arg
else:
    candidates = sorted([f for f in os.listdir(arg) if f.endswith(".qs")])
    if not candidates:
        print(f"[ERROR] 找不到 .qs 檔：{arg}")
        sys.exit(1)
    QS_FILE = os.path.join(arg, candidates[0])
    print(f"自動選用：{os.path.basename(QS_FILE)}")

print(f"輸入：{QS_FILE}")


# ── Step1：qs_to_png 轉成預覽圖，用來偵測圓形區域 ────────────────────────────
preview_png = os.path.join(OUT_DIR, "white_preview.png")
cmd = [f"{BUILD_DIR}/qs_to_png", QS_FILE, preview_png, QSBS]
ret = subprocess.run(cmd, env=env, capture_output=True, text=True)
if ret.returncode != 0 or not os.path.exists(preview_png):
    print(f"[WARN] qs_to_png 失敗，嘗試用已有的 PNG...")
    session_dir = os.path.dirname(QS_FILE)
    pngs = [f for f in os.listdir(session_dir) if f.endswith(".png")]
    if pngs:
        from shutil import copyfile
        copyfile(os.path.join(session_dir, sorted(pngs)[0]), preview_png)
    else:
        print("[ERROR] 無法取得預覽圖")
        sys.exit(1)


# ── Step2：自動偵測圓形照明區域 ──────────────────────────────────────────────
img = np.array(Image.open(preview_png).convert("L"))  # 灰階

# 找亮區（套筒外為黑，白紙區為亮）
threshold = img.max() * 0.3
bright_mask = img > threshold

# 計算圓心（亮區重心）
ys, xs = np.where(bright_mask)
if len(xs) == 0:
    print("[WARN] 無法偵測亮區，使用畫面中心")
    cx, cy = W // 2, H // 2
    radius = min(W, H) // 2 - 50
else:
    cx = int(xs.mean())
    cy = int(ys.mean())
    # 估計半徑：亮區最遠點的 90%（保守估計，排除套筒邊緣）
    dists = np.sqrt((xs - cx)**2 + (ys - cy)**2)
    radius = int(np.percentile(dists, 85))

print(f"偵測到圓形照明區域：圓心=({cx},{cy}), 半徑={radius}px")
print(f"  實際使用半徑：{int(radius*0.75)}px（75%，避開套筒邊緣漸變區）")
safe_r = int(radius * 0.75)


# ── Step3：在圓內建立 9 個取樣點 ──────────────────────────────────────────────
# 1 中心 + 4 主軸（70% 半徑）+ 4 對角（70% 半徑 × √2/2）
r70 = int(safe_r * 0.70)
r70d = int(r70 * 0.707)   # 對角方向距離

sample_points = [
    ("中心",     cx,        cy       ),
    ("上方",     cx,        cy - r70 ),
    ("下方",     cx,        cy + r70 ),
    ("左方",     cx - r70,  cy       ),
    ("右方",     cx + r70,  cy       ),
    ("左上",     cx - r70d, cy - r70d),
    ("右上",     cx + r70d, cy - r70d),
    ("左下",     cx - r70d, cy + r70d),
    ("右下",     cx + r70d, cy + r70d),
]

# 夾緊到畫面邊界，避免 patch 超出
def clamp_patch(px, py, r, W, H):
    x0 = max(r, min(W - r, px)) - r
    y0 = max(r, min(H - r, py)) - r
    x1 = x0 + 2 * r
    y1 = y0 + 2 * r
    return x0, y0, x1, y1

rois = []
for i, (name, px, py) in enumerate(sample_points):
    x0, y0, x1, y1 = clamp_patch(px, py, PATCH_R, W, H)
    rois.append({"id": i + 1, "x0": x0, "y0": y0, "x1": x1, "y1": y1,
                 "name": name, "cx": px, "cy": py})
    print(f"  [{i+1}] {name:4s}: 中心=({px},{py})  ROI=({x0},{y0})~({x1},{y1})")


# ── Step4：建 label map + 跑 spec_fingerprint ─────────────────────────────────
lmap = np.zeros((H, W), dtype=np.uint8)
for r in rois:
    lmap[r["y0"]:r["y1"], r["x0"]:r["x1"]] = r["id"]
lmap_path = os.path.join(OUT_DIR, "circle_lmap.png")
Image.fromarray(lmap).save(lmap_path)

rois_clean = [{k: v for k, v in r.items() if k not in ("name","cx","cy")} for r in rois]
rois_path  = os.path.join(OUT_DIR, "circle_rois.json")
with open(rois_path, "w") as f:
    json.dump(rois_clean, f)

csv_out = os.path.join(OUT_DIR, "circle_spec.csv")
cmd = [f"{BUILD_DIR}/spec_fingerprint", QSBS, QSDB, QS_FILE,
       rois_path, csv_out, lmap_path]
print(f"\n執行 spec_fingerprint ({len(rois)} 個取樣點)...")
ret = subprocess.run(cmd, env=env, capture_output=True, text=True)
if ret.returncode != 0:
    print(f"[ERROR] spec_fingerprint failed:\n{ret.stderr[-500:]}")
    sys.exit(1)
print(ret.stdout.strip()[:200])


# ── Step5：讀結果 ──────────────────────────────────────────────────────────────
bands, spectra = [], {}
with open(csv_out) as f:
    reader = csv.DictReader(f)
    bkeys = [k for k in reader.fieldnames if k.startswith("bean_")]
    for row in reader:
        bands.append(float(row["wavelength_nm"]))
        for bk in bkeys:
            bid = int(bk.split("_")[1])
            spectra.setdefault(bid, []).append(float(row[bk]))
bands = np.array(bands)
arr   = np.array([spectra[i+1] for i in range(len(rois))])   # (9, n_bands)
names = [r["name"] for r in rois]


# ── Step6：統計分析 ───────────────────────────────────────────────────────────
mean_per_band = arr.mean(axis=0)
std_per_band  = arr.std(axis=0)
cv_per_band   = std_per_band / (mean_per_band + 1e-9) * 100

# 各取樣點相對中心的偏差
center_vals = arr[0]   # 中心點
rel_dev = (arr - center_vals) / (center_vals + 1e-9) * 100   # (9, n_bands)
mean_rel_dev = rel_dev.mean(axis=1)   # 每個位置對中心的平均偏差


# ── Step7：視覺化 ──────────────────────────────────────────────────────────────
colors = plt.cm.tab10(np.linspace(0, 1, len(names)))

fig, axes = plt.subplots(3, 1, figsize=(13, 12))

# 圖1：原始光譜疊加
ax1 = axes[0]
for i, (name, c) in enumerate(zip(names, colors)):
    ax1.plot(bands, arr[i], marker='o', ms=3, lw=1.5, color=c, label=name,
             alpha=0.9, zorder=3 if i==0 else 2)
ax1.set_title("各位置原始光譜（若重疊 = 均勻）", fontsize=12, fontweight='bold')
ax1.set_ylabel("反射值 (a.u.)")
ax1.legend(fontsize=9, ncol=3); ax1.grid(True, alpha=0.3)

# 圖2：歸一化（各條曲線除以各自均值，看形狀）
ax2 = axes[1]
for i, (name, c) in enumerate(zip(names, colors)):
    m = arr[i].mean()
    ax2.plot(bands, arr[i] / m, marker='o', ms=3, lw=1.5, color=c, label=name, alpha=0.9)
ax2.axhline(1.0, color='gray', ls='--', lw=1)
ax2.fill_between(bands, [0.95]*len(bands), [1.05]*len(bands),
                 alpha=0.1, color='green', label='±5%')
ax2.set_title("歸一化光譜（消除亮度差異，看光譜形狀一致性）", fontsize=12, fontweight='bold')
ax2.set_ylabel("歸一化反射率")
ax2.legend(fontsize=9, ncol=3); ax2.grid(True, alpha=0.3)

# 圖3：各波段 CV%
ax3 = axes[2]
bar_c = ['green' if v < 3 else 'orange' if v < 7 else 'red' for v in cv_per_band]
ax3.bar(bands, cv_per_band, width=12, color=bar_c, alpha=0.8)
ax3.axhline(3,  color='green',  ls='--', lw=1, label='3% (優秀)')
ax3.axhline(7,  color='orange', ls='--', lw=1, label='7% (可接受)')
ax3.axhline(15, color='red',    ls='--', lw=1, label='15% (需校正)')
ax3.set_title(f"各波段位置間 CV%    全波段均值={cv_per_band.mean():.1f}%",
              fontsize=12, fontweight='bold')
ax3.set_xlabel("波長 (nm)"); ax3.set_ylabel("CV%")
ax3.legend(fontsize=9); ax3.grid(True, alpha=0.3)

plt.tight_layout()
spec_path = os.path.join(OUT_DIR, "circle_uniformity.png")
plt.savefig(spec_path, dpi=150)
plt.close()
print(f"\n[OK] 光譜圖 -> {spec_path}")


# ── Step8：空間熱力圖 ──────────────────────────────────────────────────────────
# 把 9 個點的平均反射率畫成 3×3 網格（順序：上左~下右）
grid_vals = np.array([arr[i].mean() for i in range(9)]).reshape(3, 3)
# 相對中心的偏差%
center_mean = arr[0].mean()
grid_dev = (grid_vals - center_mean) / center_mean * 100

pos_grid = [["左上","上方","右上"],
            ["左方","中心","右方"],
            ["左下","下方","右下"]]
grid_order_idx = [5, 1, 6, 3, 0, 4, 7, 2, 8]  # 重新排列到 3×3
grid_vals_2d = np.array([arr[i].mean() for i in grid_order_idx]).reshape(3, 3)
grid_dev_2d  = (grid_vals_2d - center_mean) / center_mean * 100

fig2, ax = plt.subplots(figsize=(6, 5))
vrange = max(abs(grid_dev_2d.min()), abs(grid_dev_2d.max()), 5)
im = ax.imshow(grid_dev_2d, cmap='RdYlGn_r', vmin=-vrange, vmax=vrange)
plt.colorbar(im, ax=ax, label='相對中心偏差 (%)')
for r in range(3):
    for c in range(3):
        v = grid_dev_2d[r, c]
        ax.text(c, r, f"{pos_grid[r][c]}\n{v:+.1f}%",
                ha='center', va='center', fontsize=10, fontweight='bold',
                color='black')
ax.set_xticks([]); ax.set_yticks([])
ax.set_title(f"空間均勻性熱力圖（相對中心偏差%）\n全波段平均 CV={cv_per_band.mean():.1f}%",
             fontsize=11, fontweight='bold')
plt.tight_layout()
hm_path = os.path.join(OUT_DIR, "circle_heatmap.png")
plt.savefig(hm_path, dpi=150)
plt.close()
print(f"[OK] 熱力圖 -> {hm_path}")


# ── Step9：在預覽圖上標示取樣點 ───────────────────────────────────────────────
vis = Image.open(preview_png).convert("RGB").resize((800, 600))
scale_x, scale_y = 800 / W, 600 / H
draw = ImageDraw.Draw(vis)

# 畫圓形邊界
draw.ellipse([
    (cx - radius) * scale_x, (cy - radius) * scale_y,
    (cx + radius) * scale_x, (cy + radius) * scale_y
], outline=(255, 200, 0), width=2)
draw.ellipse([
    (cx - safe_r) * scale_x, (cy - safe_r) * scale_y,
    (cx + safe_r) * scale_x, (cy + safe_r) * scale_y
], outline=(0, 200, 255), width=1)

pt_colors = [(255,100,100),(100,200,100),(100,100,255),
             (255,200,0),(200,100,255),(255,150,50),
             (50,220,220),(180,255,100),(255,80,200)]
for i, r in enumerate(rois):
    sx0 = int(r["x0"] * scale_x)
    sy0 = int(r["y0"] * scale_y)
    sx1 = int(r["x1"] * scale_x)
    sy1 = int(r["y1"] * scale_y)
    c   = pt_colors[i % len(pt_colors)]
    dev = mean_rel_dev[i]
    draw.rectangle([sx0, sy0, sx1, sy1], outline=c, width=2)
    draw.text((sx0+2, sy0+2), f"{r['name']}\n{dev:+.1f}%", fill=c)

vis.save(os.path.join(OUT_DIR, "circle_sample_points.png"))
print(f"[OK] 取樣點標示圖 -> {os.path.join(OUT_DIR, 'circle_sample_points.png')}")


# ── Step10：文字報告 ───────────────────────────────────────────────────────────
print("\n========== FOV 圓形均勻性報告 ==========")
print(f"圓心 ({cx},{cy}), 半徑 {radius}px, 使用安全半徑 {safe_r}px")
print(f"\n各取樣點相對中心的平均偏差：")
for i, r in enumerate(rois):
    dev = mean_rel_dev[i]
    nir = arr[i][(bands >= 750) & (bands <= 930)].mean()
    flag = "✓" if abs(dev) < 5 else ("△" if abs(dev) < 10 else "✗")
    print(f"  {flag} {r['name']:4s}: 相對中心 {dev:+5.1f}%  NIR均值={nir:.1f}")

cv_mean = cv_per_band.mean()
cv_nir  = cv_per_band[(bands >= 750) & (bands <= 930)].mean()
print(f"\n全波段平均 CV = {cv_mean:.1f}%")
print(f"NIR波段 CV    = {cv_nir:.1f}%  (Agtron 量測關鍵頻段)")

if cv_nir < 3:
    verdict = "✓ NIR 照明非常均勻，Agtron 結果不受位置影響"
elif cv_nir < 7:
    verdict = "△ NIR 照明尚可，建議豆子擺在畫面中央 70% 範圍內"
elif cv_nir < 15:
    verdict = "⚠ NIR 有明顯空間差異，需做 flat-field 校正再量 Agtron"
else:
    verdict = "✗ 照明嚴重不均，請檢查燈源位置或套筒設計"
print(f"\n結論：{verdict}")
print("=========================================")
