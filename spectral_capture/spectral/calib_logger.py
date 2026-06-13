"""Append batch-level VNIR density calibration rows."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np

from spectral_capture.spectral.band_extract import (
    RAW_HEIGHT,
    RAW_WIDTH,
    extract_bands_from_qs,
    per_bean_spectra,
)


DEFAULT_DATASET_PATH = Path(
    "/home/kyle/KyleClaude/spectral_capture/data/calibration/calib_dataset.jsonl"
)


def record_batch(
    batch_id: str,
    count: int,
    bean_spectra_list: Iterable[dict[str, Any]],
    bbox_list: Iterable[Sequence[float]],
    scale_weight_g: float,
    *,
    dataset_path: str | Path = DEFAULT_DATASET_PATH,
) -> dict[str, Any]:
    """Append one Phase 1 calibration row and return it."""
    count_int = int(count)
    scale_weight = float(scale_weight_g)
    spectra = list(bean_spectra_list)
    bboxes = [list(map(float, bbox)) for bbox in bbox_list]
    band_mean, band_std = _aggregate_spectra(spectra)
    geom = _bbox_geometry_stats(bboxes)
    row = {
        "schema_version": 1,
        "batch_id": str(batch_id),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "count": count_int,
        "g_per_bean_observed": scale_weight / count_int if count_int > 0 else None,
        "band_mean": band_mean,
        "band_std": band_std,
        "bbox_area_mean": geom["bbox_area_mean"],
        "bbox_area_median": geom["bbox_area_median"],
        "bbox_w_mean": geom["bbox_w_mean"],
        "bbox_w_median": geom["bbox_w_median"],
        "bbox_h_mean": geom["bbox_h_mean"],
        "bbox_h_median": geom["bbox_h_median"],
        "aspect_mean": geom["aspect_mean"],
        "aspect_median": geom["aspect_median"],
        "scale_weight_g": scale_weight,
    }
    out = Path(dataset_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    return row


def record_from_batch_file(
    batch_json_path: str | Path,
    qs_path: str | Path,
    weight_g: float,
    *,
    dataset_path: str | Path = DEFAULT_DATASET_PATH,
    frame_id: int | None = None,
    source_shape: tuple[int, int] | None = None,
    sdk_tool: str | Path | None = None,
    qsbs_path: str | Path | None = None,
    qsdb_path: str | Path | None = None,
) -> dict[str, Any]:
    """Compute spectra from one representative `.qs` frame and append a row."""
    payload = json.loads(Path(batch_json_path).read_text(encoding="utf-8"))
    frame = _select_frame(payload.get("frames") or [], frame_id=frame_id)
    boxes = frame.get("boxes") or []
    if source_shape is None:
        source_shape = _source_shape_from_frame(frame) or (RAW_HEIGHT, RAW_WIDTH)
    bands = extract_bands_from_qs(
        qs_path,
        sdk_tool=sdk_tool,
        qsbs_path=qsbs_path,
        qsdb_path=qsdb_path,
    )
    spectra = per_bean_spectra(bands, boxes, source_shape=source_shape)
    return record_batch(
        str(payload.get("batch_id") or Path(batch_json_path).stem),
        int(payload.get("total_beans", payload.get("total_crossed", len(boxes))) or 0),
        spectra,
        boxes,
        float(weight_g),
        dataset_path=dataset_path,
    )


def _aggregate_spectra(spectra: list[dict[str, Any]]) -> tuple[list[float | None], list[float | None]]:
    means = _array_from_spectra(spectra, "mean")
    stds = _array_from_spectra(spectra, "std")
    return _nanmean_list(means), _nanmean_list(stds)


def _array_from_spectra(spectra: list[dict[str, Any]], key: str) -> np.ndarray:
    rows = []
    for item in spectra:
        values = item.get(key)
        if values is None:
            continue
        rows.append([np.nan if value is None else float(value) for value in values])
    if not rows:
        return np.empty((0, 10), dtype=np.float64)
    arr = np.asarray(rows, dtype=np.float64)
    if arr.ndim != 2 or arr.shape[1] != 10:
        raise ValueError(f"Each spectrum {key!r} must contain 10 values, got {arr.shape}")
    return arr


def _bbox_geometry_stats(bboxes: list[list[float]]) -> dict[str, float | None]:
    if not bboxes:
        return {
            "bbox_area_mean": None,
            "bbox_area_median": None,
            "bbox_w_mean": None,
            "bbox_w_median": None,
            "bbox_h_mean": None,
            "bbox_h_median": None,
            "aspect_mean": None,
            "aspect_median": None,
        }
    arr = np.asarray(bboxes, dtype=np.float64)
    if arr.ndim != 2 or arr.shape[1] != 4:
        raise ValueError(f"bbox_list must be rows of [x, y, w, h], got {arr.shape}")
    widths = np.maximum(0.0, arr[:, 2])
    heights = np.maximum(0.0, arr[:, 3])
    areas = widths * heights
    aspects = np.divide(widths, heights, out=np.full_like(widths, np.nan), where=heights > 0)
    return {
        "bbox_area_mean": _finite_or_none(np.mean(areas)),
        "bbox_area_median": _finite_or_none(np.median(areas)),
        "bbox_w_mean": _finite_or_none(np.mean(widths)),
        "bbox_w_median": _finite_or_none(np.median(widths)),
        "bbox_h_mean": _finite_or_none(np.mean(heights)),
        "bbox_h_median": _finite_or_none(np.median(heights)),
        "aspect_mean": _finite_or_none(np.nanmean(aspects)),
        "aspect_median": _finite_or_none(np.nanmedian(aspects)),
    }


def _select_frame(frames: list[dict[str, Any]], *, frame_id: int | None) -> dict[str, Any]:
    if not frames:
        return {"boxes": []}
    if frame_id is not None:
        for frame in frames:
            if int(frame.get("frame_id", -1)) == int(frame_id):
                return frame
        raise ValueError(f"frame_id {frame_id} not found in batch JSON")
    return max(frames, key=lambda frame: len(frame.get("boxes") or []))


def _source_shape_from_frame(frame: dict[str, Any]) -> tuple[int, int] | None:
    for key in ("source_shape", "frame_shape", "image_shape"):
        value = frame.get(key)
        if isinstance(value, (list, tuple)) and len(value) >= 2:
            return int(value[0]), int(value[1])
    value = frame.get("frame_size") or frame.get("image_size")
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        return int(value[1]), int(value[0])
    width = frame.get("width") or frame.get("image_width")
    height = frame.get("height") or frame.get("image_height")
    if width and height:
        return int(height), int(width)
    return None


def _nanmean_list(arr: np.ndarray) -> list[float | None]:
    if arr.size == 0:
        return [None] * 10
    with np.errstate(invalid="ignore"):
        values = np.nanmean(arr, axis=0)
    return [_finite_or_none(v) for v in values]


def _finite_or_none(value: float) -> float | None:
    value = float(value)
    return value if np.isfinite(value) else None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Append one VNIR calibration dataset row")
    parser.add_argument("--batch", required=True, help="batch_*.json path")
    parser.add_argument("--weight", required=True, type=float, help="manual scale weight in grams")
    parser.add_argument("--qs", required=True, help="representative .qs frame for spectra")
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET_PATH))
    parser.add_argument("--frame-id", type=int, help="use boxes from this batch frame")
    parser.add_argument("--source-width", type=int, help="bbox source frame width")
    parser.add_argument("--source-height", type=int, help="bbox source frame height")
    parser.add_argument("--sdk-tool")
    parser.add_argument("--qsbs")
    parser.add_argument("--qsdb")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    source_shape = None
    if args.source_width and args.source_height:
        source_shape = (args.source_height, args.source_width)
    row = record_from_batch_file(
        args.batch,
        args.qs,
        args.weight,
        dataset_path=args.dataset,
        frame_id=args.frame_id,
        source_shape=source_shape,
        sdk_tool=args.sdk_tool,
        qsbs_path=args.qsbs,
        qsdb_path=args.qsdb,
    )
    print(
        f"appended batch_id={row['batch_id']} count={row['count']} "
        f"scale_weight_g={row['scale_weight_g']} dataset={args.dataset}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

