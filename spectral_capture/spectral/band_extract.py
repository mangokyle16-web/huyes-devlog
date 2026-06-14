"""VNIR 10-band feature extraction for CM020D Phase 1 calibration.

PRIMARY PATH — SDK cube (gate-validated, the only spectrally-trustworthy path):
    The C++ helper ``spectral_capture/capture/qs_to_bands.cpp`` runs the QS SDK
    (``qsToQsi`` / ``qsiToGray`` Fabry-Perot spectral inversion) on a ``.qs``
    frame and writes a small band-cube binary::

        [n_bands:u32 LE][width:u32 LE][height:u32 LE][dtype:u32 LE=4]
        [float32 band-first data: n_bands x height x width]

    Use ``load_band_cube()`` / ``parse_band_cube()`` to read it, then
    ``extract_batch_features()`` to aggregate batch-level VNIR + bbox features.
    Phase 1 gate (2026-06-14) confirmed specBegin/specEnd = 350/950 nm and ten
    distinct 60 nm bands, so this cube's band identity is trustworthy.

SMOKE-TEST EXTENSION — raw mosaic de-tile (DEV ONLY, NOT spectrally valid):
    ``load_qs()`` + ``extract_bands()`` de-tile the raw mosaic into a
    ``(10, H, W)`` array so the downstream pipeline / montage can be exercised
    without a real SDK cube. The physical mosaic is 3x3 (9 filters) and the band
    identity of any de-tile is WRONG — never feed this into calibration. The
    calibration logger only accepts SDK cubes.

Band order:
    B1 350-410, B2 410-470, B3 470-530, B4 530-590, B5 590-650,
    B6 650-710, B7 710-770, B8 770-830, B9 830-890, B10 890-950 nm.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np


BAND_RANGES_NM = (
    (350, 410),
    (410, 470),
    (470, 530),
    (530, 590),
    (590, 650),
    (650, 710),
    (710, 770),
    (770, 830),
    (830, 890),
    (890, 950),
)
N_BANDS = len(BAND_RANGES_NM)

SUBHEADER_FMT = "<IIII"
SUBHEADER_SIZE = struct.calcsize(SUBHEADER_FMT)
DTYPE_FLOAT32_BYTES = 4


class BandCubeFormatError(ValueError):
    """Raised when an SDK band-cube binary is malformed."""


# ─────────────────────────────────────────────────────────────────────────────
# PRIMARY PATH — SDK band cube
# ─────────────────────────────────────────────────────────────────────────────

def load_band_cube(path: str | Path) -> np.ndarray:
    """Load an SDK band-cube binary as shape ``(10, height, width)`` float32."""
    return parse_band_cube(Path(path).read_bytes())


def parse_band_cube(data: bytes) -> np.ndarray:
    """Parse the ``qs_to_bands`` binary payload into a band-first float32 cube."""
    if len(data) < SUBHEADER_SIZE:
        raise BandCubeFormatError(
            f"Data too short for sub-header: {len(data)} < {SUBHEADER_SIZE}"
        )

    n_bands, width, height, dtype_bytes = struct.unpack_from(SUBHEADER_FMT, data, 0)
    if dtype_bytes != DTYPE_FLOAT32_BYTES:
        raise BandCubeFormatError(
            f"Unsupported dtype byte width: {dtype_bytes} (expected 4 = float32)"
        )
    if n_bands != N_BANDS:
        raise BandCubeFormatError(
            f"Unexpected band count: {n_bands} (expected {N_BANDS})"
        )
    if width == 0 or height == 0:
        raise BandCubeFormatError(f"Invalid cube dimensions: width={width} height={height}")

    expected = SUBHEADER_SIZE + n_bands * width * height * DTYPE_FLOAT32_BYTES
    if len(data) != expected:
        raise BandCubeFormatError(
            f"Data size mismatch: got {len(data)}, expected {expected}"
        )

    cube = np.frombuffer(data, dtype="<f4", offset=SUBHEADER_SIZE)
    return np.ascontiguousarray(cube.reshape(n_bands, height, width))


def compute_bean_band_means(
    cube: np.ndarray,
    boxes: Iterable[Sequence[float]],
    *,
    box_frame_size: tuple[int, int] | None = None,
) -> np.ndarray:
    """Return an ``n_beans x 10`` float32 array of per-band means inside each bbox.

    Boxes are ``[x, y, w, h]``. If ``box_frame_size=(frame_w, frame_h)`` is given,
    bbox coordinates are scaled from that detector frame size to the cube's
    width/height before sampling. Boxes outside the cube yield a NaN row.
    """
    cube = _validate_cube(cube)
    n_bands, height, width = cube.shape
    sx = sy = 1.0
    if box_frame_size is not None:
        frame_w, frame_h = box_frame_size
        if frame_w <= 0 or frame_h <= 0:
            raise ValueError(f"Invalid box_frame_size: {box_frame_size}")
        sx = width / float(frame_w)
        sy = height / float(frame_h)

    means: list[np.ndarray] = []
    for box in boxes:
        if len(box) != 4:
            raise ValueError(f"Expected bbox [x, y, w, h], got {box!r}")
        x, y, w, h = [float(v) for v in box]
        x0 = max(0, min(width, int(np.floor(x * sx))))
        y0 = max(0, min(height, int(np.floor(y * sy))))
        x1 = max(0, min(width, int(np.ceil((x + w) * sx))))
        y1 = max(0, min(height, int(np.ceil((y + h) * sy))))
        if x1 <= x0 or y1 <= y0:
            means.append(np.full(n_bands, np.nan, dtype=np.float32))
            continue
        means.append(cube[:, y0:y1, x0:x1].mean(axis=(1, 2), dtype=np.float64))

    if not means:
        return np.empty((0, n_bands), dtype=np.float32)
    return np.asarray(means, dtype=np.float32)


def aggregate_batch_features(
    bean_band_means: np.ndarray,
    boxes: Iterable[Sequence[float]],
) -> dict:
    """Aggregate per-bean VNIR means and bbox geometry into one batch feature dict."""
    arr = np.asarray(bean_band_means, dtype=np.float32)
    if arr.ndim != 2 or arr.shape[1] != N_BANDS:
        raise ValueError(
            f"bean_band_means must have shape (n, {N_BANDS}), got {arr.shape}"
        )

    valid = arr[~np.isnan(arr).any(axis=1)]
    if valid.size:
        band_mean = valid.mean(axis=0, dtype=np.float64)
        band_std = valid.std(axis=0, dtype=np.float64)
    else:
        band_mean = np.full(N_BANDS, np.nan, dtype=np.float64)
        band_std = np.full(N_BANDS, np.nan, dtype=np.float64)

    geom = _geometry_stats(boxes)
    return {
        "bean_count": int(arr.shape[0]),
        "valid_bean_count": int(valid.shape[0]),
        "band_ranges_nm": [list(pair) for pair in BAND_RANGES_NM],
        "band_mean": _finite_or_none_list(band_mean),
        "band_std": _finite_or_none_list(band_std),
        **geom,
    }


def extract_batch_features(
    cube: np.ndarray,
    boxes: Iterable[Sequence[float]],
    *,
    box_frame_size: tuple[int, int] | None = None,
) -> dict:
    """Compute per-bean band means and aggregate them into batch-level features."""
    boxes_list = [list(box) for box in boxes]
    bean_means = compute_bean_band_means(cube, boxes_list, box_frame_size=box_frame_size)
    aggregate = aggregate_batch_features(bean_means, boxes_list)
    aggregate["per_bean_band_mean"] = bean_means.tolist()
    return aggregate


def _validate_cube(cube: np.ndarray) -> np.ndarray:
    arr = np.asarray(cube, dtype=np.float32)
    if arr.ndim != 3 or arr.shape[0] != N_BANDS:
        raise ValueError(f"cube must have shape (10, height, width), got {arr.shape}")
    return arr


def _geometry_stats(boxes: Iterable[Sequence[float]]) -> dict:
    box_arr = np.asarray([list(box) for box in boxes], dtype=np.float64)
    if box_arr.size == 0:
        return {
            "bbox_width_mean": None,
            "bbox_width_median": None,
            "bbox_height_mean": None,
            "bbox_height_median": None,
            "bbox_area_mean": None,
            "bbox_area_median": None,
        }
    if box_arr.ndim != 2 or box_arr.shape[1] != 4:
        raise ValueError(f"boxes must be an iterable of [x, y, w, h], got {box_arr.shape}")

    widths = np.maximum(0.0, box_arr[:, 2])
    heights = np.maximum(0.0, box_arr[:, 3])
    areas = widths * heights
    return {
        "bbox_width_mean": _finite_or_none(np.mean(widths)),
        "bbox_width_median": _finite_or_none(np.median(widths)),
        "bbox_height_mean": _finite_or_none(np.mean(heights)),
        "bbox_height_median": _finite_or_none(np.median(heights)),
        "bbox_area_mean": _finite_or_none(np.mean(areas)),
        "bbox_area_median": _finite_or_none(np.median(areas)),
    }


def _finite_or_none(value: float) -> float | None:
    value = float(value)
    return value if np.isfinite(value) else None


def _finite_or_none_list(values: np.ndarray) -> list[float | None]:
    return [_finite_or_none(v) for v in values]


# ─────────────────────────────────────────────────────────────────────────────
# SMOKE-TEST EXTENSION — raw mosaic de-tile (DEV ONLY, NOT spectrally valid)
#
# This exists ONLY to exercise the pipeline / produce a montage when no SDK cube
# is available. The de-tiled planes are NOT real spectral bands (physical mosaic
# is 3x3 = 9 filters; reconstructed spectrum needs the SDK). The calibration
# logger never calls this — keep it out of any calibration data path.
# ─────────────────────────────────────────────────────────────────────────────

RAW_WIDTH = 1600
RAW_HEIGHT = 1200
QS_MAGIC = b"LLSQ"
QS_HEADER_SIZE = 8
RAW_PAYLOAD_BYTES = RAW_WIDTH * RAW_HEIGHT * 2


@dataclass(frozen=True)
class MosaicLayout:
    """Configurable raw-mosaic de-tile (smoke-test only).

    ``offsets`` maps output plane index to a raw-pixel offset ``(dy, dx)`` sampled
    as ``raw[dy::period_y, dx::period_x]``.
    """

    period_y: int
    period_x: int
    offsets: tuple[tuple[int, int], ...]
    name: str = "smoke_test"

    def validate(self) -> None:
        if self.period_y <= 0 or self.period_x <= 0:
            raise ValueError("Mosaic periods must be positive")
        if len(self.offsets) != N_BANDS:
            raise ValueError(f"Expected {N_BANDS} offsets, got {len(self.offsets)}")


DEFAULT_MOSAIC_LAYOUT = MosaicLayout(
    period_y=2,
    period_x=5,
    offsets=tuple((dy, dx) for dy in range(2) for dx in range(5)),
    name="smoke_test_5x2_NOT_spectral",
)


def load_qs(path: str | Path) -> np.ndarray:
    """[smoke-test] Load a ``.qs`` payload as a ``(1200, 1600)`` uint16 mosaic.

    Assumes an 8-byte LLSQ header. Real captures may have a larger header, so
    this is for quick dev checks only — use the SDK cube path for anything real.
    """
    data = Path(path).read_bytes()
    if len(data) == RAW_PAYLOAD_BYTES:
        payload = data
    elif len(data) >= QS_HEADER_SIZE + RAW_PAYLOAD_BYTES and data[:4] == QS_MAGIC:
        payload = data[QS_HEADER_SIZE : QS_HEADER_SIZE + RAW_PAYLOAD_BYTES]
    else:
        raise ValueError(
            f"Unsupported QS file for smoke-test loader: {len(data)} bytes"
        )
    raw = np.frombuffer(payload, dtype="<u2", count=RAW_WIDTH * RAW_HEIGHT)
    return np.ascontiguousarray(raw.reshape(RAW_HEIGHT, RAW_WIDTH))


def extract_bands(raw: np.ndarray, layout: MosaicLayout = DEFAULT_MOSAIC_LAYOUT) -> np.ndarray:
    """[smoke-test] De-tile a raw mosaic into a ``(10, H, W)`` float32 array.

    NOT spectrally valid. For pipeline exercise / montage only.
    """
    layout.validate()
    raw_arr = np.asarray(raw)
    if raw_arr.ndim != 2:
        raise ValueError(f"raw must be a 2D array, got shape {raw_arr.shape}")
    min_h = min((raw_arr.shape[0] - dy + layout.period_y - 1) // layout.period_y for dy, _ in layout.offsets)
    min_w = min((raw_arr.shape[1] - dx + layout.period_x - 1) // layout.period_x for _, dx in layout.offsets)
    if min_h <= 0 or min_w <= 0:
        raise ValueError(f"raw shape {raw_arr.shape} too small for {layout.name}")
    bands = np.empty((N_BANDS, min_h, min_w), dtype=np.float32)
    for i, (dy, dx) in enumerate(layout.offsets):
        bands[i] = raw_arr[dy :: layout.period_y, dx :: layout.period_x][:min_h, :min_w]
    return bands


def save_montage(cube: np.ndarray, path: str | Path) -> Path:
    """[smoke-test] Save a 2x5 grayscale PGM montage of a 10-band cube."""
    cube = _validate_cube(cube)
    tiles = [_normalize_u8(cube[i]) for i in range(N_BANDS)]
    montage = np.concatenate(
        [np.concatenate(tiles[:5], axis=1), np.concatenate(tiles[5:], axis=1)], axis=0
    )
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    header = f"P5\n# VNIR 10-band montage B1-B10 (smoke-test)\n{montage.shape[1]} {montage.shape[0]}\n255\n"
    out.write_bytes(header.encode("ascii") + montage.tobytes())
    return out


def _normalize_u8(plane: np.ndarray) -> np.ndarray:
    arr = np.asarray(plane, dtype=np.float32)
    lo = float(np.nanpercentile(arr, 1))
    hi = float(np.nanpercentile(arr, 99))
    if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
        return np.zeros(arr.shape, dtype=np.uint8)
    scaled = (np.clip(arr, lo, hi) - lo) * (255.0 / (hi - lo))
    return scaled.astype(np.uint8)
