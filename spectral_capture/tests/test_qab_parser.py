import numpy as np
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from spectral_capture.pipeline.qab_parser import parse_qab, QABFormatError
from spectral_capture.tests.fixtures.make_fake_qab import make_fake_qab

def test_parse_returns_correct_shape():
    data = make_fake_qab(n_beans=3)
    cube = parse_qab(data)
    assert cube.shape == (1200, 1600, 5), f"Got {cube.shape}"

def test_parse_normalized_range():
    data = make_fake_qab()
    cube = parse_qab(data)
    assert cube.dtype == np.float32
    assert cube.min() >= 0.0
    assert cube.max() <= 1.0

def test_parse_wrong_size_raises():
    import pytest
    with pytest.raises(QABFormatError):
        parse_qab(b"\x00" * 100)

def test_nir_band_background_is_higher():
    """Green belt NIR (band 4) reflectance should be higher than bean areas"""
    data = make_fake_qab(n_beans=1, seed=0)
    cube = parse_qab(data)
    nir = cube[:, :, 4]
    corner_mean = np.mean(nir[:50, :50])
    assert corner_mean > 0.5, f"Corner NIR {corner_mean:.3f} not high enough"
