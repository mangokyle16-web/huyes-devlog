"""VNIR 10-band extraction helpers for CM020D `.qs` frames.

Preferred path:
    The vendor SDK exposes qsToQsi() / qsiToGray(), which can return the exact
    requested 10 spectral band planes. This repository already has a C++ helper
    (`spectral_capture/capture/qs_to_bands.cpp`) that calls:

        qsToQsi(..., bandRange={{350,410},...,{890,950}}, bandNum=10)
        qsiToGray(...)

    and writes a float32 cube with shape (10, H, W). Use that helper whenever
    SDK calibration files are available.

Fallback path:
    Pure Python can only de-tile the raw mosaic. The default layout below is a
    5x2, 10-offset HYPOTHESIS because the precise CM020D mosaic map has not
    been verified. The resulting planes are useful for pipeline testing and
    visual inspection, but band identity must be empirically verified before
    calibration data is trusted.

Band order:
    B1 350-410 nm, B2 410-470 nm, B3 470-530 nm, B4 530-590 nm,
    B5 590-650 nm, B6 650-710 nm, B7 710-770 nm, B8 770-830 nm,
    B9 830-890 nm, B10 890-950 nm.
"""

from __future__ import annotations

import argparse
import os
import struct
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np


RAW_WIDTH = 1600
RAW_HEIGHT = 1200
QS_HEADER_SIZE = 8
QS_MAGIC = b"LLSQ"
RAW_PAYLOAD_BYTES = RAW_WIDTH * RAW_HEIGHT * 2
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
SDK_CUBE_HEADER = "<IIII"
SDK_CUBE_HEADER_SIZE = struct.calcsize(SDK_CUBE_HEADER)


@dataclass(frozen=True)
class MosaicLayout:
    """Configurable raw mosaic de-tile layout.

    `offsets` maps output band index to raw-pixel offset `(dy, dx)`, sampled as
    `raw[dy::period_y, dx::period_x]`.
    """

    period_y: int
    period_x: int
    offsets: tuple[tuple[int, int], ...]
    name: str = "custom"
    verified: bool = False
    note: str = ""

    def validate(self) -> None:
        if self.period_y <= 0 or self.period_x <= 0:
            raise ValueError("Mosaic periods must be positive")
        if len(self.offsets) != len(BAND_RANGES_NM):
            raise ValueError(f"Expected 10 offsets, got {len(self.offsets)}")
        for dy, dx in self.offsets:
            if not (0 <= dy < self.period_y and 0 <= dx < self.period_x):
                raise ValueError(
                    f"Offset {(dy, dx)} outside period "
                    f"{self.period_y}x{self.period_x}"
                )


DEFAULT_MOSAIC_LAYOUT = MosaicLayout(
    period_y=2,
    period_x=5,
    offsets=tuple((dy, dx) for dy in range(2) for dx in range(5)),
    name="hypothesis_5x2_row_major",
    verified=False,
    note=(
        "Hypothesis only. Prefer SDK qsToQsi/qsiToGray output, or verify this "
        "layout with a known color/NIR target before trusting band identity."
    ),
)


def load_qs(path: str | Path) -> np.ndarray:
    """Load an LLSQ `.qs` frame as a `(1200, 1600)` uint16 raw mosaic array."""
    data = Path(path).read_bytes()
    if len(data) == RAW_PAYLOAD_BYTES:
        payload = data
    elif len(data) >= QS_HEADER_SIZE + RAW_PAYLOAD_BYTES and data[:4] == QS_MAGIC:
        payload = data[QS_HEADER_SIZE : QS_HEADER_SIZE + RAW_PAYLOAD_BYTES]
    else:
        raise ValueError(
            f"Unsupported QS file: expected raw payload or LLSQ+8-byte header, "
            f"got {len(data)} bytes"
        )
    raw = np.frombuffer(payload, dtype="<u2", count=RAW_WIDTH * RAW_HEIGHT)
    return np.ascontiguousarray(raw.reshape(RAW_HEIGHT, RAW_WIDTH))


