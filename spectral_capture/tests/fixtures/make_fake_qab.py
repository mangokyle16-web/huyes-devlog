"""
Generates synthetic QAB binary for testing without a camera.
Format: N_BANDS sequential uint16 bands, each H×W.
"""
import numpy as np
import struct
import cv2
from pathlib import Path

# Import NIR_BAND_IDX from config
config_path = Path(__file__).parent.parent.parent / "config.py"
import importlib.util
spec = importlib.util.spec_from_file_location("config", config_path)
config = importlib.util.module_from_spec(spec)
spec.loader.exec_module(config)
NIR_BAND_IDX = config.NIR_BAND_IDX

W, H, N = 1600, 1200, 5

def make_fake_qab(n_beans: int = 5, seed: int = 42) -> bytes:
    rng = np.random.default_rng(seed)
    bg_vals   = np.array([0.15, 0.45, 0.25, 0.20, 0.72])
    bean_vals = np.array([0.08, 0.14, 0.18, 0.22, 0.35])

    cube = np.zeros((N, H, W), dtype=np.float32)
    for b in range(N):
        cube[b] = bg_vals[b]

    for i in range(n_beans):
        cx = int(rng.integers(100, W - 100))
        cy = int(rng.integers(100, H - 100))
        rx, ry = int(rng.integers(12, 22)), int(rng.integers(8, 15))
        for b in range(N):
            band = cube[b]
            val = bean_vals[b] + rng.uniform(-0.02, 0.02)
            if i == 0 and b == NIR_BAND_IDX:
                val = bean_vals[b] * 0.7  # defect bean: lower NIR only
            cv2.ellipse(band, (cx, cy), (rx, ry), 0, 0, 360, float(val), -1)

    cube_u16 = (cube * 65535).clip(0, 65535).astype(np.uint16)
    return cube_u16.tobytes()


if __name__ == "__main__":
    out = Path(__file__).parent / "fake_5bean.qab"
    data = make_fake_qab(n_beans=5)
    out.write_bytes(data)
    expected = W * H * N * 2
    assert len(data) == expected, f"Expected {expected}, got {len(data)}"
    print(f"Written {len(data):,} bytes → {out}")
    print("OK")
