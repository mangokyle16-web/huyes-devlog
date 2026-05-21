#!/usr/bin/env python3
"""
spec_viz.py  <session_dir>
讀取 spec_raw.csv → 輸出兩張獨立圖：
  spec_curves_0.png  全部豆子光譜曲線
  spec_curves_1.png  Mean ± 1σ
"""
import sys, csv, os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

SESSION_DIR = sys.argv[1] if len(sys.argv) > 1 else "."
CSV_PATH    = os.path.join(SESSION_DIR, "spec_raw.csv")

# Read CSV
bands, raw = [], {}
with open(CSV_PATH) as f:
    reader = csv.DictReader(f)
    bkeys = [k for k in reader.fieldnames if k.startswith("bean_")]
    rows  = list(reader)

for bk in bkeys:
    bid = int(bk.split("_")[1])
    raw[bid] = np.array([float(row[bk]) for row in rows])
bands = np.array([int(float(row["wavelength_nm"])) for row in rows])
bean_ids = sorted(raw.keys())
n = len(bean_ids)

DARK_BG = "#1a1a1a"
AXIS_BG = "#111111"
SPINE_C = "#444444"

def style_ax(ax):
    ax.set_facecolor(AXIS_BG)
    ax.tick_params(colors="gray")
    for sp in ax.spines.values():
        sp.set_color(SPINE_C)

# ── 圖 0：所有豆子光譜曲線 ────────────────────────────────────────────
fig0, ax0 = plt.subplots(figsize=(6, 4.5), facecolor=DARK_BG)
fig0.subplots_adjust(left=0.10, right=0.97, top=0.90, bottom=0.13)
style_ax(ax0)
cmap = plt.cm.plasma
for i, bid in enumerate(bean_ids):
    ax0.plot(bands, raw[bid], color=cmap(i / max(n - 1, 1)), alpha=0.65, linewidth=1.1)
ax0.axvspan(350, 450, alpha=0.12, color="violet", label="UV")
ax0.axvspan(620, 700, alpha=0.10, color="red",    label="Red")
ax0.axvspan(750, 850, alpha=0.10, color="darkred", label="NIR")
ax0.set_xlabel("Wavelength (nm)", color="white")
ax0.set_ylabel("Radiance (raw)",  color="white")
ax0.set_title(f"Spectral Curves  ({n} beans)", color="white", fontsize=11)
ax0.legend(fontsize=7, framealpha=0.4, labelcolor="white")
out0 = os.path.join(SESSION_DIR, "spec_curves_0.png")
fig0.savefig(out0, dpi=90, bbox_inches="tight", facecolor=DARK_BG)
plt.close(fig0)
print(f"[spec_viz] → {out0}  ({n} beans, {len(bands)} bands)")

# ── 圖 1：Mean ± 1σ ──────────────────────────────────────────────────
fig1, ax1 = plt.subplots(figsize=(6, 4.5), facecolor=DARK_BG)
fig1.subplots_adjust(left=0.10, right=0.97, top=0.90, bottom=0.13)
style_ax(ax1)
X = np.array([raw[bid] for bid in bean_ids])
mu, sd = X.mean(0), X.std(0)
ax1.plot(bands, mu, color="#00cfff", linewidth=1.8, label="Mean")
ax1.fill_between(bands, mu - sd, mu + sd, alpha=0.25, color="#00cfff", label=u"±1σ")
ax1.axvspan(350, 450, alpha=0.12, color="violet")
ax1.axvspan(750, 850, alpha=0.10, color="darkred")
ax1.set_xlabel("Wavelength (nm)", color="white")
ax1.set_ylabel("Radiance (raw)",  color="white")
ax1.set_title(u"Mean ± 1σ", color="white", fontsize=11)
ax1.legend(fontsize=7, framealpha=0.4, labelcolor="white")
out1 = os.path.join(SESSION_DIR, "spec_curves_1.png")
fig1.savefig(out1, dpi=90, bbox_inches="tight", facecolor=DARK_BG)
plt.close(fig1)
print(f"[spec_viz] → {out1}")
