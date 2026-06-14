#!/usr/bin/env python3
"""Append and update VNIR batch-level calibration rows (SDK-cube path).

Consumes the SDK band cube produced by ``qs_to_bands`` plus the live detection /
count snapshots, and appends one calibration row per batch. The scale weight can
be filled in later with ``set-weight``.

Examples:
  python3 -m spectral_capture.spectral.calib_logger append --cube /dev/shm/vnir_bands.bin
  python3 -m spectral_capture.spectral.calib_logger append --weight 61.2
  python3 -m spectral_capture.spectral.calib_logger set-weight 20260613_153012 61.2
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from spectral_capture.spectral.band_extract import extract_batch_features, load_band_cube


DEFAULT_DATASET = REPO_ROOT / "data/calibration/vnir_calib.jsonl"
DEFAULT_CUBE = Path("/dev/shm/vnir_bands.bin")
DEFAULT_DETECT_JSON = Path("/dev/shm/bean_detect.json")
DEFAULT_COUNT_STATUS = Path("/dev/shm/count_status.json")


def read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return {}


def append_row(args: argparse.Namespace) -> int:
    dataset = Path(args.dataset)
    count_status = read_json(Path(args.count_status))
    detect = read_json(Path(args.detect_json))
    cube_path = Path(args.cube)

    boxes = detect.get("boxes") or []
    cube = load_band_cube(cube_path)
    box_frame_size = None
    if args.box_frame_width and args.box_frame_height:
        box_frame_size = (int(args.box_frame_width), int(args.box_frame_height))
    features = extract_batch_features(cube, boxes, box_frame_size=box_frame_size)

    batch_id = args.batch_id or count_status.get("batch_id") or _default_batch_id()
    row = {
        "schema_version": 1,
        "batch_id": str(batch_id),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "count": _coerce_int(args.count, count_status.get("total_crossed")),
        "true_weight_g": _coerce_float_or_none(args.weight),
        "spectral_features": {
            "band_ranges_nm": features["band_ranges_nm"],
            "band_mean": features["band_mean"],
            "band_std": features["band_std"],
            "valid_bean_count": features["valid_bean_count"],
        },
        "bbox_geometry": {
            "bean_count": features["bean_count"],
            "bbox_width_mean": features["bbox_width_mean"],
            "bbox_width_median": features["bbox_width_median"],
            "bbox_height_mean": features["bbox_height_mean"],
            "bbox_height_median": features["bbox_height_median"],
            "bbox_area_mean": features["bbox_area_mean"],
            "bbox_area_median": features["bbox_area_median"],
        },
        "source": {
            "cube_path": str(cube_path),
            "detect_json": str(args.detect_json),
            "count_status_json": str(args.count_status),
            "cube_shape": list(cube.shape),
            "detect_count": detect.get("count"),
            "count_status_updated_at": count_status.get("updated_at"),
        },
    }

    dataset.parent.mkdir(parents=True, exist_ok=True)
    with dataset.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    print(f"appended batch_id={row['batch_id']} dataset={dataset}")
    return 0


def set_weight(args: argparse.Namespace) -> int:
    dataset = Path(args.dataset)
    if not dataset.exists():
        print(f"dataset not found: {dataset}", file=sys.stderr)
        return 1

    target = str(args.batch_id)
    weight = float(args.grams)
    rows: list[dict[str, Any]] = []
    updated = 0
    for line in dataset.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if str(row.get("batch_id")) == target:
            row["true_weight_g"] = weight
            row["weight_updated_at"] = datetime.now(timezone.utc).isoformat()
            updated += 1
        rows.append(row)

    if updated == 0:
        print(f"batch_id not found: {target}", file=sys.stderr)
        return 1

    tmp = dataset.with_suffix(dataset.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    os.replace(tmp, dataset)
    print(f"updated batch_id={target} rows={updated} dataset={dataset}")
    return 0


def _coerce_int(primary: Any, fallback: Any) -> int | None:
    value = primary if primary is not None else fallback
    if value is None:
        return None
    return int(value)


def _coerce_float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _default_batch_id() -> str:
    return datetime.fromtimestamp(time.time()).strftime("%Y%m%d_%H%M%S")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        default=str(DEFAULT_DATASET),
        help=f"JSONL dataset path (default: {DEFAULT_DATASET})",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    append = sub.add_parser("append", help="append one calibration row")
    append.add_argument("--cube", default=str(DEFAULT_CUBE))
    append.add_argument("--detect-json", default=str(DEFAULT_DETECT_JSON))
    append.add_argument("--count-status", default=str(DEFAULT_COUNT_STATUS))
    append.add_argument("--batch-id")
    append.add_argument("--count", type=int)
    append.add_argument("--weight", type=float)
    append.add_argument("--box-frame-width", type=int)
    append.add_argument("--box-frame-height", type=int)
    append.set_defaults(func=append_row)

    update = sub.add_parser("set-weight", help="set true scale weight for an existing row")
    update.add_argument("batch_id")
    update.add_argument("grams", type=float)
    update.set_defaults(func=set_weight)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
