#!/usr/bin/env python3
"""
white_paper_check.py
對白紙拍攝的 .qs 檔跑光譜指紋分析（不做 flat-field 校正），
檢查各波段反射率是否水平，驗證標定檔案是否正常。
"""
import json, os, subprocess, sys
import numpy as np
from PIL import Image
import matplotlib.pyplot as plt
import csv

# ── 設定路徑 ─────────────────────────────────────────────────────────────────
WHITE_FOLDER = "/home/kyle/Desktop/GigaImage_20260413_165855"
BUILD_DIR    = "/home/kyle/KyleClaude/multispectral_demo/build"
QSBS         = "/home/kyle/KyleClaude/camera_new.qsbs"
QSDB         = "/home/kyle/KyleClaude/db_std.qsdb"
SDK          = "/home/kyle/KyleClaude/sdk_extract/linux-sdk-arm64/qssdk-20250817"
OUT_DIR      = "/home/kyle/Desktop/white_paper_check"

os.makedirs(OUT_DIR, exist_ok=True)

# ── 環境變數 ──────────────────────────────────────────────────────────────────
env = os.environ.copy()
env["LD_LIBRARY_PATH"] = (
    f"{SDK}:{SDK}/libarm64/spinvcore:{SDK}/libarm64/opencv/lib"
)

# ── 找出所有白紙 .qs 檔 ───────────────────────────────────────────────────────
qs_files = sorted([
    os.path.join(WHITE_FOLDER, f)
    for f in os.listdir(WHITE_FOLDER)
    if f.endswith(".qs")
])
print(f"找到 {len(qs_files)} 個 .qs 檔：")
for q in qs_files:
    print(f"  {os.path.basename(q)}")

# ── 建立全圖 ROI JSON（留 10% 邊界，避免邊緣雜訊）─────────────────────────────
W, H = 1600, 1200
margin_x = int(W * 0.10)
margin_y = int(H * 0.10)
roi = {"id": 1, "x0": margin_x, "y0": margin_y,
       "x1": W - margin_x, "y1": H - margin_y}
rois_path = os.path.join(OUT_DIR, "white_roi.json")
with open(rois_path, "w") as f:
    json.dump([roi], f, indent=2)
print(f"\nROI: x0={roi['x0']}, y0={roi['y0']}, x1={roi['x1']}, y1={roi['y1']}")

# ── 建立全圖 label map（ROI 內像素 = 1，其餘 = 0）─────────────────────────────
label_map = np.zeros((H, W), dtype=np.uint8)
label_map[roi["y0"]:roi["y1"], roi["x0"]:roi["x1"]] = 1
lmap_path = os.path.join(OUT_DIR, "white_labelmap.png")
Image.fromarray(label_map).save(lmap_path)
print(f"Label map 已存：{lmap_path}")

# ── 對每個 .qs 檔跑 spec_fingerprint ─────────────────────────────────────────
results = {}   # filename → {band_nm: mean_value}

for qs_path in qs_files:
    name = os.path.splitext(os.path.basename(qs_path))[0]
    csv_out = os.path.join(OUT_DIR, f"{name}_spec.csv")

    cmd = [
        f"{BUILD_DIR}/spec_fingerprint",
        QSBS, QSDB,
        qs_path,
        rois_path,
        csv_out,
        lmap_path,
        # 不帶 white_ref → 看原始反射值
    ]
    print(f"\n執行：{name} ...")
    ret = subprocess.run(cmd, env=env, capture_output=True, text=True)
    if ret.returncode != 0:
        print(f"  [ERROR] returncode={ret.returncode}")
        print(ret.stderr[-800:])
        continue
    if ret.stdout:
        print(ret.stdout.strip()[:200])

    # 讀 CSV：格式為 wavelength_nm, bean_1, bean_2, ...
    if not os.path.exists(csv_out):
        print(f"  [WARN] CSV 未產生：{csv_out}")
        continue

    band_data = {}
    with open(csv_out) as f:
        reader = csv.DictReader(f)
        for row in reader:
            nm = int(float(row["wavelength_nm"]))
            # 取第一個 bean 欄位（bean_1）
            val_key = [k for k in row.keys() if k.startswith("bean_")][0]
            band_data[f"{nm}nm"] = float(row[val_key])
    if band_data:
        results[name] = band_data
        print(f"  波段數：{len(band_data)}")

