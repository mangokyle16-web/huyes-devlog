#!/usr/bin/env python3
"""
white_paper_grid_check.py <session_dir_or_qs_file>

把白紙畫面拆成 3×3 網格（9 個子區域），各自量光譜，比較 FOV 均勻性。
若曲線高度重疊、CV% < 5% → 照明均勻，豆子位置不影響量測。

用法：
  python3 white_paper_grid_check.py /path/to/session_dir
  python3 white_paper_grid_check.py /path/to/file.qs
"""
import json, os, csv, subprocess, sys
import numpy as np
from PIL import Image, ImageDraw
import matplotlib
matplotlib.rcParams['font.family'] = 'DejaVu Sans'
import matplotlib.pyplot as plt

# ── 路徑設定 ──────────────────────────────────────────────────────────────────
BUILD_DIR = "/home/kyle/KyleClaude/multispectral_demo/build"
QSBS      = "/home/kyle/KyleClaude/camera_new.qsbs"
QSDB      = "/home/kyle/KyleClaude/db_std.qsdb"
SDK       = "/home/kyle/KyleClaude/sdk_extract/linux-sdk-arm64/qssdk-20250817"
OUT_DIR   = "/home/kyle/Desktop/white_paper_check"

# ── 解析輸入路徑 ──────────────────────────────────────────────────────────────
arg = sys.argv[1] if len(sys.argv) > 1 else "/home/kyle/Desktop/GigaImage_20260413_165855"
if arg.endswith(".qs") and os.path.isfile(arg):
    QS_FILE  = arg
    WHITE_DIR = os.path.dirname(arg)
else:
    WHITE_DIR = arg
    # 找第一個 .qs 檔
    qs_files = sorted([f for f in os.listdir(WHITE_DIR) if f.endswith(".qs")])
    if not qs_files:
        print(f"[ERROR] 找不到 .qs 檔：{WHITE_DIR}")
        sys.exit(1)
    QS_FILE = os.path.join(WHITE_DIR, qs_files[0])

print(f"分析檔案：{QS_FILE}")

env = os.environ.copy()
env["LD_LIBRARY_PATH"] = (
    f"{SDK}:{SDK}/libarm64/spinvcore:{SDK}/libarm64/opencv/lib"
)

W, H = 1600, 1200
MARGIN_X = int(W * 0.10)   # 160
MARGIN_Y = int(H * 0.10)   # 120
ROI_W = W - 2 * MARGIN_X   # 1280
ROI_H = H - 2 * MARGIN_Y   # 960

# ── 建立 3×3 網格 ROI ─────────────────────────────────────────────────────────
GRID_ROWS, GRID_COLS = 3, 3
rois = []
cell_w = ROI_W // GRID_COLS
cell_h = ROI_H // GRID_ROWS
inner_pad = 20   # 格子內縮，避免邊緣

cell_id = 1
for row in range(GRID_ROWS):
    for col in range(GRID_COLS):
        x0 = MARGIN_X + col * cell_w + inner_pad
        y0 = MARGIN_Y + row * cell_h + inner_pad
        x1 = MARGIN_X + (col + 1) * cell_w - inner_pad
        y1 = MARGIN_Y + (row + 1) * cell_h - inner_pad
        rois.append({"id": cell_id, "x0": x0, "y0": y0, "x1": x1, "y1": y1,
                     "row": row, "col": col})
        cell_id += 1

rois_path = os.path.join(OUT_DIR, "grid_rois.json")
with open(rois_path, "w") as f:
    json.dump([{k: v for k, v in r.items() if k not in ("row","col")}
               for r in rois], f, indent=2)
print(f"[OK] {len(rois)} 個網格 ROI 已建立")

# ── 建立 label map：各格填入對應 ID ──────────────────────────────────────────
label_map = np.zeros((H, W), dtype=np.uint8)
for r in rois:
    label_map[r["y0"]:r["y1"], r["x0"]:r["x1"]] = r["id"]

lmap_path = os.path.join(OUT_DIR, "grid_labelmap.png")
Image.fromarray(label_map).save(lmap_path)
print(f"[OK] Label map 已存：{lmap_path}")

# ── 執行 spec_fingerprint ─────────────────────────────────────────────────────
csv_out = os.path.join(OUT_DIR, "grid_spec.csv")
cmd = [
    f"{BUILD_DIR}/spec_fingerprint",
    QSBS, QSDB, QS_FILE,
    rois_path, csv_out, lmap_path
]
print(f"\n執行 spec_fingerprint（9 區域）...")
ret = subprocess.run(cmd, env=env, capture_output=True, text=True)
if ret.returncode != 0:
    print(f"[ERROR] {ret.stderr[-500:]}")
    exit(1)
print(ret.stdout.strip())

# ── 讀 CSV ────────────────────────────────────────────────────────────────────
# 格式：wavelength_nm, bean_1, bean_2, ..., bean_9
bands, grid_vals = [], {}
with open(csv_out) as f:
    reader = csv.DictReader(f)
    headers = reader.fieldnames
    bean_keys = [k for k in headers if k.startswith("bean_")]
    for row in reader:
        bands.append(int(float(row["wavelength_nm"])))
        for k in bean_keys:
            grid_vals.setdefault(k, []).append(float(row[k]))

bands = np.array(bands)
grid_arr = np.array([grid_vals[k] for k in bean_keys])   # (9, 30)
print(f"\n[OK] 讀取成功：{len(bean_keys)} 區域 × {len(bands)} 波段")

# ── 計算統計 ──────────────────────────────────────────────────────────────────
mean_all = grid_arr.mean(axis=0)
std_all  = grid_arr.std(axis=0)
cv_all   = std_all / mean_all * 100   # 各波段的變異係數 (CV%)

