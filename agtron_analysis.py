#!/usr/bin/env python3
"""
agtron_analysis.py <session_dir>

Estimates Agtron roast value per bean from multispectral spectral data.
Reads:  spec_raw.csv, beans_labelmap.png, optional white_spec.csv,
        optional ~/KyleClaude/agtron_calibration.json
Writes: agtron_result.json, agtron_labeled.png
"""
import sys, os, json, csv
import numpy as np
import cv2

SESSION_DIR = sys.argv[1] if len(sys.argv) > 1 else "."
FAST_MODE   = "--fast" in sys.argv   # skip matplotlib charts (result + labeled PNG only)


def load_spec_csv(path):
    bands, spectra = [], {}
    with open(path) as f:
        reader = csv.DictReader(f)
        bkeys = [k for k in reader.fieldnames if k.startswith("bean_")]
        rows  = list(reader)
    for bk in bkeys:
        bid = int(bk.split("_")[1])
        spectra[bid] = np.array([float(row[bk]) for row in rows])
    bands = np.array([float(row["wavelength_nm"]) for row in rows])
    return bands, spectra


# ── 1. Load bean spectra ──────────────────────────────────────────────────────
# Prefer agtron_raw_spec.csv (no flat-field) for accurate NIR normalization.
# Per-pixel flat-field is invalid when white paper doesn't cover bean positions.
RAW_SPEC_CSV = os.path.join(SESSION_DIR, "agtron_raw_spec.csv")
spec_csv     = os.path.join(SESSION_DIR, "spec_raw.csv")

if os.path.exists(RAW_SPEC_CSV):
    bands, spectra = load_spec_csv(RAW_SPEC_CSV)
    use_raw_spec = True
    print("[agtron] Using agtron_raw_spec.csv (no flat-field)", flush=True)
elif os.path.exists(spec_csv):
    bands, spectra = load_spec_csv(spec_csv)
    use_raw_spec = False
else:
    print("[agtron] No spec CSV found", flush=True)
    sys.exit(1)

bean_ids = sorted(spectra.keys())

# ── 1b. Cylinder mask — filter beans outside the camera FOV circle ────────────
# Camera is fixed at top of black cylinder; cylinder diameter < camera 16:9 FOV.
# Detect the valid circular area from background_1250us.png (dark outside, bright inside).
# Saves result to a global JSON so subsequent sessions skip re-detection.
GLOBAL_CYLINDER_JSON  = "/home/kyle/KyleClaude/cylinder_mask.json"
SESSION_CYLINDER_JSON = os.path.join(SESSION_DIR, "cylinder_mask.json")

