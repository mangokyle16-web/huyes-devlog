"""
咖啡豆新鮮度指數（Freshness Index）初步分析
資料來源：spec_fingerprint_20beans.csv
方法：FI = R_460 / R_900（使用 450+470nm 平均 vs 890+910nm 平均）
"""

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.colors import Normalize
from matplotlib.cm import ScalarMappable

# ── 載入資料 ──────────────────────────────────────────────
CSV = "/home/kyle/Desktop/GigaImage_20260413_174159/spec_fingerprint_20beans.csv"
df = pd.read_csv(CSV, index_col=0)  # index = wavelength_nm
beans = df.columns.tolist()  # bean_1 … bean_20
wl = df.index.values.astype(float)  # 350…930

# ── 計算新鮮度指數 ─────────────────────────────────────────
# 459nm 代理：450nm + 470nm 平均
R_blue = (df.loc[450] + df.loc[470]) / 2.0

# 900nm 代理：890nm + 910nm 平均
R_nir  = (df.loc[890] + df.loc[910]) / 2.0

FI = R_blue / R_nir   # 低 = 新鮮（CGA 吸收強 + NIR 高）

# 輔助指標
# NIR slope：R_910 - R_750（越高表示 NIR 更陡，水分/結構差異）
NIR_slope = df.loc[910] - df.loc[750]

# Blue absorption depth：1 - R_460/R_510（CGA 特徵吸收深度）
blue_depth = 1.0 - (R_blue / df.loc[510])

# 綜合新鮮度分數（標準化到 0-100，低 FI + 高 NIR slope → 新鮮）
from sklearn.preprocessing import MinMaxScaler

fi_norm       = 1.0 - (FI - FI.min()) / (FI.max() - FI.min())       # 反轉：低FI→高分
slope_norm    = (NIR_slope - NIR_slope.min()) / (NIR_slope.max() - NIR_slope.min())
depth_norm    = (blue_depth - blue_depth.min()) / (blue_depth.max() - blue_depth.min())

# 加權合成（FI 為主指標）
fresh_score = (fi_norm * 0.5 + slope_norm * 0.3 + depth_norm * 0.2) * 100

# ── 列印結果 ──────────────────────────────────────────────
print("=" * 65)
print(f"{'Bean':<10} {'R_460':>8} {'R_900':>8} {'FI':>8} {'NIR_slope':>10} {'Score':>8}")
print("-" * 65)

results = pd.DataFrame({
    "R_460": R_blue,
    "R_900": R_nir,
    "FI": FI,
    "NIR_slope": NIR_slope,
    "blue_depth": blue_depth,
    "fresh_score": fresh_score,
})
results_sorted = results.sort_values("fresh_score", ascending=False)

for bean, row in results_sorted.iterrows():
    marker = ""
    if row["fresh_score"] >= 70: marker = "★ 新鮮"
    elif row["fresh_score"] <= 30: marker = "△ 老化"
    print(f"{bean:<10} {row['R_460']:>8.4f} {row['R_900']:>8.4f} {row['FI']:>8.4f} "
          f"{row['NIR_slope']:>10.4f} {row['fresh_score']:>8.1f}  {marker}")

print("=" * 65)
print(f"FI 平均: {FI.mean():.4f}  ±  {FI.std():.4f}")
print(f"Score 平均: {fresh_score.mean():.1f}  ±  {fresh_score.std():.1f}")

# ── 視覺化 ────────────────────────────────────────────────
OUT_DIR = "/home/kyle/Desktop/freshness_analysis"
import os; os.makedirs(OUT_DIR, exist_ok=True)

cmap = plt.cm.RdYlGn
norm = Normalize(vmin=0, vmax=100)

fig = plt.figure(figsize=(18, 14))
gs = gridspec.GridSpec(3, 3, figure=fig, hspace=0.42, wspace=0.35)

# ── 圖1：所有豆子光譜（依新鮮度著色）─────────────────
ax1 = fig.add_subplot(gs[0, :2])
for bean in beans:
    score = fresh_score[bean]
    color = cmap(norm(score))
    ax1.plot(wl, df[bean].values, color=color, alpha=0.7, lw=1.2)
