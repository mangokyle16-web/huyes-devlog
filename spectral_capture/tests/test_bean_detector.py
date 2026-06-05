import numpy as np
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from spectral_capture.pipeline.qab_parser import parse_qab
from spectral_capture.pipeline.bean_detector import detect_beans, BeanDetection
from spectral_capture.tests.fixtures.make_fake_qab import make_fake_qab

def test_detect_correct_count():
    cube = parse_qab(make_fake_qab(n_beans=5, seed=1))
    beans = detect_beans(cube)
    assert 3 <= len(beans) <= 6, f"Expected ~5 beans, got {len(beans)}"

def test_bean_has_spectral_vector():
    cube = parse_qab(make_fake_qab(n_beans=3))
    beans = detect_beans(cube)
    assert len(beans) > 0
    b = beans[0]
    assert isinstance(b, BeanDetection)
    assert b.spec_vec.shape == (5,)
    assert b.spec_vec.dtype == np.float32

def test_bean_bbox_within_image():
    cube = parse_qab(make_fake_qab(n_beans=3))
    beans = detect_beans(cube)
    for b in beans:
        x, y, w, h = b.bbox
        assert x >= 0 and y >= 0
        assert x + w <= 1600
        assert y + h <= 1200

def test_belt_background_not_detected():
    """Empty green belt (no beans) should return 0 detections"""
    cube = np.zeros((1200, 1600, 5), dtype=np.float32)
    cube[:, :, 4] = 0.72   # NIR = high reflectance (green belt)
    cube[:, :, 0] = 0.15
    cube[:, :, 1] = 0.45
    cube[:, :, 2] = 0.25
    cube[:, :, 3] = 0.20
    beans = detect_beans(cube)
    assert len(beans) == 0, f"Expected 0 beans on empty belt, got {len(beans)}"
