"""
Mimics qs_daemon stdout binary output using synthetic QAB data.
Used for testing FrameReader on Mac without a camera.
"""
import sys
import struct
import time

# Allow import from project root
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../..'))

from spectral_capture.tests.fixtures.make_fake_qab import make_fake_qab
from spectral_capture.config import TARGET_FPS

FRAME_INTERVAL = 1.0 / TARGET_FPS

def main():
    out = sys.stdout.buffer
    frame_id = 0
    while True:
        t0 = time.time()
        qab = make_fake_qab(n_beans=5, seed=frame_id % 10)
        ts_us = int(time.time() * 1e6)
        header = struct.pack("<QqQ", frame_id, ts_us, len(qab))
        out.write(header)
        out.write(qab)
        out.flush()
        frame_id += 1
        elapsed = time.time() - t0
        sleep = FRAME_INTERVAL - elapsed
        if sleep > 0:
            time.sleep(sleep)

if __name__ == "__main__":
    main()
