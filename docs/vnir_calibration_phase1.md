# VNIR Calibration Phase 1

Phase 1 adds offline tooling for one calibration row per counted batch. It does
not change the detector, tracker, or live counting path.

## 10-band extraction

Preferred extraction uses the vendor SDK helper in
`spectral_capture/capture/qs_to_bands.cpp`, which calls `qsToQsi()` and
`qsiToGray()` for these 10 requested bands:

```text
B1 350-410 nm  B2 410-470 nm  B3 470-530 nm  B4 530-590 nm  B5 590-650 nm
B6 650-710 nm  B7 710-770 nm  B8 770-830 nm  B9 830-890 nm  B10 890-950 nm
```

When SDK paths are unavailable, Python falls back to a configurable raw mosaic
de-tile. The default `5x2` row-major layout is a hypothesis only; verify it with
a known color/NIR target before trusting band identity.

Sanity-check one `.qs` frame and write a montage:

```bash
python3 -m spectral_capture.spectral.band_extract /path/to/sample.qs
```

Use the SDK helper when built and calibration files are available:

```bash
python3 -m spectral_capture.spectral.band_extract /path/to/sample.qs \
  --sdk-tool /home/kyle/KyleClaude/spectral_capture/capture/qs_to_bands \
  --qsbs /home/kyle/KyleClaude/camera_new.qsbs \
  --qsdb /home/kyle/KyleClaude/db_std.qsdb
```

## Calibration Row Logging

After a batch is finalized, provide the saved batch JSON, manual scale weight,
and a representative `.qs` frame:

```bash
python3 -m spectral_capture.spectral.calib_logger \
  --batch /home/kyle/KyleClaude/spectral_capture/data/batches/batch_20260613_153012.json \
  --weight 61.2 \
  --qs /home/kyle/KyleClaude/spectral_capture/data/captures/20260613_153012/frame_000123.qs
```

If the capture pipeline has not copied a frame into `data/captures/<batch>/`,
use `/dev/shm/qs_latest.qs` immediately after finalize as the representative QS
source. The CLI picks the batch frame with the most boxes unless `--frame-id` is
provided.

Rows append to:

```text
/home/kyle/KyleClaude/spectral_capture/data/calibration/calib_dataset.jsonl
```

Each row includes `schema_version`, `batch_id`, `timestamp`, `count`,
`g_per_bean_observed`, 10-element `band_mean`, 10-element `band_std`, bbox
geometry mean/median fields, and `scale_weight_g`.