ax1.axvline(460, color='royalblue', ls='--', lw=1.5, label='~460nm')
ax1.axvline(900, color='darkorange', ls='--', lw=1.5, label='~900nm')
sm = ScalarMappable(cmap=cmap, norm=norm)
sm.set_array([])
plt.colorbar(sm, ax=ax1, label='新鮮度分數')
ax1.set_xlabel('Wavelength (nm)')
ax1.set_ylabel('Spectral Value')
ax1.set_title('全波段光譜（綠=新鮮 / 紅=老化）')
ax1.legend(fontsize=9)

# ── 圖2：FI 條形圖 ────────────────────────────────────────
ax2 = fig.add_subplot(gs[0, 2])
bean_labels = [b.replace("bean_", "B") for b in results_sorted.index]
colors_bar = [cmap(norm(s)) for s in results_sorted["fresh_score"]]
ax2.barh(bean_labels, results_sorted["FI"], color=colors_bar)
ax2.set_xlabel('FI = R₄₆₀ / R₉₀₀')
ax2.set_title('新鮮度指數 FI（低=新鮮）')
ax2.invert_yaxis()
ax2.axvline(FI.mean(), color='gray', ls='--', lw=1, label=f'平均 {FI.mean():.3f}')
ax2.legend(fontsize=8)

# ── 圖3：新鮮度分數條形圖 ─────────────────────────────────
ax3 = fig.add_subplot(gs[1, :2])
bean_order = [b.replace("bean_", "B") for b in results_sorted.index]
ax3.bar(bean_order, results_sorted["fresh_score"], color=colors_bar, edgecolor='white', lw=0.5)
ax3.axhline(70, color='green', ls='--', lw=1.5, label='新鮮門檻 70')
ax3.axhline(30, color='red',   ls='--', lw=1.5, label='老化門檻 30')
ax3.set_ylabel('新鮮度分數 (0-100)')
ax3.set_title('綜合新鮮度分數（主 FI 0.5 + NIR slope 0.3 + Blue depth 0.2）')
ax3.legend(fontsize=9)
ax3.set_ylim(0, 110)
for i, (bean, score) in enumerate(zip(results_sorted.index, results_sorted["fresh_score"])):
    ax3.text(i, score + 2, f'{score:.0f}', ha='center', fontsize=7)

# ── 圖4：散佈圖 R_460 vs R_900 ───────────────────────────
ax4 = fig.add_subplot(gs[1, 2])
for bean in beans:
    score = fresh_score[bean]
    color = cmap(norm(score))
    ax4.scatter(R_nir[bean], R_blue[bean], color=color, s=60, zorder=3)
    ax4.annotate(bean.replace("bean_","B"), (R_nir[bean], R_blue[bean]),
                 fontsize=7, ha='center', va='bottom')
ax4.set_xlabel('R₉₀₀（NIR，水分相關）')
ax4.set_ylabel('R₄₆₀（藍光，CGA 相關）')
ax4.set_title('R₄₆₀ vs R₉₀₀ 散佈圖')

# ── 圖5：460nm 差分光譜（相對平均）──────────────────────
ax5 = fig.add_subplot(gs[2, :])
mean_spec = df.mean(axis=1)
for bean in beans:
    score = fresh_score[bean]
    color = cmap(norm(score))
    diff = df[bean] - mean_spec
    ax5.plot(wl, diff.values, color=color, alpha=0.7, lw=1.2,
             label=bean.replace("bean_","B") if score >= 70 or score <= 30 else "")
ax5.axhline(0, color='gray', ls='-', lw=0.8)
ax5.axvline(460, color='royalblue', ls='--', lw=1.5)
ax5.axvline(900, color='darkorange', ls='--', lw=1.5)
ax5.set_xlabel('Wavelength (nm)')
ax5.set_ylabel('差分（豆子 − 平均）')
ax5.set_title('差分光譜（綠=新鮮端 / 紅=老化端，極端值標記）')
ax5.legend(fontsize=8, ncol=4)

plt.suptitle('咖啡豆新鮮度指數（FI）初步分析 — 20 顆豆子相對比較', fontsize=13, y=1.01)

OUT_PNG = f"{OUT_DIR}/freshness_index_report.png"
plt.savefig(OUT_PNG, dpi=150, bbox_inches='tight')
plt.close()
print(f"\n報告已儲存：{OUT_PNG}")

# ── 輸出 CSV ─────────────────────────────────────────────
results_sorted.to_csv(f"{OUT_DIR}/freshness_scores.csv", float_format="%.4f")
print(f"數據已儲存：{OUT_DIR}/freshness_scores.csv")
