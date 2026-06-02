#!/usr/bin/env python3
"""
export_report.py
產生自含式 HTML 報告（圖片內嵌 base64），Windows 瀏覽器直接開啟。
"""
import base64, os
from datetime import date

OUT_DIR  = "/home/kyle/Desktop/mold_detection"
BEAN_DIR = "/home/kyle/Desktop/GigaImage_20260413_174159"
WP_DIR   = "/home/kyle/Desktop/white_paper_check"
HTML_OUT = "/home/kyle/Desktop/mold_detection/咖啡豆黴菌偵測報告_20260414.html"

def img_b64(path):
    if not os.path.exists(path):
        return None
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()

def img_tag(path, width="100%", caption=""):
    b = img_b64(path)
    if not b:
        return f"<p style='color:red'>[圖片不存在：{path}]</p>"
    fn = os.path.basename(path)
    cap = f"<figcaption style='font-size:12px;color:#666;margin-top:4px'>{caption or fn}</figcaption>"
    return f"""<figure style='margin:12px 0'>
  <img src='data:image/png;base64,{b}' style='width:{width};border:1px solid #ddd;border-radius:6px'/>
  {cap}
</figure>"""

html = f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="UTF-8">
<title>咖啡豆黴菌偵測報告 — 2026-04-14</title>
<style>
  body {{ font-family: 'Segoe UI', Arial, sans-serif; max-width: 1100px; margin: 0 auto; padding: 24px; background:#f9f9f9; color:#222; }}
  h1 {{ background:#2c3e50; color:#fff; padding:18px 24px; border-radius:8px; margin-bottom:8px; }}
  h2 {{ color:#2c3e50; border-left:5px solid #e74c3c; padding-left:12px; margin-top:36px; }}
  h3 {{ color:#34495e; border-left:3px solid #95a5a6; padding-left:10px; }}
  .meta {{ color:#666; font-size:13px; margin-bottom:24px; }}
  table {{ border-collapse:collapse; width:100%; margin:12px 0; font-size:14px; }}
  th {{ background:#2c3e50; color:#fff; padding:8px 12px; text-align:left; }}
  td {{ padding:7px 12px; border-bottom:1px solid #ddd; }}
  tr:nth-child(even) {{ background:#f4f4f4; }}
  .high {{ background:#fde8e8!important; font-weight:bold; }}
  .med  {{ background:#fff3e0!important; }}
  .ok   {{ background:#e8f8e8!important; }}
  .badge-high {{ background:#e74c3c; color:#fff; padding:2px 8px; border-radius:10px; font-size:12px; }}
  .badge-med  {{ background:#f39c12; color:#fff; padding:2px 8px; border-radius:10px; font-size:12px; }}
  .badge-ok   {{ background:#27ae60; color:#fff; padding:2px 8px; border-radius:10px; font-size:12px; }}
  .box {{ background:#fff; border:1px solid #ddd; border-radius:8px; padding:16px 20px; margin:12px 0; }}
  .warn {{ background:#fff8e1; border-left:4px solid #f39c12; padding:10px 16px; border-radius:4px; margin:8px 0; }}
  .info {{ background:#e3f2fd; border-left:4px solid #2196f3; padding:10px 16px; border-radius:4px; margin:8px 0; }}
  .grid2 {{ display:grid; grid-template-columns:1fr 1fr; gap:16px; }}
  code {{ background:#eee; padding:2px 6px; border-radius:3px; font-family:monospace; }}
  .footer {{ text-align:center; color:#aaa; font-size:12px; margin-top:40px; border-top:1px solid #ddd; padding-top:16px; }}
</style>
</head>
<body>

<h1>&#9749; 咖啡生豆多光譜黴菌偵測報告</h1>
<div class="meta">
  分析日期：2026-04-14 ｜ 硬體：CM020D 多光譜相機（350–950nm，30 波段）｜ 平台：Raspberry Pi 5
</div>

<!-- ══════════════════ 摘要 ══════════════════ -->
<h2>&#x1F4CB; 執行摘要</h2>
<div class="box">
  <p>對 <strong>20 顆咖啡生豆</strong>進行多光譜反射率分析，使用 <strong>in-situ 局部 flat-field 校正</strong>（每顆豆用其周圍白紙背景做局部校正，消除照明空間不均勻影響），以 <strong>Mahalanobis distance + UV z-score</strong> 雙指標判定異常。</p>
  <div class="warn">⚠ 本分析為白光 LED 反射率異常偵測，非真正 365nm UV 螢光分析。建議用 365nm UV 手電筒對可疑豆實際照射確認。</div>
</div>

<h3>&#x1F3AF; 重點結論</h3>
<table>
  <tr><th>#</th><th>豆子</th><th>Mahalanobis</th><th>UV z-score</th><th>等級</th><th>建議</th></tr>
  <tr class="high"><td>1</td><td><strong>Bean 9</strong></td><td>3.25</td><td>−0.19</td><td><span class="badge-high">HIGH</span></td><td>優先用 365nm UV 確認</td></tr>
  <tr class="high"><td>2</td><td><strong>Bean 8</strong></td><td>3.19</td><td>+0.94</td><td><span class="badge-high">HIGH</span></td><td>優先用 365nm UV 確認</td></tr>
  <tr class="med"><td>3</td><td><strong>Bean 14</strong></td><td>2.92</td><td>+1.41</td><td><span class="badge-med">MED</span></td><td>次優先確認</td></tr>
  <tr class="ok"><td>4</td><td>Bean 16</td><td>2.56</td><td>−2.07</td><td><span class="badge-ok">OK*</span></td><td>UV 吸收最強，值得留意</td></tr>
  <tr class="ok"><td>5</td><td>Bean 19</td><td>2.51</td><td>−1.58</td><td><span class="badge-ok">OK*</span></td><td>UV 吸收次強</td></tr>
  <tr class="ok"><td>—</td><td>其餘 15 顆</td><td>&lt;2.5</td><td>—</td><td><span class="badge-ok">OK</span></td><td>正常</td></tr>
</table>
<p style="font-size:12px;color:#666">* OK* = Mahalanobis 在閾值以下，但 UV z-score 偏負，需 UV 手電筒確認</p>

<!-- ══════════════════ 標示圖 ══════════════════ -->
<h2>&#x1F5BC; 豆子位置標示圖</h2>
{img_tag(f"{OUT_DIR}/mold_final_labeled.png", "100%",
  "最終標示圖：紅=HIGH，橙=MED，綠=OK。標籤中 z= 為 UV 區 z-score（負值=UV 吸收異常）")}

<!-- ══════════════════ 分析報告圖 ══════════════════ -->
<h2>&#x1F4CA; 完整分析報告</h2>
{img_tag(f"{OUT_DIR}/mold_final_report.png", "100%",
  "左：光譜指紋疊加｜中：z-score 熱力圖（紅=偏低/藍=偏高，UV 區紫色標注）｜右：Mahalanobis 距離排名")}

<div class="info">
  &#x1F4A1; <strong>z-score 熱力圖看法：</strong>紫色框住的 UV 區（350–450nm）若呈現深紅色（z &lt; −1），代表該豆在 UV 波段吸收偏強，與黃麴毒素的 UV 吸收特徵一致。
</div>

<!-- ══════════════════ 方法說明 ══════════════════ -->
<h2>&#x1F9EA; 分析方法</h2>
<div class="box">
  <h3>In-situ Flat-Field 校正</h3>
  <p>每顆豆的光譜 ÷ 豆子周圍 4 個方向（上下左右各 20px 寬）的白紙背景平均值。<br>
  優點：使用同一張影像、同一時刻的白紙背景，完全消除跨場次照明變動影響。</p>

  <h3>Mahalanobis Distance（主指標）</h3>
  <p>在 PCA 前 6 個主成分空間中計算各豆到正常群體中心的馬氏距離，考慮波段間相關性，是高光譜異常偵測的標準方法。<br>
  閾值：<code>mean + 1.5σ → HIGH</code>，<code>mean + 0.8σ → MED</code></p>

  <h3>UV z-score（輔助指標，最接近 365nm UV 特徵）</h3>
  <p>350–450nm 波段的平均 z-score。黃麴毒素在 365nm 附近有強吸收，感染豆在 UV 端反射率偏低（z &lt; −0.5 為異常）。</p>
</div>

<!-- ══════════════════ 白紙校正分析 ══════════════════ -->
<h2>&#x1F4C8; 白紙光譜校正分析</h2>
<div class="grid2">
  {img_tag(f"{WP_DIR}/white_paper_grid_heatmap.png", "100%",
    "3×3 格子均值熱力圖：Cell 22（中心）偏暗，照明中心偏左")}
  {img_tag(f"{WP_DIR}/white_paper_grid_spectrum.png", "100%",
    "9 格光譜疊加：形狀一致（標定正常），絕對值差異=照明不均")}
</div>
<div class="warn">
  ⚠ 跨場次白紙做 flat-field 曾造成角落豆（Bean 17、18）誤判為 HIGH，改用 in-situ 校正後恢復正常。
</div>
{img_tag(f"{OUT_DIR}/mold_insitu_labeled.png", "100%",
  "in-situ 校正示意：藍色小框為每顆豆周圍的局部白紙採樣區域")}

<!-- ══════════════════ 後續步驟 ══════════════════ -->
<h2>&#x1F4CC; 後續驗證步驟</h2>
<div class="box">
  <ol>
    <li>用 <strong>365nm UV 手電筒</strong>在暗室中照射 Bean 8、9、14、16、19</li>
    <li>觀察是否有 <strong>藍綠色螢光</strong>（黃麴毒素 B1 @ 450nm、G1 @ 520nm）</li>
    <li>與本報告的 HIGH/MED 結果對齊比較</li>
    <li>若 UV 螢光與高光譜異常一致 → 建立分類模型基準</li>
    <li>若不一致 → 調整各指標權重或加入更多訓練樣本</li>
  </ol>
</div>

<!-- ══════════════════ 技術規格 ══════════════════ -->
<h2>&#x2699;&#xFE0F; 技術規格</h2>
<table>
  <tr><th>項目</th><th>規格</th></tr>
  <tr><td>相機</td><td>CM020D 多光譜相機</td></tr>
  <tr><td>波段範圍</td><td>350–930nm，30 波段，步距 20nm</td></tr>
  <tr><td>光譜曝光</td><td>10000 μs</td></tr>
  <tr><td>分割曝光</td><td>5000 μs</td></tr>
  <tr><td>校準檔</td><td>camera_new.qsbs</td></tr>
  <tr><td>分割方法</td><td>兩段式閾值（t65 定位 + t80 輪廓）</td></tr>
  <tr><td>Flat-field</td><td>in-situ 局部背景（PAD=25px, BG_W=20px）</td></tr>
  <tr><td>異常偵測</td><td>Mahalanobis（PCA 6D）+ UV z-score</td></tr>
  <tr><td>豆子數量</td><td>20 顆咖啡生豆</td></tr>
  <tr><td>拍攝時間</td><td>2026-04-13 17:41</td></tr>
</table>

<div class="footer">
  Generated by Claude Code + CM020D Multispectral Pipeline ｜ 2026-04-14<br>
  檔案路徑：/home/kyle/Desktop/mold_detection/
</div>

</body>
</html>"""

with open(HTML_OUT, "w", encoding="utf-8") as f:
    f.write(html)
print(f"[OK] {HTML_OUT}")
print(f"     大小：{os.path.getsize(HTML_OUT)/1024/1024:.1f} MB")
