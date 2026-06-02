#!/usr/bin/env python3
"""
white_paper_viz.py
1. 繪製白紙 4 組光譜指紋圖（含 ±std 帶）
2. 在 capture_000.png 上標示計算區域
"""
import csv, os
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import matplotlib
matplotlib.rcParams['font.family'] = 'DejaVu Sans'
import matplotlib.pyplot as plt

OUT_DIR   = "/home/kyle/Desktop/white_paper_check"
WHITE_DIR = "/home/kyle/Desktop/GigaImage_20260413_165855"

# ── 1. 讀取所有 CSV ───────────────────────────────────────────────────────────
captures = {}
for name in ["capture_000", "capture_001", "capture_002", "capture_003"]:
    csv_path = os.path.join(OUT_DIR, f"{name}_spec.csv")
    if not os.path.exists(csv_path):
        continue
    bands, vals = [], []
    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            bands.append(int(float(row["wavelength_nm"])))
            val_key = [k for k in row.keys() if k.startswith("bean_")][0]
            vals.append(float(row[val_key]))
    captures[name] = (np.array(bands), np.array(vals))

bands_arr = captures["capture_000"][0]
all_vals  = np.stack([v for _, v in captures.values()])  # shape (4, 30)
mean_vals = all_vals.mean(axis=0)
std_vals  = all_vals.std(axis=0)

# ── 2. 光譜指紋圖 ─────────────────────────────────────────────────────────────
fig, axes = plt.subplots(2, 1, figsize=(13, 9))

# 上：原始值
ax1 = axes[0]
colors = ['#e6194b', '#3cb44b', '#4363d8', '#f58231']
for i, (name, (b, v)) in enumerate(captures.items()):
    ax1.plot(b, v, marker='o', markersize=3.5, linewidth=1.5,
             color=colors[i], label=name)
ax1.set_title("White Paper Spectral Fingerprint (Raw, no flat-field)", fontsize=12, fontweight='bold')
ax1.set_xlabel("Wavelength (nm)")
ax1.set_ylabel("Reflectance Value (a.u.)")
ax1.set_xticks(bands_arr)
ax1.set_xticklabels([str(b) for b in bands_arr], rotation=45, fontsize=7)
ax1.legend(fontsize=9)
ax1.grid(True, alpha=0.3)

# 在峰值和谷值標注
peak_idx = np.argmax(mean_vals)
val_idx  = np.argmin(mean_vals)
ax1.annotate(f"Peak\n{bands_arr[peak_idx]}nm\n{mean_vals[peak_idx]:.2f}",
             xy=(bands_arr[peak_idx], mean_vals[peak_idx]),
             xytext=(bands_arr[peak_idx]-40, mean_vals[peak_idx]-3),
             fontsize=8, color='red',
             arrowprops=dict(arrowstyle='->', color='red', lw=1.2))

# 下：歸一化 + 平均 ± std
ax2 = axes[1]
norm_all = all_vals / mean_vals.mean()
norm_mean = norm_all.mean(axis=0)
norm_std  = norm_all.std(axis=0)

ax2.fill_between(bands_arr, norm_mean - norm_std, norm_mean + norm_std,
                 alpha=0.25, color='steelblue', label='±1 std (4 captures)')
ax2.plot(bands_arr, norm_mean, color='steelblue', linewidth=2.0,
         marker='o', markersize=4, label='Mean (4 captures)')
for i, (name, (b, v)) in enumerate(captures.items()):
    ax2.plot(b, v / mean_vals.mean(), linewidth=0.8, alpha=0.5,
             color=colors[i], linestyle='--')
ax2.axhline(1.0, color='gray', linestyle='--', linewidth=1)
ax2.fill_between(bands_arr, [0.95]*len(bands_arr), [1.05]*len(bands_arr),
                 alpha=0.10, color='green', label='±5% ideal zone')
ax2.set_title("Normalized Spectral Response (ideal = flat at 1.0)", fontsize=12, fontweight='bold')
ax2.set_xlabel("Wavelength (nm)")
ax2.set_ylabel("Normalized Reflectance")
ax2.set_xticks(bands_arr)
ax2.set_xticklabels([str(b) for b in bands_arr], rotation=45, fontsize=7)
ax2.legend(fontsize=9)
ax2.grid(True, alpha=0.3)

plt.tight_layout()
spec_path = os.path.join(OUT_DIR, "white_paper_fingerprint.png")
plt.savefig(spec_path, dpi=150)
plt.close()
print(f"[OK] 光譜圖: {spec_path}")

# ── 3. 在 capture_000.png 標示 ROI ────────────────────────────────────────────
img_path = os.path.join(WHITE_DIR, "capture_000.png")
img = Image.open(img_path).convert("RGB")
draw = ImageDraw.Draw(img)

W, H = img.size   # 1600 x 1200
margin_x = int(W * 0.10)   # 160
margin_y = int(H * 0.10)   # 120
x0, y0, x1, y1 = margin_x, margin_y, W - margin_x, H - margin_y

# 紅色矩形邊框（線寬 5）
for lw in range(5):
    draw.rectangle([x0-lw, y0-lw, x1+lw, y1+lw], outline=(255, 50, 50))

# 半透明紅色填充（另外合成）
overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
ov_draw = ImageDraw.Draw(overlay)
ov_draw.rectangle([x0, y0, x1, y1], fill=(255, 50, 50, 40))
img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
draw = ImageDraw.Draw(img)

# 左上角標籤
label_x, label_y = x0 + 8, y0 + 8
box_pad = 6
label_text = f"ROI  {x1-x0} x {y1-y0} px  (10% margin)"
# 白底黑字
bbox = [label_x - box_pad, label_y - box_pad,
        label_x + len(label_text)*10 + box_pad, label_y + 26 + box_pad]
draw.rectangle(bbox, fill=(255, 255, 255, 220))
draw.text((label_x, label_y), label_text, fill=(200, 30, 30))

# 四個角的十字標記
def cross(d, cx, cy, size=18, color=(255, 50, 50), width=3):
    d.line([cx-size, cy, cx+size, cy], fill=color, width=width)
    d.line([cx, cy-size, cx, cy+size], fill=color, width=width)

cross(draw, x0, y0)
cross(draw, x1, y0)
cross(draw, x0, y1)
cross(draw, x1, y1)

roi_path = os.path.join(OUT_DIR, "capture_000_roi_labeled.png")
img.save(roi_path)
print(f"[OK] ROI 標示圖: {roi_path}")

print(f"\nROI 範圍: ({x0}, {y0}) → ({x1}, {y1})  共 {(x1-x0)*(y1-y0):,} 像素")
print(f"結果存放: {OUT_DIR}")
