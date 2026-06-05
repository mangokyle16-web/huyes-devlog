"""
Parse qs_daemon binary band data → numpy cube (H, W, N_BANDS) float32

Protocol (data section after the 24-byte frame header):
  [n_bands: uint32 LE]
  [width:   uint32 LE]
  [height:  uint32 LE]
  [dtype:   uint32 LE]  -- 4 = float32
  [band_data: float32 × n_bands × H × W]  -- band-first layout

Band wavelengths: 450 / 560 / 650 / 730 / 840 nm
Values: calibrated radiance from qabToGray() (positive float, ~0–10 range)
"""
import struct
import numpy as np

SUBHEADER_FMT  = "<IIII"   # n_bands, width, height, dtype
SUBHEADER_SIZE = struct.calcsize(SUBHEADER_FMT)  # 16 bytes


class QABFormatError(ValueError):
    pass


def parse_qab(data: bytes) -> np.ndarray:
    """
    Parse qs_daemon frame data → numpy array (H, W, N_BANDS) float32

    Args:
        data: bytes from the data section of a qs_daemon frame
              (everything after the 24-byte frame_id/ts_us/data_size header)

    Returns:
        cube: shape (height, width, n_bands), dtype float32
    """
    if len(data) < SUBHEADER_SIZE:
        raise QABFormatError(
            f"Data too short for sub-header: {len(data)} < {SUBHEADER_SIZE}"
        )

    n_bands, width, height, dtype_bytes = struct.unpack_from(SUBHEADER_FMT, data, 0)

    if dtype_bytes != 4:
        raise QABFormatError(f"Unsupported dtype: {dtype_bytes} (expected 4 = float32)")
    if n_bands == 0 or width == 0 or height == 0:
        raise QABFormatError(f"Invalid dimensions: bands={n_bands} W={width} H={height}")

    expected_bytes = SUBHEADER_SIZE + n_bands * width * height * 4
    if len(data) != expected_bytes:
        raise QABFormatError(
            f"Data size mismatch: got {len(data)}, "
            f"expected {expected_bytes} ({height}×{width}×{n_bands}×float32)"
        )

    raw = np.frombuffer(data, dtype="<f4", offset=SUBHEADER_SIZE)
    # Band-first layout → (H, W, N_BANDS)
    cube = raw.reshape(n_bands, height, width).transpose(1, 2, 0)
    return np.ascontiguousarray(cube)
