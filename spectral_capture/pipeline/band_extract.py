"""
Utilities for VNIR 10-band cube parsing and batch feature extraction.

The C++ SDK tool writes a small binary format:
  [n_bands:uint32 LE][width:uint32 LE][height:uint32 LE][dtype:uint32 LE=4]
  [float32 band data in band-first order: n_bands x height x width]

Band order for Phase 1:
  B1 350-410 nm, B2 410-470 nm, B3 470-530 nm, B4 530-590 nm,
  B5 590-650 nm, B6 650-710 nm, B7 710-770 nm, B8 770-830 nm,
  B9 830-890 nm, B10 890-950 nm.
"""

from __future__ import annotations

import struct
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

SUBHEADER_FMT = "<IIII"
SUBHEADER_SIZE = struct.calcsize(SUBHEADER_FMT)
DTYPE_FLOAT32_BYTES = 4


class BandCubeFormatError(ValueError):
    pass


def load_band_cube(path: str | Path) -> np.ndarray:
    """Load a VNIR binary cube as shape (10, height, width), dtype float32."""
    data = Path(path).read_bytes()
    return parse_band_cube(data)


def parse_band_cube(data: bytes) -> np.ndarray:
    """Parse the qs_to_bands binary payload into a band-first float32 cube."""
    if len(data) < SUBHEADER_SIZE:
        raise BandCubeFormatError(
            f"Data too short for sub-header: {len(data)} < {SUBHEADER_SIZE}"
        )

    n_bands, width, height, dtype_bytes = struct.unpack_from(SUBHEADER_FMT, data, 0)
    if dtype_bytes != DTYPE_FLOAT32_BYTES:
        raise BandCubeFormatError(
            f"Unsupported dtype byte width: {dtype_bytes} (expected 4 = float32)"
        )
    if n_bands != len(BAND_RANGES_NM):
        raise BandCubeFormatError(
            f"Unexpected band count: {n_bands} (expected {len(BAND_RANGES_NM)})"
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
    """
    Return an n_beans x 10 float32 array of per-band means inside each bbox.

    Boxes are [x, y, w, h]. If box_frame_size is provided, bbox coordinates are
    scaled from that frame size to the cube's width and height.
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
        x0 = int(np.floor(x * sx))
        y0 = int(np.floor(y * sy))
        x1 = int(np.ceil((x + w) * sx))
        y1 = int(np.ceil((y + h) * sy))
        x0 = max(0, min(width, x0))
        y0 = max(0, min(height, y0))
        x1 = max(0, min(width, x1))
        y1 = max(0, min(height, y1))
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
    if arr.ndim != 2 or arr.shape[1] != len(BAND_RANGES_NM):
        raise ValueError(
            f"bean_band_means must have shape (n, {len(BAND_RANGES_NM)}), got {arr.shape}"
        )

    valid = arr[~np.isnan(arr).any(axis=1)]
    if valid.size:
        band_mean = valid.mean(axis=0, dtype=np.float64)
        band_std = valid.std(axis=0, dtype=np.float64)
    else:
        band_mean = np.full(len(BAND_RANGES_NM), np.nan, dtype=np.float64)
        band_std = np.full(len(BAND_RANGES_NM), np.nan, dtype=np.float64)

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
    bean_means = compute_bean_band_means(
        cube, boxes_list, box_frame_size=box_frame_size
    )
    aggregate = aggregate_batch_features(bean_means, boxes_list)
    aggregate["per_bean_band_mean"] = bean_means.tolist()
    return aggregate


def _validate_cube(cube: np.ndarray) -> np.ndarray:
    arr = np.asarray(cube, dtype=np.float32)
    if arr.ndim != 3 or arr.shape[0] != len(BAND_RANGES_NM):
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
