import sys
import time
import numpy as np
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from spectral_capture.pipeline.frame_reader import FrameReader, CapturedFrame

STUB = str(Path(__file__).parent / "fixtures" / "stub_qs_daemon.py")

def test_frame_reader_produces_frames():
    reader = FrameReader(daemon_cmd=[sys.executable, STUB])
    reader.start()
    frame = reader.get_frame(timeout=3.0)
    reader.stop()
    assert frame is not None
    assert isinstance(frame, CapturedFrame)
    assert frame.frame_id >= 0
    assert frame.timestamp_us > 0

def test_frame_reader_cube_shape():
    reader = FrameReader(daemon_cmd=[sys.executable, STUB])
    reader.start()
    frame = reader.get_frame(timeout=3.0)
    reader.stop()
    assert frame.cube.shape == (1200, 1600, 5)
    assert frame.cube.dtype == np.float32

def test_frame_reader_stop_is_clean():
    import numpy as np
    reader = FrameReader(daemon_cmd=[sys.executable, STUB])
    reader.start()
    reader.get_frame(timeout=3.0)
    reader.stop()
    assert not reader._thread.is_alive()
