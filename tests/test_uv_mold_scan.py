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


def test_compute_fl_score_emission_mean_and_norm():
    fl_signal = {
        "bean_1": {350: 0.0, 410: 2.0, 430: 2.0, 450: 2.0, 470: 2.0, 490: 2.0},
        "bean_2": {350: 0.0, 410: 1.0, 430: 1.0, 450: 1.0, 470: 1.0, 490: 1.0},
    }
    uv_spec = {"bean_1": {350: 4.0}, "bean_2": {350: 4.0}}
    fl_score, fl_norm = compute_fl_score(fl_signal, uv_spec)
    assert fl_score["bean_1"] == pytest.approx(2.0)
    assert fl_score["bean_2"] == pytest.approx(1.0)
    assert fl_norm["bean_1"]  == pytest.approx(2.0 / 4.0)
    assert fl_norm["bean_2"]  == pytest.approx(1.0 / 4.0)


def test_compute_fl_score_zero_uv_ref_no_crash():
    fl_signal = {"bean_1": {410: 1.0, 430: 1.0, 450: 1.0, 470: 1.0, 490: 1.0}}
    uv_spec   = {"bean_1": {350: 0.0}}   # UV ref = 0 → must not divide by zero
    fl_score, fl_norm = compute_fl_score(fl_signal, uv_spec)
    assert np.isfinite(fl_norm["bean_1"])


def test_flag_suspects_outlier_flagged():
    fl_norm = {"bean_1": 0.1, "bean_2": 0.1, "bean_3": 0.1,
               "bean_4": 0.1, "bean_5": 1.0}
    flags = flag_suspects(fl_norm, sigma=1.5)
    assert flags["bean_5"] == "SUSPECT"
    assert all(flags[f"bean_{i}"] == "OK" for i in range(1, 5))


def test_flag_suspects_all_identical_no_suspects():
    fl_norm = {"bean_1": 1.0, "bean_2": 1.0, "bean_3": 1.0}
    flags = flag_suspects(fl_norm, sigma=1.5)
    # std=0 → threshold=mean → no bean strictly exceeds mean
    assert all(f == "OK" for f in flags.values())


def test_save_report_csv(tmp_path):
    fl_score = {"bean_1": 2.0, "bean_2": 1.0}
    fl_norm  = {"bean_1": 0.5, "bean_2": 0.25}
    flags    = {"bean_1": "SUSPECT", "bean_2": "OK"}
    out = str(tmp_path / "report.csv")
    save_report_csv(fl_score, fl_norm, flags, out)

    with open(out) as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 2
    assert rows[0]["bean_id"]  == "bean_1"
    assert rows[0]["flag"]     == "SUSPECT"
    assert float(rows[0]["fl_norm"]) == pytest.approx(0.5, abs=1e-3)
    assert rows[1]["flag"] == "OK"
