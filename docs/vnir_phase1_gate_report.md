# VNIR Phase 1 Gate Report — 60nm Band Validation

**Date:** 2026-06-14  
**QSBS:** /home/kyle/KyleClaude/camera_new.qsbs  
**QSDB:** /home/kyle/KyleClaude/db_std.qsdb  
**White ref:** /home/kyle/KyleClaude/white_flatfield_BAD_flat_surface.qs  
**Bean frame:** /home/kyle/KyleClaude/spectral_capture/data/captures/20260607-001/frame_000085.qs  

## 1. SDK Spectral Range

| Parameter | Value |
|---|---|
| specBegin | 350 nm |
| specEnd   | 950 nm |
| STEP      | 60 nm |
| INTRICACY | 100 |
| lightSrc  | idx=9 (QS_MD_LED) |
| bands generated | 10 |

**Proposal assumption:** 350–950nm / 10 bands.  
**Actual:** 350–950nm / 10 bands.  
**Band start offset:** 0 nm (exact match).

## 2. Band Mapping & outRange Verification

| # | Requested [nm] | SDK outRange [nm] | Match? |
|---|---|---|---|
| 1 | [350, 410] | [350, 410] | YES |
| 2 | [410, 470] | [410, 470] | YES |
| 3 | [470, 530] | [470, 530] | YES |
| 4 | [530, 590] | [530, 590] | YES |
| 5 | [590, 650] | [590, 650] | YES |
| 6 | [650, 710] | [650, 710] | YES |
| 7 | [710, 770] | [710, 770] | YES |
| 8 | [770, 830] | [770, 830] | YES |
| 9 | [830, 890] | [830, 890] | YES |
| 10 | [890, 950] | [890, 950] | YES |

**All outRange matched:** YES

## 3. Per-Band Signal Statistics (bean frame, flat-field corrected)

Flat-field correction: applied  

| # | Band [nm] | mean | std | non-zero? | has-std? |
|---|---|---|---|---|---|
| 1 | [350,410] | 0.216146 | 0.366178 | YES | YES |
| 2 | [410,470] | 0.274230 | 0.319173 | YES | YES |
| 3 | [470,530] | 0.414725 | 0.333333 | YES | YES |
| 4 | [530,590] | 0.402944 | 0.325096 | YES | YES |
| 5 | [590,650] | 0.233420 | 0.214327 | YES | YES |
| 6 | [650,710] | 0.167695 | 0.156224 | YES | YES |
| 7 | [710,770] | 0.144190 | 0.124873 | YES | YES |
| 8 | [770,830] | 0.104026 | 0.095285 | YES | YES |
| 9 | [830,890] | 0.088975 | 0.101345 | YES | YES |
| 10 | [890,950] | 0.085204 | 0.161448 | YES | YES |

## 4. Band Distinguishability

Adjacent band mean differences (flat-field corrected, normalised to maxMean):

| Pair | |ΔmeanFF| | |ΔmeanFF|/maxMean | Distinguishable? |
|---|---|---|---|
| B1→B2 | 0.058083 | 0.140053 | YES |
| B2→B3 | 0.140495 | 0.338768 | YES |
| B3→B4 | 0.011781 | 0.028408 | YES |
| B4→B5 | 0.169524 | 0.408762 | YES |
| B5→B6 | 0.065725 | 0.158478 | YES |
| B6→B7 | 0.023505 | 0.056675 | YES |
| B7→B8 | 0.040164 | 0.096845 | YES |
| B8→B9 | 0.015051 | 0.036292 | YES |
| B9→B10 | 0.003771 | 0.009092 | YES |

## 5. Channel PNG Saved

- `gate_chan380nm.png`
- `gate_chan440nm.png`
- `gate_chan500nm.png`
- `gate_chan560nm.png`
- `gate_chan620nm.png`
- `gate_chan680nm.png`
- `gate_chan740nm.png`
- `gate_chan800nm.png`
- `gate_chan860nm.png`
- `gate_chan920nm.png`

## 6. GO / NO-GO

| Criterion | Result |
|---|---|
| All bands non-zero mean | PASS |
| All bands have std > 0  | PASS |
| outRange matches request| PASS |
| Adjacent bands distinct | PASS |

### **VERDICT: GO**

60nm / 10-band sampling validated. Ready to proceed to Phase 2.
