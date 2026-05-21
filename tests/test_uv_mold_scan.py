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


def test_load_spec_csv_basic(tmp_path):
    path = _make_csv(tmp_path, {
        "bean_1": {350: 1.0, 410: 2.0, 450: 3.0},
        "bean_2": {350: 1.5, 410: 2.5, 450: 3.5},
    })
    spec = load_spec_csv(path)
    assert set(spec.keys()) == {"bean_1", "bean_2"}
    assert spec["bean_1"][350] == pytest.approx(1.0)
    assert spec["bean_2"][450] == pytest.approx(3.5)


def test_load_spec_csv_wavelength_as_int(tmp_path):
    path = _make_csv(tmp_path, {"bean_1": {410: 5.5}})
    spec = load_spec_csv(path)
    assert 410 in spec["bean_1"]          # key must be int, not string
    assert spec["bean_1"][410] == pytest.approx(5.5)


def test_compute_fluorescence_subtracts_dark():
    uv   = {"bean_1": {410: 5.0, 450: 6.0, 350: 2.0},
            "bean_2": {410: 3.0, 450: 4.0, 350: 1.5}}
    dark = {"bean_1": {410: 1.0, 450: 1.5, 350: 0.5},
            "bean_2": {410: 0.5, 450: 0.5, 350: 0.3}}
    fl = compute_fluorescence(uv, dark)
    assert fl["bean_1"][410] == pytest.approx(4.0)
    assert fl["bean_1"][450] == pytest.approx(4.5)
    assert fl["bean_2"][410] == pytest.approx(2.5)


def test_compute_fluorescence_clamps_negative():
    uv   = {"bean_1": {410: 0.3}}
    dark = {"bean_1": {410: 1.0}}
    fl = compute_fluorescence(uv, dark)
    assert fl["bean_1"][410] == 0.0   # must not go negative