def _detect_cylinder_from_image(img_path):
    """Return (cx, cy, r, W, H) from a grayscale image, or None."""
    img = cv2.imread(img_path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        return None
    H, W = img.shape
    binary = (img > 35).astype(np.uint8) * 255
    cnts, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return None
    largest = max(cnts, key=cv2.contourArea)
    if cv2.contourArea(largest) < 0.05 * W * H:  # sanity: must cover >5% of image
        return None
    (cx, cy), r = cv2.minEnclosingCircle(largest)
    return float(cx), float(cy), float(r), W, H

cylinder_cx = cylinder_cy = cylinder_r = None
cylinder_iw = cylinder_ih = None

# Priority: session-local copy (placed by app at startup) → global → auto-detect
_cyl_src = None
if os.path.exists(SESSION_CYLINDER_JSON):
    _cyl_src = SESSION_CYLINDER_JSON
elif os.path.exists(GLOBAL_CYLINDER_JSON):
    _cyl_src = GLOBAL_CYLINDER_JSON

if _cyl_src:
    with open(_cyl_src) as _f:
        _cp = json.load(_f)
    cylinder_cx, cylinder_cy, cylinder_r = _cp["cx"], _cp["cy"], _cp["r"]
    cylinder_iw, cylinder_ih = _cp["image_w"], _cp["image_h"]
    _tag = "session" if _cyl_src == SESSION_CYLINDER_JSON else "global"
    print(f"[agtron] Cylinder mask ({_tag}): c=({cylinder_cx:.0f},{cylinder_cy:.0f}) r={cylinder_r:.0f}", flush=True)
else:
    # Last resort: auto-detect from this session's background image
    _bg_path = os.path.join(SESSION_DIR, "background_1250us.png")
    _det = _detect_cylinder_from_image(_bg_path)
    if _det:
        cylinder_cx, cylinder_cy, cylinder_r, cylinder_iw, cylinder_ih = _det
        _cp = {"cx": cylinder_cx, "cy": cylinder_cy, "r": cylinder_r,
               "image_w": cylinder_iw, "image_h": cylinder_ih,
               "note": f"auto-detected from {_bg_path}"}
        with open(GLOBAL_CYLINDER_JSON, "w") as _f:
            json.dump(_cp, _f, indent=2)
        print(f"[agtron] Cylinder detected & saved: c=({cylinder_cx:.0f},{cylinder_cy:.0f}) r={cylinder_r:.0f}", flush=True)
    else:
        print("[agtron] No cylinder mask — using all beans", flush=True)

# Apply cylinder mask: filter bean_ids by centroid position in the full-res labelmap
_lmap_full_path = os.path.join(SESSION_DIR, "beans_labelmap.png")
if cylinder_r and os.path.exists(_lmap_full_path):
    _lmap_full = cv2.imread(_lmap_full_path, cv2.IMREAD_GRAYSCALE)
    _LH, _LW = _lmap_full.shape
    # Scale cylinder params from capture resolution to labelmap resolution
    _sx = _LW / cylinder_iw
    _sy = _LH / cylinder_ih
    _cx_s = cylinder_cx * _sx
    _cy_s = cylinder_cy * _sy
    _r_s  = cylinder_r  * min(_sx, _sy)
    _kept, _dropped = [], []
    for _bid in bean_ids:
        _bpx = np.where(_lmap_full == _bid)
        if len(_bpx[0]) == 0:
            continue
        _bcy = _bpx[0].mean()
        _bcx = _bpx[1].mean()
        if (_bcx - _cx_s)**2 + (_bcy - _cy_s)**2 <= _r_s**2:
            _kept.append(_bid)
        else:
            _dropped.append(_bid)
    if _dropped:
        print(f"[agtron] Cylinder mask: dropped {len(_dropped)} outside-circle beans, kept {len(_kept)}", flush=True)
    bean_ids = _kept if _kept else bean_ids  # fallback if detection went wrong

# ── 2. White reference ───────────────────────────────────────────────────────
FLATFIELD_MARKER = os.path.join(SESSION_DIR, "flatfield_used.txt")
has_flatfield = os.path.exists(FLATFIELD_MARKER) and not use_raw_spec

GLOBAL_WHITE_CSV = "/home/kyle/KyleClaude/white_spec.csv"

if use_raw_spec:
    # Raw spec: always normalize by white_spec.csv (global or session)
    white_csv = os.path.join(SESSION_DIR, "white_spec.csv")
    if not os.path.exists(white_csv) and os.path.exists(GLOBAL_WHITE_CSV):
        white_csv = GLOBAL_WHITE_CSV
    if os.path.exists(white_csv):
        white_bands, white_spectra = load_spec_csv(white_csv)
        white_key = sorted(white_spectra.keys())[0]
        white_ref_raw = white_spectra[white_key]
        # Align white_ref to our bands (interpolate: handles 2-band agtron-only mode)
        white_ref = np.interp(bands, white_bands, white_ref_raw)
        has_white = True
        src = "(global)" if white_csv == GLOBAL_WHITE_CSV else "(session)"
        w850 = white_ref[bands==850][0] if (bands==850).any() else float(np.interp(850, bands, white_ref))
        w930 = white_ref[bands==930][0] if (bands==930).any() else float(np.interp(930, bands, white_ref))
        print(f"[agtron] White ref {src}: 850nm={w850:.1f}  930nm={w930:.1f}", flush=True)
    else:
        white_ref = None
        has_white = False
        print("[agtron] No white_spec.csv — batch-relative Agtron estimate", flush=True)
elif has_flatfield:
    # Per-pixel flat-field already applied in spec_raw.csv
    white_ref = None
    has_white = True
    ff_path = open(FLATFIELD_MARKER).read().strip()
    print(f"[agtron] Flat-field spec_raw ({ff_path})", flush=True)
else:
    white_csv = os.path.join(SESSION_DIR, "white_spec.csv")
    if not os.path.exists(white_csv) and os.path.exists(GLOBAL_WHITE_CSV):
        white_csv = GLOBAL_WHITE_CSV
    if os.path.exists(white_csv):
        white_bands, white_spectra = load_spec_csv(white_csv)
        white_key = sorted(white_spectra.keys())[0]
        white_ref_raw = white_spectra[white_key]
        white_ref = np.interp(bands, white_bands, white_ref_raw)
        has_white = True
        src = "(global)" if white_csv == GLOBAL_WHITE_CSV else "(session)"
        print(f"[agtron] White ref loaded {src}", flush=True)
    else:
        white_ref = None
        has_white = False
        print("[agtron] No white_spec.csv — batch-relative Agtron estimate", flush=True)

# ── 3. Calibration (linear: Agtron = a*raw + b) ───────────────────────────────
calibration = None
for cal_path in [
    os.path.join(SESSION_DIR, "agtron_calibration.json"),
    "/home/kyle/KyleClaude/agtron_calibration.json",
]:
    if os.path.exists(cal_path):
        with open(cal_path) as f:
            calibration = json.load(f)
        print(f"[agtron] Calibration: a={calibration['a']:.4f} b={calibration['b']:.2f}", flush=True)
        break

# ── 3b. Cal-white normalization ────────────────────────────────────────────────
# If calibration stores cal_white_850/930, always normalize by those fixed values
# so Agtron output is stable regardless of when/how white ref was retaken.
cal_white_ref = None
if calibration and "cal_white_850" in calibration and "cal_white_930" in calibration:
    cw850 = float(calibration["cal_white_850"])
    cw930 = float(calibration["cal_white_930"])
    base = white_ref.copy() if white_ref is not None else np.ones(len(bands))
    for i, wl in enumerate(bands):
        if 850 <= wl <= 930:
            t = (float(wl) - 850.0) / 80.0
            base[i] = cw850 + t * (cw930 - cw850)
    cal_white_ref = base
    print(f"[agtron] Cal-white 850={cw850:.1f} 930={cw930:.1f} — stable normalization", flush=True)

# ── 4. Agtron estimation ──────────────────────────────────────────────────────
# Mode A: 850+930nm average (simple, variety-dependent)
# Mode B: 850-930nm broad average
# Mode C: (R_850-R_930)/(R_850+R_930) normalized difference — variety-corrected
#   Multiplicative variety factor k cancels: (kR850-kR930)/(kR850+kR930) = (R850-R930)/(R850+R930)
#   Mirrors DiFluid's cross-variety 850+940nm approach.
MASK_A = np.isin(bands, [850, 930])
MASK_B = bands >= 850

def get_white(mask):
    if cal_white_ref is not None:
        w = np.where(cal_white_ref > 1.0, cal_white_ref, 1.0)
    elif has_white and white_ref is not None:
        w = np.where(white_ref > 1.0, white_ref, 1.0)
    else:
        w = None
    return w

def calc_reflectances(mask):
    w = get_white(mask)
    if has_flatfield:
        return np.array([spectra[bid][mask].mean() for bid in bean_ids])
    elif w is not None:
        return np.array([(spectra[bid] / w)[mask].mean() for bid in bean_ids])
    else:
        raw = np.array([spectra[bid][mask].mean() for bid in bean_ids])
        return raw / (raw.max() if raw.max() > 0 else 1.0)

def calc_global_ndiff():
    """Global (R_850-R_930)/(R_850+R_930)*100 — pool all bean means first, then ratio.
    Mirrors DiFluid: captures 850+940nm of whole scene, computes single ratio.
    Cancels multiplicative variety factor k: (k*pool850-k*pool930)/(k*pool850+k*pool930).
    """
    w = get_white(MASK_A)
    idx850 = np.where(bands == 850)[0]
    idx930 = np.where(bands == 930)[0]
    if len(idx850) == 0 or len(idx930) == 0:
        return float(calc_reflectances(MASK_A).mean() * 100.0)
    all_r850, all_r930 = [], []
    for bid in bean_ids:
        s = spectra[bid]
        if w is not None:
            all_r850.append(s[idx850[0]] / w[idx850[0]])
            all_r930.append(s[idx930[0]] / w[idx930[0]])
        else:
            all_r850.append(float(s[idx850[0]]))
            all_r930.append(float(s[idx930[0]]))
    pool850 = float(np.mean(all_r850))
    pool930 = float(np.mean(all_r930))
    denom = pool850 + pool930
    return float((pool850 - pool930) / denom * 100.0) if denom > 0 else 0.0

nir_reflectances_a = calc_reflectances(MASK_A)
nir_reflectances_b = calc_reflectances(MASK_B)

agtron_raw_a = nir_reflectances_a * 100.0
agtron_raw_b = nir_reflectances_b * 100.0

# Select raw input for calibration based on calibration formula field
cal_formula = calibration.get("formula", "avg") if calibration else "avg"

if calibration:
    if cal_formula == "ndiff":
        # Global ndiff = (pool_R850-pool_R930)/(pool_R850+pool_R930)*100
        # Mirrors DiFluid: whole-scene ratio before averaging — variety k cancels.
        global_ndiff      = calc_global_ndiff()
        batch_mean_agtron = calibration["a"] * global_ndiff + calibration["b"]
        # Per-bean display: proportional scaling from simple reflectance (within-batch ranking)
        batch_avg_raw_a   = float(np.mean(agtron_raw_a))
        if batch_avg_raw_a > 0:
            agtron_vals_a = batch_mean_agtron * (agtron_raw_a / batch_avg_raw_a)
        else:
            agtron_vals_a = np.full(len(agtron_raw_a), batch_mean_agtron)
    else:
        agtron_vals_a = calibration["a"] * agtron_raw_a + calibration["b"]
    agtron_vals_b = calibration["a"] * agtron_raw_b + calibration["b"]
else:
    global_ndiff  = calc_global_ndiff()
    agtron_vals_a = agtron_raw_a
    agtron_vals_b = agtron_raw_b

agtron_vals_a = np.clip(agtron_vals_a, 0, 100)
agtron_vals_b = np.clip(agtron_vals_b, 0, 100)

# Primary display uses Mode A (DiFluid-aligned); both are saved to JSON
nir_reflectances = nir_reflectances_a
agtron_raw       = agtron_raw_a
agtron_vals      = agtron_vals_a


def classify(v):
    if v >= 75: return "Light"
    if v >= 65: return "Med-Lt"
    if v >= 55: return "Medium"
    if v >= 45: return "Med-Dk"
    if v >= 35: return "Dark"
    return "V.Dark"


def agtron_color(v):
    """BGR for Agtron value"""
    if v >= 75: return (89,  199, 52)   # Green  = Light
    if v >= 65: return (52,  160, 89)   # Teal   = Med-Light
    if v >= 55: return (10,  149, 255)  # Orange = Medium
    if v >= 45: return (30,  100, 255)  # D-Org  = Med-Dark
    if v >= 35: return (56,   68, 255)  # Red    = Dark
    return              (180,  56, 128) # Purple = V.Dark


results = {
    bid: {"agtron": round(float(agtron_vals[i]), 1), "class": classify(agtron_vals[i])}
    for i, bid in enumerate(bean_ids)
}
mean_agtron    = float(np.mean(agtron_vals_a))
mean_agtron_b  = float(np.mean(agtron_vals_b))
mean_ndiff_raw = global_ndiff
print(f"[agtron] formula={cal_formula}  mean={mean_agtron:.1f}  global_ndiff={mean_ndiff_raw:.3f}  ModeB={mean_agtron_b:.1f}  n={len(results)}", flush=True)

# ── 5. Bean size from labelmap ────────────────────────────────────────────────
mean_bean_area_px  = 0.0
mean_bean_diam_px  = 0.0
lmap_for_area = os.path.join(SESSION_DIR, "beans_labelmap.png")
if os.path.exists(lmap_for_area):
    _lmap = cv2.imread(lmap_for_area, cv2.IMREAD_GRAYSCALE)
    _ids  = [i for i in np.unique(_lmap) if i > 0]
    if _ids:
        _areas = [float(np.sum(_lmap == i)) for i in _ids]
        mean_bean_area_px = float(np.mean(_areas))
        mean_bean_diam_px = float(np.sqrt(mean_bean_area_px))  # equiv square side
        print(f"[agtron] Bean size: n={len(_ids)}  mean_area={mean_bean_area_px:.0f}px²  equiv_diam={mean_bean_diam_px:.1f}px", flush=True)

# ── 6. Save JSON ──────────────────────────────────────────────────────────────
results_b = {
    bid: {"agtron": round(float(agtron_vals_b[i]), 1), "class": classify(agtron_vals_b[i])}
    for i, bid in enumerate(bean_ids)
}

with open(os.path.join(SESSION_DIR, "agtron_result.json"), "w") as f:
    json.dump({
        "mean_agtron":        round(mean_agtron, 1),
        "mean_agtron_modeA":  round(mean_agtron, 1),    # 850+930nm (DiFluid-aligned)
        "mean_agtron_modeB":  round(mean_agtron_b, 1),  # 850-930nm broad avg
        "has_white_ref":      has_white,
        "has_flatfield":      has_flatfield,
        "has_calibration":    calibration is not None,
        "cal_formula":        cal_formula,
        "mean_ndiff_raw":     round(mean_ndiff_raw, 3),
        "mean_bean_area_px":  round(mean_bean_area_px, 1),
        "mean_bean_diam_px":  round(mean_bean_diam_px, 1),
        "beans":              results,
        "beans_modeB":        results_b,
    }, f, indent=2)

# ── 6. Visualization ──────────────────────────────────────────────────────────
# Generate at display resolution (500×480) so text is readable without scaling.
DISP_W, DISP_H = 500, 480

lmap_path = os.path.join(SESSION_DIR, "beans_labelmap.png")
if not os.path.exists(lmap_path):
    print("[agtron] beans_labelmap.png not found — skipping visualization", flush=True)
    sys.exit(0)

labelmap_full = cv2.imread(lmap_path, cv2.IMREAD_GRAYSCALE)

# Resize labelmap with INTER_NEAREST to preserve integer bean IDs
labelmap = cv2.resize(labelmap_full, (DISP_W, DISP_H), interpolation=cv2.INTER_NEAREST)

# Background: prefer 2500us gray, then 1250us bg, then blank
bg = None
for gn in ["capture_2500us_gray.png", "background_1250us.png", "capture_spec_5000us_gray.png"]:
    p = os.path.join(SESSION_DIR, gn)
    if os.path.exists(p):
        bg = cv2.imread(p)
        break

if bg is None or bg.size == 0:
    bg = np.zeros((DISP_H, DISP_W, 3), dtype=np.uint8)
else:
    if len(bg.shape) == 2:
        bg = cv2.cvtColor(bg, cv2.COLOR_GRAY2BGR)
    bg = cv2.resize(bg, (DISP_W, DISP_H), interpolation=cv2.INTER_AREA)

vis = (bg * 0.55).astype(np.uint8)

for i, bid in enumerate(bean_ids):
    mask = (labelmap == bid).astype(np.uint8) * 255
    if mask.sum() == 0:
        continue
    av    = agtron_vals[i]
    color = agtron_color(av)

    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(vis, cnts, -1, color, 3, cv2.LINE_AA)

    M = cv2.moments(mask)
    if M["m00"] > 0:
        cx = int(M["m10"] / M["m00"])
        cy = int(M["m01"] / M["m00"])
        lbl = f"{av:.0f}"
        fs  = 0.42
        (tw, th), _ = cv2.getTextSize(lbl, cv2.FONT_HERSHEY_SIMPLEX, fs, 1)
        tx, ty = cx - tw // 2, cy + th // 2
        cv2.rectangle(vis, (tx - 2, ty - th - 2), (tx + tw + 2, ty + 2), (0, 0, 0), -1)
        cv2.putText(vis, lbl, (tx, ty), cv2.FONT_HERSHEY_SIMPLEX, fs,
                    (255, 255, 255), 1, cv2.LINE_AA)

# Title bar
cal_tag   = "[Cal]" if calibration else "[Est]"
white_tag = "[FF]"  if has_flatfield else ("[W]" if has_white else "[rel]")
title = f"Agtron {white_tag}{cal_tag}  A:{mean_agtron:.0f}  B:{mean_agtron_b:.0f} ({classify(mean_agtron)})"
cv2.putText(vis, title, (8, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.44, (220, 220, 220), 1, cv2.LINE_AA)

out = os.path.join(SESSION_DIR, "agtron_labeled.png")
cv2.imwrite(out, vis)
print(f"[agtron] → {out}", flush=True)

# ── 7. Histogram ──────────────────────────────────────────────────────────────
if FAST_MODE:
    print("[agtron] --fast: skipping charts", flush=True)
    sys.exit(0)

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

HIST_BINS   = ['<35', '35-45', '45-55', '55-65', '65-75', '75-85', '≥85']
HIST_COLORS = ['#7c3b8c', '#c93c35', '#d96022', '#d99c22', '#5aab30', '#38b860', '#28c8a0']
HIST_EDGES  = [0, 35, 45, 55, 65, 75, 85, 100]

counts = [0] * 7
for av in agtron_vals:
    for i in range(6, -1, -1):
        if av >= HIST_EDGES[i]:
            counts[i] += 1
            break

total = len(agtron_vals)
pcts  = [c / total * 100.0 if total > 0 else 0.0 for c in counts]
std_agtron = float(np.std(agtron_vals))

fig, ax = plt.subplots(figsize=(6, 3.2), facecolor='#1a1a2e')
ax.set_facecolor('#1a1a2e')

bars = ax.bar(range(7), pcts, color=HIST_COLORS, edgecolor='white', linewidth=0.8, width=0.75)
for bar, pct in zip(bars, pcts):
    if pct > 0:
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.4,
                f'{pct:.0f}%', ha='center', va='bottom',
                color='white', fontsize=9, fontweight='bold')

ax.set_xticks(range(7))
ax.set_xticklabels(HIST_BINS, color='#cccccc', fontsize=9)
ax.yaxis.set_visible(False)
ax.spines['bottom'].set_color('#555577')
ax.spines['left'].set_visible(False)
ax.spines['top'].set_visible(False)
ax.spines['right'].set_visible(False)
ax.set_ylim(0, max(pcts) * 1.25 + 3 if pcts else 30)

cal_tag2   = "[Cal]" if calibration else "[Est]"
white_tag2 = "[FF]"  if has_flatfield else ("[W]" if has_white else "[rel]")
ax.set_title(f'Agtron Distribution  {white_tag2}{cal_tag2}', color='#dddddd', fontsize=10, pad=6)

ax.text(0.01, 0.97, f'Mean: {mean_agtron:.0f}', transform=ax.transAxes,
        color='#f5c842', fontsize=10, fontweight='bold', va='top')
ax.text(0.99, 0.97, f'SD: {std_agtron:.1f}', transform=ax.transAxes,
        color='#6ab4f0', fontsize=10, fontweight='bold', va='top', ha='right')

fig.subplots_adjust(left=0.04, right=0.97, top=0.88, bottom=0.18)
hist_out = os.path.join(SESSION_DIR, "agtron_histogram.png")
fig.savefig(hist_out, dpi=130, facecolor='#1a1a2e')
plt.close(fig)
print(f"[agtron] → {hist_out}", flush=True)

# ── 8. Arc gauge (DiFluid style) ─────────────────────────────────────────────
# DiFluid COMMON roast classification
def classify_common(v):
    if v <= 30: return "Espresso"
    if v <= 40: return "French"
    if v <= 50: return "Full City"
    if v <= 60: return "City"
    if v <= 70: return "Dark"
    if v <= 80: return "Medium"
    if v <= 90: return "Cinnamon"
    return "Light"

def arc_color(v):
    """Orange→yellow gradient based on Agtron value."""
    t = np.clip((v - 30) / 70.0, 0, 1)   # 30=dark end, 100=light end
    r = int(210 + 45 * t)
    g = int(100 + 120 * t)
    b = int(20)
    return (r/255, g/255, b/255)

BG_COLOR  = '#0d1117'
CARD_COLOR = '#161b22'

fig2 = plt.figure(figsize=(5.0, 4.0), facecolor=BG_COLOR)
ax2  = fig2.add_axes([0, 0, 1, 1])
ax2.set_facecolor(BG_COLOR)
ax2.set_xlim(-1.6, 1.6)
ax2.set_ylim(-1.4, 1.4)
ax2.set_aspect('equal')
ax2.axis('off')

# Arc parameters: 225° → -45° clockwise (270° sweep), Agtron 0→100
ARC_START = 225   # degrees (bottom-left)
ARC_SWEEP = 270   # total sweep
AGTRON_MIN, AGTRON_MAX = 0, 100
R_OUTER, R_INNER = 0.92, 0.65

def draw_arc(ax, r_out, r_in, theta1, theta2, color, n=200):
    """Draw a filled arc annulus segment."""
    t = np.linspace(np.radians(theta1), np.radians(theta2), n)
    xs = np.concatenate([r_out*np.cos(t), r_in*np.cos(t[::-1])])
    ys = np.concatenate([r_out*np.sin(t), r_in*np.sin(t[::-1])])
    ax2.fill(xs, ys, color=color, zorder=2)

# 1. Track (inactive) — full arc in dark gray
theta_start_rad = ARC_START
theta_end_rad   = ARC_START - ARC_SWEEP
draw_arc(ax2, R_OUTER, R_INNER, theta_end_rad, theta_start_rad, '#2a2f3a')

# 2. Active arc — filled up to current Agtron value
val_clamped = float(np.clip(mean_agtron if np.isfinite(mean_agtron) else 0.0, AGTRON_MIN, AGTRON_MAX))
fill_frac   = (val_clamped - AGTRON_MIN) / (AGTRON_MAX - AGTRON_MIN)
fill_sweep  = fill_frac * ARC_SWEEP
theta_fill  = ARC_START - fill_sweep
n_seg       = max(3, int(fill_sweep * 3))

# Gradient: draw segments with varying color
if fill_sweep > 1:
    for k in range(n_seg):
        t0 = ARC_START - (k / n_seg) * fill_sweep
        t1 = ARC_START - ((k+1) / n_seg) * fill_sweep
        frac = (k + 0.5) / n_seg
        v_seg = AGTRON_MIN + frac * (val_clamped - AGTRON_MIN)
        draw_arc(ax2, R_OUTER, R_INNER, t1, t0, arc_color(v_seg))

# 3. Center dark circle
circle = plt.Circle((0, 0), R_INNER - 0.02, color=CARD_COLOR, zorder=3)
ax2.add_patch(circle)

# 4. Agtron value — center large
ax2.text(0, 0.13, f'{mean_agtron:.1f}', ha='center', va='center',
         fontsize=34, color='white', fontweight='bold', zorder=5)
ax2.text(0, -0.13, 'Agtron', ha='center', va='center',
         fontsize=11, color='#888888', zorder=5)

# 5. Roast name — bottom of circle
roast_name = classify_common(mean_agtron)
ax2.text(0, -0.40, roast_name, ha='center', va='center',
         fontsize=13, color='#f5a623', fontweight='bold', zorder=5)

# 6. n beans + ratio at bottom corners
ratio_str = f'{mean_ndiff_raw:.1f}%' if mean_ndiff_raw else ''
ax2.text(-1.45, -1.20, f'n={total}', ha='left', va='bottom',
         fontsize=9, color='#666677', zorder=5)
ax2.text(1.45, -1.20, f'ndiff: {mean_ndiff_raw:.2f}', ha='right', va='bottom',
         fontsize=9, color='#666677', zorder=5)

# 7. Scale ticks at 0, 25, 50, 75, 100
for tick_val in [0, 25, 50, 75, 100]:
    frac  = (tick_val - AGTRON_MIN) / (AGTRON_MAX - AGTRON_MIN)
    angle = np.radians(ARC_START - frac * ARC_SWEEP)
    x0 = (R_OUTER + 0.03) * np.cos(angle)
    y0 = (R_OUTER + 0.03) * np.sin(angle)
    x1 = (R_OUTER + 0.12) * np.cos(angle)
    y1 = (R_OUTER + 0.12) * np.sin(angle)
    ax2.plot([x0, x1], [y0, y1], color='#555566', lw=1, zorder=4)
    ax2.text((R_OUTER + 0.20) * np.cos(angle), (R_OUTER + 0.20) * np.sin(angle),
             str(tick_val), ha='center', va='center', fontsize=7, color='#555566', zorder=5)

# 8. Title
ax2.text(0, 1.28, f'Roast  (COMMON)',
         ha='center', va='top', fontsize=11, color='#aaaaaa', zorder=5)
ax2.text(0, 1.10, f'{cal_tag2}{white_tag2}',
         ha='center', va='top', fontsize=8, color='#555566', zorder=5)

fig2.savefig(os.path.join(SESSION_DIR, "agtron_piechart.png"),
             dpi=110, bbox_inches='tight', facecolor=BG_COLOR)
plt.close(fig2)
print(f"[agtron] → {os.path.join(SESSION_DIR, 'agtron_piechart.png')}", flush=True)