def extract_bands(raw: np.ndarray, layout: MosaicLayout = DEFAULT_MOSAIC_LAYOUT) -> np.ndarray:
    """Extract 10 de-tiled band planes from a raw mosaic using `layout`.

    This is the pure-Python fallback. The default layout is not a verified
    CM020D band map; use SDK extraction when possible.
    """
    layout.validate()
    raw_arr = np.asarray(raw)
    if raw_arr.ndim != 2:
        raise ValueError(f"raw must be a 2D array, got shape {raw_arr.shape}")

    min_h = min((raw_arr.shape[0] - dy + layout.period_y - 1) // layout.period_y for dy, _ in layout.offsets)
    min_w = min((raw_arr.shape[1] - dx + layout.period_x - 1) // layout.period_x for _, dx in layout.offsets)
    if min_h <= 0 or min_w <= 0:
        raise ValueError(f"raw shape {raw_arr.shape} is too small for {layout}")

    bands = np.empty((len(layout.offsets), min_h, min_w), dtype=np.float32)
    for band_index, (dy, dx) in enumerate(layout.offsets):
        bands[band_index] = raw_arr[dy :: layout.period_y, dx :: layout.period_x][
            :min_h, :min_w
        ].astype(np.float32, copy=False)
    return bands


def extract_bands_from_qs(
    qs_path: str | Path,
    *,
    layout: MosaicLayout = DEFAULT_MOSAIC_LAYOUT,
    sdk_tool: str | Path | None = None,
    qsbs_path: str | Path | None = None,
    qsdb_path: str | Path | None = None,
    prefer_sdk: bool = True,
    intricacy: int = 100,
    light_source: int | None = None,
) -> np.ndarray:
    """Return band cube `(10, H, W)` from `qs_path`.

    If SDK helper inputs are supplied, the helper is used and returns the
    SDK-demultiplexed planes from qsToQsi/qsiToGray. Otherwise this falls back
    to configurable raw mosaic de-tiling.
    """
    sdk_tool = sdk_tool or os.environ.get("VNIR_QS_TO_BANDS")
    qsbs_path = qsbs_path or os.environ.get("VNIR_QSBS")
    qsdb_path = qsdb_path or os.environ.get("VNIR_QSDB")
    if prefer_sdk and sdk_tool and qsbs_path and qsdb_path:
        return _extract_bands_with_sdk(
            qs_path,
            sdk_tool=sdk_tool,
            qsbs_path=qsbs_path,
            qsdb_path=qsdb_path,
            intricacy=intricacy,
            light_source=light_source,
        )
    return extract_bands(load_qs(qs_path), layout=layout)


def per_bean_spectra(
    bands: np.ndarray,
    bboxes: Iterable[Sequence[float]],
    *,
    source_shape: tuple[int, int] | None = None,
) -> list[dict[str, object]]:
    """Return per-bean `mean` and `std` arrays for each bbox.

    `bboxes` are `[x, y, w, h]`. If `source_shape=(height, width)` is supplied,
    bbox coordinates are scaled into the band-plane resolution before sampling.
    """
    cube = _as_band_cube(bands)
    _n_bands, band_h, band_w = cube.shape
    if source_shape is None:
        source_h, source_w = band_h, band_w
    else:
        source_h, source_w = source_shape
        if source_h <= 0 or source_w <= 0:
            raise ValueError(f"Invalid source_shape: {source_shape}")
    sx = band_w / float(source_w)
    sy = band_h / float(source_h)

    spectra: list[dict[str, object]] = []
    for bbox in bboxes:
        if len(bbox) != 4:
            raise ValueError(f"Expected bbox [x, y, w, h], got {bbox!r}")
        x, y, w, h = [float(v) for v in bbox]
        x0 = _clamp_int(np.floor(x * sx), 0, band_w)
        y0 = _clamp_int(np.floor(y * sy), 0, band_h)
        x1 = _clamp_int(np.ceil((x + w) * sx), 0, band_w)
        y1 = _clamp_int(np.ceil((y + h) * sy), 0, band_h)
        if x1 <= x0 or y1 <= y0:
            mean = [None] * cube.shape[0]
            std = [None] * cube.shape[0]
        else:
            roi = cube[:, y0:y1, x0:x1]
            mean = _finite_list(roi.mean(axis=(1, 2), dtype=np.float64))
            std = _finite_list(roi.std(axis=(1, 2), dtype=np.float64))
        spectra.append({"bbox": [x, y, w, h], "mean": mean, "std": std})
    return spectra


def validate_band_map(bands_or_qs: str | Path | np.ndarray) -> list[dict[str, float | int | list[int]]]:
    """Return per-band mean/std summary for field sanity checks."""
    if isinstance(bands_or_qs, (str, Path)):
        bands = extract_bands_from_qs(bands_or_qs)
    else:
        arr = np.asarray(bands_or_qs)
        bands = extract_bands(arr) if arr.ndim == 2 else _as_band_cube(arr)
    summary = []
    for index, (start, end) in enumerate(BAND_RANGES_NM):
        plane = bands[index]
        summary.append(
            {
                "band": index + 1,
                "range_nm": [start, end],
                "mean": float(np.mean(plane)),
                "std": float(np.std(plane)),
            }
        )
    return summary


def suggest_mosaic_layouts(
    raw: np.ndarray,
    candidates: Sequence[tuple[int, int]] = ((2, 5), (5, 2), (4, 4), (3, 3)),
) -> list[dict[str, object]]:
    """Summarize candidate periods for empirical layout calibration.

    This helper does not identify true wavelengths. It reports offset-level
    signal stats so a calibration target can be used to choose a plausible
    period/map in Phase 3.
    """
    raw_arr = np.asarray(raw)
    results: list[dict[str, object]] = []
    for period_y, period_x in candidates:
        offsets = [(dy, dx) for dy in range(period_y) for dx in range(period_x)]
        cells = []
        for dy, dx in offsets:
            cell = raw_arr[dy::period_y, dx::period_x]
            cells.append(
                {
                    "offset": [dy, dx],
                    "mean": float(np.mean(cell)),
                    "std": float(np.std(cell)),
                }
            )
        results.append(
            {
                "period_y": period_y,
                "period_x": period_x,
                "cell_count": len(cells),
                "cells": cells,
            }
        )
    return results


def save_montage(bands: np.ndarray, path: str | Path) -> Path:
    """Save a 2x5 grayscale PGM montage for visual band inspection."""
    cube = _as_band_cube(bands)
    tiles = [_normalize_u8(cube[i]) for i in range(cube.shape[0])]
    top = np.concatenate(tiles[:5], axis=1)
    bottom = np.concatenate(tiles[5:], axis=1)
    montage = np.concatenate([top, bottom], axis=0)
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    header = f"P5\n# VNIR 10-band montage B1-B10\n{montage.shape[1]} {montage.shape[0]}\n255\n"
    out.write_bytes(header.encode("ascii") + montage.tobytes())
    return out


def _extract_bands_with_sdk(
    qs_path: str | Path,
    *,
    sdk_tool: str | Path,
    qsbs_path: str | Path,
    qsdb_path: str | Path,
    intricacy: int,
    light_source: int | None,
) -> np.ndarray:
    with tempfile.TemporaryDirectory() as tmp:
        out_path = Path(tmp) / "vnir_bands.bin"
        cmd = [
            str(sdk_tool),
            str(qsbs_path),
            str(qsdb_path),
            str(qs_path),
            str(out_path),
            str(intricacy),
        ]
        if light_source is not None:
            cmd.append(str(light_source))
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            raise RuntimeError(
                "SDK band extraction failed "
                f"(exit {proc.returncode}): {proc.stderr.strip()}"
            )
        return _load_sdk_cube(out_path)


def _load_sdk_cube(path: str | Path) -> np.ndarray:
    data = Path(path).read_bytes()
    if len(data) < SDK_CUBE_HEADER_SIZE:
        raise ValueError("SDK cube output is too short")
    n_bands, width, height, dtype_bytes = struct.unpack_from(SDK_CUBE_HEADER, data, 0)
    if n_bands != len(BAND_RANGES_NM) or dtype_bytes != 4 or width <= 0 or height <= 0:
        raise ValueError(
            f"Unexpected SDK cube header bands={n_bands} width={width} "
            f"height={height} dtype_bytes={dtype_bytes}"
        )
    expected = SDK_CUBE_HEADER_SIZE + n_bands * width * height * dtype_bytes
    if len(data) != expected:
        raise ValueError(f"SDK cube size mismatch: got {len(data)}, expected {expected}")
    arr = np.frombuffer(data, dtype="<f4", offset=SDK_CUBE_HEADER_SIZE)
    return np.ascontiguousarray(arr.reshape(n_bands, height, width))


def _as_band_cube(bands: np.ndarray) -> np.ndarray:
    cube = np.asarray(bands, dtype=np.float32)
    if cube.ndim != 3 or cube.shape[0] != len(BAND_RANGES_NM):
        raise ValueError(f"bands must have shape (10, H, W), got {cube.shape}")
    return cube


def _normalize_u8(plane: np.ndarray) -> np.ndarray:
    arr = np.asarray(plane, dtype=np.float32)
    lo = float(np.nanpercentile(arr, 1))
    hi = float(np.nanpercentile(arr, 99))
    if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
        return np.zeros(arr.shape, dtype=np.uint8)
    scaled = (np.clip(arr, lo, hi) - lo) * (255.0 / (hi - lo))
    return scaled.astype(np.uint8)


def _finite_list(values: np.ndarray) -> list[float | None]:
    out: list[float | None] = []
    for value in values:
        v = float(value)
        out.append(v if np.isfinite(v) else None)
    return out


def _clamp_int(value: float, low: int, high: int) -> int:
    return max(low, min(high, int(value)))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect VNIR bands from one .qs file")
    parser.add_argument("qs", help="input .qs frame")
    parser.add_argument("--montage", help="output PGM montage path")
    parser.add_argument("--sdk-tool", default=os.environ.get("VNIR_QS_TO_BANDS"))
    parser.add_argument("--qsbs", default=os.environ.get("VNIR_QSBS"))
    parser.add_argument("--qsdb", default=os.environ.get("VNIR_QSDB"))
    parser.add_argument("--intricacy", type=int, default=100)
    parser.add_argument("--light-source", type=int)
    parser.add_argument(
        "--auto-detect-layout",
        action="store_true",
        help="print candidate raw mosaic period stats for calibration-target runs",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.auto_detect_layout:
        for candidate in suggest_mosaic_layouts(load_qs(args.qs)):
            print(
                f"period={candidate['period_y']}x{candidate['period_x']} "
                f"cells={candidate['cell_count']}"
            )
        return 0

    used_sdk = bool(args.sdk_tool and args.qsbs and args.qsdb)
    bands = extract_bands_from_qs(
        args.qs,
        sdk_tool=args.sdk_tool,
        qsbs_path=args.qsbs,
        qsdb_path=args.qsdb,
        intricacy=args.intricacy,
        light_source=args.light_source,
    )
    print(f"source={'sdk_qsToQsi' if used_sdk else 'fallback_mosaic_hypothesis'}")
    for item in validate_band_map(bands):
        print(
            f"B{item['band']:02d} {item['range_nm'][0]}-{item['range_nm'][1]}nm "
            f"mean={item['mean']:.3f} std={item['std']:.3f}"
        )
    montage = Path(args.montage) if args.montage else Path(args.qs).with_suffix(".bands.pgm")
    print(f"montage={save_montage(bands, montage)}")
    if not used_sdk:
        print(f"WARNING: fallback layout {DEFAULT_MOSAIC_LAYOUT.name} is not verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

