import json
import tempfile
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from spectral_capture.spectral.calib_logger import record_batch


def test_record_batch_appends_phase1_jsonl_row_with_aggregate_features():
    bean_spectra = [
        {
            "mean": [10 + i for i in range(10)],
            "std": [1 + i / 10 for i in range(10)],
        },
        {
            "mean": [20 + i for i in range(10)],
            "std": [2 + i / 10 for i in range(10)],
        },
    ]
    bboxes = [[0, 0, 10, 20], [5, 5, 20, 10]]

    with tempfile.TemporaryDirectory() as tmp:
        dataset_path = Path(tmp) / "calibration" / "calib_dataset.jsonl"
        row = record_batch(
            "batch-001",
            2,
            bean_spectra,
            bboxes,
            30.0,
            dataset_path=dataset_path,
        )

        written = [json.loads(line) for line in dataset_path.read_text().splitlines()]

    assert len(written) == 1
    assert written[0] == row
    assert row["schema_version"] == 1
    assert row["batch_id"] == "batch-001"
    assert row["count"] == 2
    assert row["scale_weight_g"] == 30.0
    assert row["g_per_bean_observed"] == 15.0
    np.testing.assert_allclose(row["band_mean"], [15 + i for i in range(10)])
    np.testing.assert_allclose(row["band_std"], [1.5 + i / 10 for i in range(10)])
    assert row["bbox_area_median"] == 200.0
    assert row["bbox_w_median"] == 15.0
    assert row["bbox_h_median"] == 15.0
    assert row["aspect_median"] == 1.25
    assert "timestamp" in row


if __name__ == "__main__":
    test_record_batch_appends_phase1_jsonl_row_with_aggregate_features()
