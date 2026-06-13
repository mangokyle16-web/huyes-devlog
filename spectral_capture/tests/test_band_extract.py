import tempfile
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from spectral_capture.spectral.band_extract import (
    DEFAULT_MOSAIC_LAYOUT,
    QS_HEADER_SIZE,
    RAW_HEIGHT,
    RAW_WIDTH,
    extract_bands,
    load_qs,
    per_bean_spectra,
)


def _write_qs(path: Path, raw: np.ndarray) -> None:
    path.write_bytes(b"LLSQ" + b"\x00" * (QS_HEADER_SIZE - 4) + raw.astype("<u2").tobytes())


def test_load_qs_reads_llsq_payload_as_1600x1200_uint16():
    raw = np.arange(RAW_HEIGHT * RAW_WIDTH, dtype=np.uint16).reshape(RAW_HEIGHT, RAW_WIDTH)
    with tempfile.TemporaryDirectory() as tmp:
        qs_path = Path(tmp) / "sample.qs"
        _write_qs(qs_path, raw)

        loaded = load_qs(qs_path)

    assert loaded.dtype == np.uint16
    assert loaded.shape == (RAW_HEIGHT, RAW_WIDTH)
    assert int(loaded[0, 0]) == 0
    assert int(loaded[-1, -1]) == int(raw[-1, -1])


def test_extract_bands_uses_configurable_mosaic_offsets():
    raw = np.zeros((RAW_HEIGHT, RAW_WIDTH), dtype=np.uint16)
    for band_index, offset in enumerate(DEFAULT_MOSAIC_LAYOUT.offsets):
        dy, dx = offset
        raw[dy :: DEFAULT_MOSAIC_LAYOUT.period_y, dx :: DEFAULT_MOSAIC_LAYOUT.period_x] = (
            100 + band_index
        )

    bands = extract_bands(raw)

    assert bands.shape == (10, RAW_HEIGHT // 2, RAW_WIDTH // 5)
    assert bands.dtype == np.float32
    for band_index in range(10):
        np.testing.assert_allclose(bands[band_index], 100 + band_index)


def test_per_bean_spectra_scales_bboxes_and_returns_mean_and_std_per_band():
    bands = np.zeros((10, 6, 8), dtype=np.float32)
    for band_index in range(10):
        bands[band_index] = band_index * 10 + np.arange(48, dtype=np.float32).reshape(6, 8)

    spectra = per_bean_spectra(
        bands,
        [[4, 6, 8, 6]],
        source_shape=(12, 16),
    )

    roi = bands[:, 3:6, 2:6]
    assert len(spectra) == 1
    np.testing.assert_allclose(spectra[0]["mean"], roi.mean(axis=(1, 2)))
    np.testing.assert_allclose(spectra[0]["std"], roi.std(axis=(1, 2)))
    assert spectra[0]["bbox"] == [4.0, 6.0, 8.0, 6.0]


if __name__ == "__main__":
    test_load_qs_reads_llsq_payload_as_1600x1200_uint16()
    test_extract_bands_uses_configurable_mosaic_offsets()
    test_per_bean_spectra_scales_bboxes_and_returns_mean_and_std_per_band()
