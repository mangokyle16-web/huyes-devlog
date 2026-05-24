import csv, os, sys, pytest
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from mold_analysis import compute_mahalanobis, cross_validate, save_report_csv


# ── compute_mahalanobis ────────────────────────────────────────────────────────

def _make_spec(n_beans, base_val=1.0):
    """n normal beans with uniform spectrum."""
    nms = [350, 410, 450, 490, 550, 650, 750, 850, 930]
    return {f"bean_{i}": {nm: base_val for nm in nms} for i in range(1, n_beans + 1)}


def test_compute_mahalanobis_returns_all_keys():
    spec = _make_spec(5)
    result = compute_mahalanobis(spec)
    assert set(result.keys()) == set(spec.keys())


def test_compute_mahalanobis_non_negative():
    spec = _make_spec(10)
    result = compute_mahalanobis(spec)
    assert all(v >= 0 for v in result.values())


def test_compute_mahalanobis_outlier_highest():
    """Outlier bean should have maximum distance."""
    spec = _make_spec(9)
    # bean_10 is an outlier with extreme spectral values
    spec["bean_10"] = {350: 5.0, 410: 0.1, 450: 5.0, 490: 0.1,
                       550: 5.0, 650: 0.1, 750: 5.0, 850: 0.1, 930: 5.0}
    result = compute_mahalanobis(spec)
    max_bean = max(result, key=result.__getitem__)
    assert max_bean == "bean_10"


def test_compute_mahalanobis_too_few_beans():
    """Returns zeros when fewer than 3 beans (SVD unstable)."""
    spec = _make_spec(2)
    result = compute_mahalanobis(spec)
    assert all(v == 0.0 for v in result.values())


# ── cross_validate ─────────────────────────────────────────────────────────────

def _make_cross_data():
    """
    bean_1: both mahal and fl_norm high  → HIGH
    bean_2: only mahal high              → MID
    bean_3: only fl_norm high            → MID
    bean_4..10: both low                 → LOW
    With value=20 for outliers vs 1.0 for normals.
    """
    mahal   = {f"bean_{i}": 1.0 for i in range(1, 11)}
    fl_norm = {f"bean_{i}": 1.0 for i in range(1, 11)}
    mahal["bean_1"]   = 20.0;  fl_norm["bean_1"]  = 20.0
    mahal["bean_2"]   = 20.0   # fl_norm stays 1.0
    fl_norm["bean_3"] = 20.0   # mahal stays 1.0
    return mahal, fl_norm


def test_cross_validate_high():
    mahal, fl_norm = _make_cross_data()
    result = cross_validate(mahal, fl_norm, sigma=1.5)
    assert result["bean_1"] == "HIGH"


def test_cross_validate_mid_mahal_only():
    mahal, fl_norm = _make_cross_data()
    result = cross_validate(mahal, fl_norm, sigma=1.5)
    assert result["bean_2"] == "MID"


def test_cross_validate_mid_fl_only():
    mahal, fl_norm = _make_cross_data()
    result = cross_validate(mahal, fl_norm, sigma=1.5)
    assert result["bean_3"] == "MID"


def test_cross_validate_low():
    mahal, fl_norm = _make_cross_data()
    result = cross_validate(mahal, fl_norm, sigma=1.5)
    assert result["bean_4"] == "LOW"


def test_cross_validate_returns_all_common_keys():
    mahal   = {"bean_1": 1.0, "bean_2": 5.0}
    fl_norm = {"bean_1": 1.0, "bean_2": 5.0}
    result = cross_validate(mahal, fl_norm)
    assert set(result.keys()) == {"bean_1", "bean_2"}


def test_cross_validate_ignores_keys_not_in_both():
    mahal   = {"bean_1": 1.0, "bean_x": 99.0}
    fl_norm = {"bean_1": 1.0, "bean_y": 99.0}
    result = cross_validate(mahal, fl_norm)
    assert set(result.keys()) == {"bean_1"}


# ── save_report_csv ────────────────────────────────────────────────────────────

def test_save_report_csv_columns(tmp_path):
    mahal   = {"bean_1": 1.23, "bean_2": 4.56}
    fl_norm = {"bean_1": 0.01, "bean_2": 0.99}
    suspects = {"bean_1": "LOW", "bean_2": "HIGH"}
    out = str(tmp_path / "report.csv")
    save_report_csv(mahal, fl_norm, suspects, out)
    with open(out) as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["bean_id"] == "bean_1"
    assert rows[1]["suspect_level"] == "HIGH"
    assert float(rows[1]["mahal"]) == pytest.approx(4.56, abs=0.01)
    assert float(rows[1]["fl_norm"]) == pytest.approx(0.99, abs=0.01)
