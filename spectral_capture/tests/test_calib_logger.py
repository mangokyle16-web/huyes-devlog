import json
import struct
import sys
import tempfile
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from spectral_capture.spectral.band_extract import N_BANDS
from spectral_capture.spectral.calib_logger import main


def _write_cube(path: Path, width: int, height: int) -> None:
    header = struct.pack("<IIII", N_BANDS, width, height, 4)
    cube = np.zeros((N_BANDS, height, width), dtype="<f4")
    for b in range(N_BANDS):
        cube[b] = float(b + 1)
    path.write_bytes(header + cube.tobytes())


def _write_json(path: Path, obj) -> None:
    path.write_text(json.dumps(obj), encoding="utf-8")


def test_append_then_set_weight_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        dataset = tmp / "calib" / "vnir_calib.jsonl"
        cube = tmp / "vnir_bands.bin"
        detect = tmp / "bean_detect.json"
        count_status = tmp / "count_status.json"

        _write_cube(cube, width=8, height=6)
        _write_json(detect, {"count": 2, "boxes": [[0, 0, 4, 4], [2, 2, 4, 4]]})
        _write_json(count_status, {"batch_id": "batch-xyz", "total_crossed": 2, "updated_at": 123.0})

        rc = main([
            "--dataset", str(dataset),
            "append",
            "--cube", str(cube),
            "--detect-json", str(detect),
            "--count-status", str(count_status),
            "--box-frame-width", "8",
            "--box-frame-height", "6",
        ])
        assert rc == 0

        rows = [json.loads(l) for l in dataset.read_text().splitlines() if l.strip()]
        assert len(rows) == 1
        row = rows[0]
        assert row["schema_version"] == 1
        assert row["batch_id"] == "batch-xyz"
        assert row["count"] == 2
        assert row["true_weight_g"] is None
        assert len(row["spectral_features"]["band_mean"]) == N_BANDS
        np.testing.assert_allclose(row["spectral_features"]["band_mean"], [b + 1 for b in range(N_BANDS)])
        assert row["bbox_geometry"]["bean_count"] == 2
        assert row["source"]["cube_shape"] == [N_BANDS, 6, 8]

        # fill the scale weight in later
        rc = main(["--dataset", str(dataset), "set-weight", "batch-xyz", "61.2"])
        assert rc == 0
        row2 = json.loads(dataset.read_text().splitlines()[0])
        assert row2["true_weight_g"] == 61.2
        assert "weight_updated_at" in row2


def test_set_weight_missing_batch_returns_error():
    with tempfile.TemporaryDirectory() as tmp:
        dataset = Path(tmp) / "vnir_calib.jsonl"
        dataset.write_text(json.dumps({"batch_id": "a", "true_weight_g": None}) + "\n", encoding="utf-8")
        rc = main(["--dataset", str(dataset), "set-weight", "nonexistent", "10.0"])
        assert rc == 1


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-q"]))