print("\n========== 網格一致性報告 ==========")
print(f"{'波長':>8} {'平均':>8} {'std':>8} {'CV%':>8}")
for i, nm in enumerate(bands):
    flag = "  <-- 高變異!" if cv_all[i] > 5 else ""
    print(f"{nm:>8}nm {mean_all[i]:>8.3f} {std_all[i]:>8.3f} {cv_all[i]:>7.1f}%{flag}")
print(f"\n全波段平均 CV = {cv_all.mean():.1f}%")
print("======================================")

# ── 圖1：各格光譜疊加圖 ──────────────────────────────────────────────────────
fig, axes = plt.subplots(2, 1, figsize=(13, 9))

colors = plt.cm.tab10(np.linspace(0, 1, len(bean_keys)))
labels = [f"Cell {r['row']+1}{r['col']+1}" for r in rois]   # C11, C12 ...

ax1 = axes[0]
for i, (key, lbl) in enumerate(zip(bean_keys, labels)):
    ax1.plot(bands, grid_vals[key], marker='o', markersize=3, linewidth=1.5,
             color=colors[i], label=lbl, alpha=0.85)
ax1.set_title("White Paper 3x3 Grid - Spectral Fingerprint Overlay (Raw)", fontsize=12, fontweight='bold')
ax1.set_xlabel("Wavelength (nm)")
ax1.set_ylabel("Reflectance Value (a.u.)")
ax1.set_xticks(bands)
ax1.set_xticklabels([str(b) for b in bands], rotation=45, fontsize=7)
ax1.legend(fontsize=8, ncol=3)
ax1.grid(True, alpha=0.3)

# 下圖：歸一化後疊加（消除絕對值差異，只看形狀）
ax2 = axes[1]
for i, (key, lbl) in enumerate(zip(bean_keys, labels)):
    v = np.array(grid_vals[key])
    v_norm = v / v.mean()
    ax2.plot(bands, v_norm, marker='o', markersize=3, linewidth=1.5,
             color=colors[i], label=lbl, alpha=0.85)
ax2.fill_between(bands, mean_all/mean_all.mean() - std_all/mean_all.mean(),
                         mean_all/mean_all.mean() + std_all/mean_all.mean(),
                 alpha=0.15, color='gray', label='±1 std band')
ax2.axhline(1.0, color='gray', linestyle='--', linewidth=1)
ax2.set_title("Normalized (shape comparison) - flat = uniform illumination", fontsize=12, fontweight='bold')
ax2.set_xlabel("Wavelength (nm)")
ax2.set_ylabel("Normalized Reflectance")
ax2.set_xticks(bands)
ax2.set_xticklabels([str(b) for b in bands], rotation=45, fontsize=7)
ax2.legend(fontsize=8, ncol=3)
ax2.grid(True, alpha=0.3)

plt.tight_layout()
spec_path = os.path.join(OUT_DIR, "white_paper_grid_spectrum.png")
plt.savefig(spec_path, dpi=150)
plt.close()
print(f"\n[OK] 光譜疊加圖：{spec_path}")

# ── 圖2：CV% 熱力圖（空間均勻性）────────────────────────────────────────────
# 計算每個格子的平均值（用於空間分布）
cell_means = grid_arr.mean(axis=1).reshape(GRID_ROWS, GRID_COLS)

fig2, ax = plt.subplots(figsize=(7, 5))
im = ax.imshow(cell_means, cmap='RdYlGn', aspect='auto')
plt.colorbar(im, ax=ax, label='Mean reflectance (all bands)')
for row in range(GRID_ROWS):
    for col in range(GRID_COLS):
        cell_idx = row * GRID_COLS + col
        ax.text(col, row, f"Cell {row+1}{col+1}\n{cell_means[row,col]:.2f}",
                ha='center', va='center', fontsize=10, fontweight='bold',
                color='black')
ax.set_xticks([0, 1, 2])
ax.set_xticklabels(['Left', 'Center', 'Right'])
ax.set_yticks([0, 1, 2])
ax.set_yticklabels(['Top', 'Mid', 'Bottom'])
ax.set_title("Spatial Uniformity (mean reflectance per grid cell)", fontsize=12, fontweight='bold')
plt.tight_layout()
heatmap_path = os.path.join(OUT_DIR, "white_paper_grid_heatmap.png")
plt.savefig(heatmap_path, dpi=150)
plt.close()
print(f"[OK] 空間均勻性熱力圖：{heatmap_path}")

# ── 圖3：在 capture_000.png 標示 9 格 ────────────────────────────────────────
img = Image.open(os.path.join(WHITE_DIR, "capture_000.png")).convert("RGB")
draw = ImageDraw.Draw(img)

grid_colors = [
    (220, 50, 50), (50, 150, 220), (50, 200, 80),
    (200, 150, 0), (160, 50, 200), (0, 180, 180),
    (220, 100, 30), (80, 80, 220), (180, 180, 50),
]
for r in rois:
    idx = r["id"] - 1
    c = grid_colors[idx]
    # 邊框
    for lw in range(3):
        draw.rectangle([r["x0"]-lw, r["y0"]-lw, r["x1"]+lw, r["y1"]+lw], outline=c)
    # 標籤
    lbl = f"C{r['row']+1}{r['col']+1}"
    tx, ty = r["x0"] + 8, r["y0"] + 6
    draw.rectangle([tx-3, ty-3, tx+35, ty+20], fill=(255,255,255))
    draw.text((tx, ty), lbl, fill=c)

labeled_path = os.path.join(OUT_DIR, "capture_000_grid_labeled.png")
img.save(labeled_path)
print(f"[OK] 網格標示圖：{labeled_path}")
