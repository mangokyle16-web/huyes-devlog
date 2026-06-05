"""
Generates synthetic qs_daemon frame data for testing without a camera.

Format matches the new qs_daemon protocol:
  [n_bands: uint32 LE][width: uint32 LE][height: uint32 LE][dtype: uint32 LE=4]
  [band_data: float32 × n_bands × H × W]  -- band-first layout

Band values are calibrated radiance-like (~0–10 range), NOT 0-1 reflectance.
Background (green belt): high NIR (~3.5), moderate visible.
Beans: lower NIR (~1.2), distinct spectral signature.
"""
import numpy as np
import struct
import cv2
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from spectral_capture.config import NIR_BAND_IDX

W, H, N = 1600, 1200, 5

# Vegetation index values (range -1 to 1):
# Bands: NDVI, GNDVI, NDRE, OSAVI, LCI
# Green belt has high chlorophyll → high NDVI/GNDVI/NDRE
# Coffee beans: lower vegetation indices (brown/tan object, no chlorophyll)
BG_VALS   = np.array([ 0.75,  0.70,  0.55,  0.68,  0.50], dtype=np.float32)
BEAN_VALS = np.array([ 0.10,  0.08,  0.05,  0.09,  0.04], dtype=np.float32)


def make_fake_qab(n_beans: int = 5, seed: int = 42) -> bytes:
    """
    Returns bytes in qs_daemon format: 16-byte sub-header + float32 band data.
    Total: 16 + 5 × 1200 × 1600 × 4 = 38,400,016 bytes.
    """
    rng = np.random.default_rng(seed)

    cube = np.zeros((N, H, W), dtype=np.float32)
    for b in range(N):
        cube[b] = BG_VALS[b]

    for i in range(n_beans):
        cx = int(rng.integers(100, W - 100))
        cy = int(rng.integers(100, H - 100))
        rx, ry = int(rng.integers(12, 22)), int(rng.integers(8, 15))
        for b in range(N):
            val = float(BEAN_VALS[b]) + rng.uniform(-0.05, 0.05)
            if i == 0 and b == NIR_BAND_IDX:
                val = float(BEAN_VALS[b]) * 0.7  # defect bean: lower NIR only
            cv2.ellipse(cube[b], (cx, cy), (rx, ry), 0, 0, 360, val, -1)

    # Sub-header: n_bands, width, height, dtype(4=float32)
    subheader = struct.pack("<IIII", N, W, H, 4)
    return subheader + cube.tobytes()


if __name__ == "__main__":
    out = Path(__file__).parent / "fake_5bean.qab"
    data = make_fake_qab(n_beans=5)
    out.write_bytes(data)
    expected = 16 + N * H * W * 4
    assert len(data) == expected, f"Expected {expected}, got {len(data)}"
    print(f"Written {len(data):,} bytes → {out}")
    print("OK")