# ── 繪圖：各拍攝光譜疊加 ────────────────────────────────────────────────────
if not results:
    print("\n[ERROR] 沒有成功的結果，結束。")
    sys.exit(1)

fig, axes = plt.subplots(2, 1, figsize=(12, 9))

# 上圖：原始值
ax1 = axes[0]
colors = plt.cm.tab10(np.linspace(0, 1, len(results)))
all_bands = None
for i, (name, band_data) in enumerate(results.items()):
    bands = [int(k.replace("nm","")) for k in band_data.keys()]
    vals  = list(band_data.values())
    if all_bands is None:
        all_bands = bands
    ax1.plot(bands, vals, marker='o', markersize=4, label=name, color=colors[i])

ax1.set_title("白紙光譜（原始值，無 flat-field 校正）", fontsize=13)
ax1.set_xlabel("波長 (nm)")
ax1.set_ylabel("反射值（任意單位）")
ax1.legend(fontsize=8)
ax1.grid(True, alpha=0.3)

# 下圖：各拍攝歸一化（÷平均值），看形狀是否水平
ax2 = axes[1]
for i, (name, band_data) in enumerate(results.items()):
    vals = np.array(list(band_data.values()), dtype=float)
    if vals.mean() > 0:
        vals_norm = vals / vals.mean()
    else:
        vals_norm = vals
    bands = [int(k.replace("nm","")) for k in band_data.keys()]
    ax2.plot(bands, vals_norm, marker='o', markersize=4, label=name, color=colors[i])

ax2.axhline(1.0, color='gray', linestyle='--', linewidth=1, label='理想水平線')
n = len(all_bands) if all_bands else 30
ax2.fill_between(all_bands or list(range(350, 951, 20)),
                 [0.95]*n, [1.05]*n, alpha=0.1, color='green', label='±5% 範圍')
ax2.set_title("白紙光譜（歸一化，理想情況應接近水平）", fontsize=13)
ax2.set_xlabel("波長 (nm)")
ax2.set_ylabel("歸一化反射率")
ax2.legend(fontsize=8)
ax2.grid(True, alpha=0.3)

plt.tight_layout()
plot_path = os.path.join(OUT_DIR, "white_paper_spectrum.png")
plt.savefig(plot_path, dpi=150)
print(f"\n圖表已存：{plot_path}")

# ── 數值分析報告 ────────────────────────────────────────────────────────────
print("\n========== 白紙光譜分析報告 ==========")
for name, band_data in results.items():
    vals = np.array(list(band_data.values()), dtype=float)
    mn, mx = vals.min(), vals.max()
    mean = vals.mean()
    variation = (mx - mn) / mean * 100 if mean > 0 else 0
    print(f"\n{name}:")
    print(f"  平均值 = {mean:.2f}  最小 = {mn:.2f}  最大 = {mx:.2f}")
    print(f"  波段間變異 = {variation:.1f}%  {'✓ 水平良好 (<10%)' if variation < 10 else '⚠ 變異偏大，標定可能有問題'}")

# 合并 CSV
merged_path = os.path.join(OUT_DIR, "white_paper_all_captures.csv")
with open(merged_path, "w", newline="") as f:
    writer = csv.writer(f)
    if results:
        first = next(iter(results.values()))
        header = ["capture"] + list(first.keys())
        writer.writerow(header)
        for name, band_data in results.items():
            writer.writerow([name] + list(band_data.values()))
print(f"\n匯總 CSV：{merged_path}")
print("======================================")
