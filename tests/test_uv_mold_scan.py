import csv, os, sys, pytest
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from uv_mold_scan import (
    load_spec_csv, compute_fluorescence, compute_fl_score, flag_suspects,
    save_report_csv,
)


def _make_csv(tmp_path, data):
    """Write a spec CSV matching spec_fingerprint output format."""
    all_nms = sorted({nm for spec in data.values() for nm in spec})
    bean_ids = sorted(data.keys())
    path = str(tmp_path / "spec.csv")
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["wavelength_nm"] + bean_ids)
        for nm in all_nms:
            w.writerow([nm] + [data[b].get(nm, 0.0) for b in bean_ids])
    return path
