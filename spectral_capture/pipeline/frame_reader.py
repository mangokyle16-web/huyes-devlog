"""
Spawns qs_daemon subprocess, reads binary frame stream, puts CapturedFrame into queue.
Same subprocess daemon pattern as KyleClaude/seg_daemon.py.
"""
import struct
import threading
import queue
import subprocess
import sys
from dataclasses import dataclass
import numpy as np

from spectral_capture.pipeline.qab_parser import parse_qab, QABFormatError
from spectral_capture.config import QS_DAEMON_BIN, QSBS_PATH, TARGET_FPS

HEADER_FMT  = "<QqQ"   # frame_id(u64) + timestamp_us(i64) + qab_size(u64)
HEADER_SIZE = struct.calcsize(HEADER_FMT)
MAX_QUEUE   = 4  # drop oldest if full to prevent memory growth


@dataclass
class CapturedFrame:
    frame_id:     int
    timestamp_us: int
    cube:         np.ndarray  # (H, W, 5) float32


class FrameReader:
    def __init__(self, daemon_cmd: list = None):
        if daemon_cmd is None:
            daemon_cmd = [str(QS_DAEMON_BIN), str(QSBS_PATH), str(TARGET_FPS)]
        self._cmd      = daemon_cmd
        self._queue    = queue.Queue(maxsize=MAX_QUEUE)
        self._proc     = None
        self._thread   = None
        self._stop_evt = threading.Event()

    def start(self):
        self._proc = subprocess.Popen(
            self._cmd,
            stdout=subprocess.PIPE,
            stderr=sys.stderr,
            bufsize=0,
        )
        self._thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._thread.start()

    def get_frame(self, timeout: float = 1.0):
        """Returns CapturedFrame or None if timeout expires."""
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def stop(self):
        self._stop_evt.set()
        if self._proc:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait()
        if self._thread:
            self._thread.join(timeout=3)

    def _reader_loop(self):
        buf = self._proc.stdout
        while not self._stop_evt.is_set():
            header_bytes = self._read_exact(buf, HEADER_SIZE)
            if not header_bytes:
                break
            frame_id, ts_us, qab_size = struct.unpack(HEADER_FMT, header_bytes)
            qab_bytes = self._read_exact(buf, qab_size)
            if not qab_bytes:
                break
            try:
                cube = parse_qab(bytes(qab_bytes))
            except QABFormatError as e:
                print(f"[FrameReader] parse error frame {frame_id}: {e}", file=sys.stderr)
                continue
            frame = CapturedFrame(frame_id=frame_id, timestamp_us=ts_us, cube=cube)
            if self._queue.full():
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    pass
            self._queue.put_nowait(frame)

    @staticmethod
    def _read_exact(stream, n: int):
        """Read exactly n bytes from stream, handling partial reads. Returns None on EOF."""
        data = b""
        while len(data) < n:
            chunk = stream.read(n - len(data))
            if not chunk:
                return None
            data += chunk
        return data
