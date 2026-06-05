"""
Pi5 multispectral capture pipeline entry point.
Usage: python3 -m spectral_capture.main [--origin Ethiopia] [--roast green] [--stub] [--db PATH]

Thread architecture:
  FrameReader thread → main thread (detect + collect) → SQLite

Use --stub to run without a camera (synthetic QAB data via stub_qs_daemon.py).
"""
import argparse
import signal
import sys
import time
from pathlib import Path

import spectral_capture.config as cfg
from spectral_capture.pipeline.frame_reader import FrameReader
from spectral_capture.pipeline.bean_detector import detect_beans
from spectral_capture.storage.collector import Collector


def build_args():
    p = argparse.ArgumentParser(description="Pi5 multispectral bean capture")
    p.add_argument("--origin", default=cfg.ORIGIN)
    p.add_argument("--roast",  default=cfg.ROAST_LEVEL)
    p.add_argument("--fps",    type=int, default=cfg.TARGET_FPS)
    p.add_argument("--stub",   action="store_true",
                   help="Use synthetic data (no camera needed)")
    p.add_argument("--db",     default=str(cfg.DB_PATH))
    return p.parse_args()


def main():
    args = build_args()
    cfg.ORIGIN      = args.origin
    cfg.ROAST_LEVEL = args.roast

    if args.stub:
        stub_path = Path(__file__).parent / "tests/fixtures/stub_qs_daemon.py"
        daemon_cmd = [sys.executable, str(stub_path)]
        print("[main] stub mode — synthetic QAB data")
    else:
        daemon_cmd = None  # uses QS_DAEMON_BIN from config

    reader    = FrameReader(daemon_cmd=daemon_cmd)
    collector = Collector(db_path=Path(args.db))

    stop = False
    def _sig(s, f): nonlocal stop; stop = True
    signal.signal(signal.SIGINT,  _sig)
    signal.signal(signal.SIGTERM, _sig)

    reader.start()
    print(f"[main] capturing @ {args.fps} fps  origin={args.origin}  db={args.db}")
    print("[main] Ctrl+C to stop\n")

    total_frames = 0
    total_beans  = 0
    t_report     = time.time()

    while not stop:
        frame = reader.get_frame(timeout=0.5)
        if frame is None:
            continue

        beans = detect_beans(frame.cube)
        for b in beans:
            collector.insert_bean(
                frame_id=frame.frame_id,
                timestamp_us=frame.timestamp_us,
                cx=b.cx, cy=b.cy, area_px=b.area_px,
                spec_vec=b.spec_vec,
            )
        total_frames += 1
        total_beans  += len(beans)

        if total_frames % 30 == 0:
            elapsed = time.time() - t_report
            fps_actual = 30 / elapsed if elapsed > 0 else 0
            print(f"  frame={frame.frame_id:6d}  fps={fps_actual:.1f}  "
                  f"beans_this_frame={len(beans)}  total_beans={total_beans}")
            t_report = time.time()

    reader.stop()
    stats = collector.stats()
    collector.close()
    print(f"\n[main] done. {total_frames} frames, {total_beans} bean records.")
    print(f"[main] DB stats: {stats}")


if __name__ == "__main__":
    main()
