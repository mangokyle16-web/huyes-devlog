"""
QAB binary → numpy cube (H, W, 5) float32 [0,1]

QAB format (QS SDK qsToQab() output):
  5 bands sequential: band0[H×W uint16] | band1[H×W uint16] | ... | band4[H×W uint16]
  Wavelengths: 450 / 560 / 650 / 730 / 840 nm
"""
import numpy as np
from spectral_capture.config import CAMERA_W, CAMERA_H, N_BANDS

BYTES_PER_PIXEL = 2  # uint16
EXPECTED_BYTES  = CAMERA_H * CAMERA_W * N_BANDS * BYTES_PER_PIXEL


class QABFormatError(ValueError):
    pass


def parse_qab(qab_bytes: bytes) -> np.ndarray:
    """
    QAB bytes → numpy array (H, W, N_BANDS) float32, normalized to [0, 1]

    Args:
        qab_bytes: raw bytes from qsToQab()

    Returns:
        cube: shape (CAMERA_H, CAMERA_W, N_BANDS), dtype float32
    """
    if len(qab_bytes) != EXPECTED_BYTES:
        raise QABFormatError(
            f"QAB size mismatch: got {len(qab_bytes)}, "
            f"expected {EXPECTED_BYTES} ({CAMERA_H}×{CAMERA_W}×{N_BANDS}×{BYTES_PER_PIXEL})"
        )
    raw = np.frombuffer(qab_bytes, dtype=np.uint16)
    # Shape: (N_BANDS, H, W) → transpose to (H, W, N_BANDS)
    cube = raw.reshape(N_BANDS, CAMERA_H, CAMERA_W).transpose(1, 2, 0)
    return cube.astype(np.float32) / 65535.0
