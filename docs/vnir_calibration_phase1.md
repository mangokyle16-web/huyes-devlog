# VNIR Calibration Phase 1

Offline tooling that produces one batch-level calibration row per counted batch.
It does **not** touch the detector, tracker, or live preview/counting path.

Canonical module: `spectral_capture/spectral/` (`band_extract.py`, `calib_logger.py`).

## Band extraction — two paths

**Primary (SDK cube, gate-validated).** The C++ helper
`spectral_capture/capture/qs_to_bands.cpp` runs the QS SDK
(`qsToQsi` / `qsiToGray` Fabry-Perot spectral inversion) and writes a band-cube
binary (`/dev/shm/vnir_bands.bin` by default):

```text
[n_bands:u32 LE][width:u32 LE][height:u32 LE][dtype:u32 LE=4]
[float32 band-first data: n_bands x height x width]
```

Phase 1 gate (2026-06-14) confirmed `specBegin/specEnd = 350/950 nm` and ten
distinct 60 nm bands (`outRange` 10/10), so this cube's band identity is trusted.
Build/run the helper on the Pi5 (SDK is linux-arm64):

```bash
qs_to_bands camera_new.qsbs db_std.qsdb frame.qs /dev/shm/vnir_bands.bin 100
```

`band_extract.parse_band_cube()` / `load_band_cube()` read it, and
`extract_batch_features()` aggregates batch-level VNIR + bbox features.

**Smoke-test extension (dev only, NOT spectrally valid).** `load_qs()` +
`extract_bands()` de-tile the raw mosaic into a `(10, H, W)` array just to
exercise the pipeline / produce a montage when no SDK cube is available. The
physical mosaic is 3x3 (9 filters) and the de-tile band identity is wrong — it
must never be fed into calibration. The logger only accepts SDK cubes.

## Calibration row logging

After a batch is counted, append a row from the SDK cube plus the live
detection / count snapshots, then fill in the scale weight when you have it:

```bash
# append a pending row (true_weight_g = null)
python3 -m spectral_capture.spectral.calib_logger append \
  --cube /dev/shm/vnir_bands.bin \
  --detect-json /dev/shm/bean_detect.json \
  --count-status /dev/shm/count_status.json \
  --box-frame-width 1600 --box-frame-height 1200

# later, record the kitchen-scale weight for that batch
python3 -m spectral_capture.spectral.calib_logger set-weight 20260613_153012 61.2
```

Rows append to `data/calibration/vnir_calib.jsonl`. Each row:

```json
{
  "schema_version": 1,
  "batch_id": "...",
  "timestamp": "...",
  "count": 403,
  "true_weight_g": null,
  "spectral_features": {"band_ranges_nm": [...], "band_mean": [...10...], "band_std": [...10...], "valid_bean_count": 0},
  "bbox_geometry": {"bean_count": 0, "bbox_width_mean": null, "bbox_area_median": null, "...": null},
  "source": {"cube_path": "...", "cube_shape": [10, H, W], "...": null}
}
```

`count` + `true_weight_g` + `bbox_geometry` also cover 提案14 (定量分裝) needs:
per-batch `g_per_bean = true_weight_g / count` and bbox size features.
