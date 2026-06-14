import struct
import sys
import tempfile
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from spectral_capture.spectral.band_extract import (
    BandCubeFormatError,
    DEFAULT_MOSAIC_LAYOUT,
    N_BANDS,
    QS_HEADER_SIZE,
    RAW_HEIGHT,
    RAW_WIDTH,
    compute_bean_band_means,
    extract_bands,
    extract_batch_features,
    load_qs,
    parse_band_cube,
)


def _make_cube_bytes(width: int, height: int, per_band_fill) -> bytes:
    header = struct.pack("<IIII", N_BANDS, width, height, 4)
    cube = np.empty((N_BANDS, height, width), dtype="<f4")
    for b in range(N_BANDS):
        cube[b] = per_band_fill(b)
    return header + cube.tobytes()


# ── PRIMARY PATH: SDK band cube ──────────────────────────────────────────────

def test_parse_band_cube_roundtrips_shape_dtype_and_values():
    data = _make_cube_bytes(4, 3, lambda b: float(b))
    cube = parse_band_cube(data)
    assert cube.shape == (N_BANDS, 3, 4)
    assert cube.dtype == np.float32
    for b in range(N_BANDS):
        np.testing.assert_allclose(cube[b], float(b))


def test_parse_band_cube_rejects_wrong_band_count_and_size():
    bad_bands = struct.pack("<IIII", 9, 2, 2, 4) + b"\x00" * (9 * 2 * 2 * 4)
    with pytest.raises(BandCubeFormatError):
        parse_band_cube(bad_bands)
    truncated = _make_cube_bytes(4, 3, lambda b: float(b))[:-8]
    with pytest.raises(BandCubeFormatError):
        parse_band_cube(truncated)


def test_compute_bean_band_means_scales_bboxes_to_cube():
    cube = np.zeros((N_BANDS, 6, 8), dtype=np.float32)
    for b in range(N_BANDS):
        cube[b] = b * 10 + np.arange(48, dtype=np.float32).reshape(6, 8)
    # detector frame is 2x the cube; bbox [4,6,8,6] -> cube region [2:6, 3:6]
    means = compute_bean_band_means(cube, [[4, 6, 8, 6]], box_frame_size=(16, 12))
    roi = cube[:, 3:6, 2:6]
    assert means.shape == (1, N_BANDS)
    np.testing.assert_allclose(means[0], roi.mean(axis=(1, 2)))


def test_compute_bean_band_means_out_of_frame_box_is_nan():
    cube = np.ones((N_BANDS, 4, 4), dtype=np.float32)
    means = compute_bean_band_means(cube, [[100, 100, 5, 5]])
    assert means.shape == (1, N_BANDS)
    assert np.isnan(means[0]).all()


def test_extract_batch_features_aggregates_bands_and_geometry():
    cube = np.zeros((N_BANDS, 4, 4), dtype=np.float32)
    for b in range(N_BANDS):
        cube[b] = float(b + 1)
    feats = extract_batch_features(cube, [[0, 0, 2, 2], [1, 1, 2, 2]])
    assert feats["bean_count"] == 2
    assert feats["valid_bean_count"] == 2
    np.testing.assert_allclose(feats["band_mean"], [b + 1 for b in range(N_BANDS)])
    np.testing.assert_allclose(feats["band_std"], [0.0] * N_BANDS)
    assert feats["bbox_area_median"] == 4.0
    assert len(feats["per_bean_band_mean"]) == 2


# ── SMOKE-TEST EXTENSION: raw mosaic de-tile (dev only) ──────────────────────

def test_smoke_test_load_qs_and_extract_bands_shape():
    raw = np.arange(RAW_HEIGHT * RAW_WIDTH, dtype=np.uint16).reshape(RAW_HEIGHT, RAW_WIDTH)
    with tempfile.TemporaryDirectory() as tmp:
        qs_path = Path(tmp) / "sample.qs"
        qs_path.write_bytes(b"LLSQ" + b"\x00" * (QS_HEADER_SIZE - 4) + raw.astype("<u2").tobytes())
        loaded = load_qs(qs_path)
    assert loaded.shape == (RAW_HEIGHT, RAW_WIDTH)
    bands = extract_bands(loaded, DEFAULT_MOSAIC_LAYOUT)
    assert bands.shape == (N_BANDS, RAW_HEIGHT // 2, RAW_WIDTH // 5)
    assert bands.dtype == np.float32


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
