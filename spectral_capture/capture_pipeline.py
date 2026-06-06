#!/usr/bin/env python3
"""
Async capture pipeline for Pi5 multispectral data collection.

capture_one grabs .qs files fast (~0.5s each).
qs_file_processor converts to spectral vectors (~20s each).
Results written to SQLite for Siamese network training.

Run: python3 spectral_capture/capture_pipeline.py --origin 台灣阿里山 --process washed --roast green --batch-id 20260607-001
"""
import subprocess, struct, time, os, sys, signal, argparse, sqlite3
import datetime
from pathlib import Path
import numpy as np

ROOT        = Path('/home/kyle/KyleClaude')
QSBS        = ROOT / 'spectral_capture/capture/msi.qsbs'
CAPTURE_ONE = ROOT / 'multispectral_demo/build/capture_one'
PROCESSOR   = ROOT / 'spectral_capture/capture/qs_file_processor'
DB_PATH     = ROOT / 'spectral_capture/data/beans.db'
QUEUE_DIR   = Path('/tmp/qs_queue')
SDK         = ROOT / 'sdk_extract/linux-sdk-arm64/qssdk-20250817'
OPENCV_LIB  = SDK / 'libarm64/opencv/lib'
UVC_FIX     = ROOT / 'multispectral_demo/uvc_fix.so'

CAPTURE_INTERVAL_S = 25


def init_db(db_path):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)

    # 1. Create table (minimal schema, always safe)
    conn.execute('''
        CREATE TABLE IF NOT EXISTS bean_spectra (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            captured_at REAL    NOT NULL,
            qs_file     TEXT    NOT NULL,
            bean_cx     INTEGER NOT NULL,
            bean_cy     INTEGER NOT NULL,
            area_px     INTEGER NOT NULL,
            b0 REAL, b1 REAL, b2 REAL, b3 REAL, b4 REAL,
            origin      TEXT DEFAULT '',
            roast_level TEXT DEFAULT 'green',
            label       TEXT DEFAULT 'unknown'
        )
    ''')
    conn.execute("CREATE INDEX IF NOT EXISTS idx_captured_at ON bean_spectra(captured_at)")

    # 2. Migrate: add new columns if missing
    existing = {row[1] for row in conn.execute("PRAGMA table_info(bean_spectra)")}
    migrations = [
        ('capture_date', 'TEXT', "''"),
        ('process',      'TEXT', "'unknown'"),
        ('bean_type',    'TEXT', "'green'"),
        ('batch_id',     'TEXT', "''"),
    ]
    for col, typ, defval in migrations:
        if col not in existing:
            conn.execute(f"ALTER TABLE bean_spectra ADD COLUMN {col} {typ} DEFAULT {defval}")

    # 3. Create indexes on new columns (safe after migration)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_batch_id     ON bean_spectra(batch_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_capture_date ON bean_spectra(capture_date)")

    conn.commit()
    return conn


def insert_beans(conn, qs_file, ts, beans, args):
    rows = [(ts, args.date, qs_file, b['cx'], b['cy'], b['area'],
             float(b['spec'][0]), float(b['spec'][1]), float(b['spec'][2]),
             float(b['spec'][3]), float(b['spec'][4]),
             args.origin, args.process, args.roast, args.bean_type, args.batch_id)
            for b in beans]
    conn.executemany(
        'INSERT INTO bean_spectra '
        '(captured_at, capture_date, qs_file, bean_cx, bean_cy, area_px, '
        ' b0,b1,b2,b3,b4, origin,process,roast_level,bean_type,batch_id) '
        'VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', rows)
    conn.commit()


def detect_beans(cube):
    import cv2
    nir = cube[:, :, 0]
    nir_max = float(nir.max()) or 1.0
    nir_u8 = (nir / nir_max * 255).clip(0, 255).astype(np.uint8)
    _, mask = cv2.threshold(nir_u8, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, k)
    k2 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k2)
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    beans = []
    for cnt in cnts:
        area = cv2.contourArea(cnt)
        if not (500 < area < 8000):
            continue
        x, y, w, h = cv2.boundingRect(cnt)
        roi = cube[y:y+h, x:x+w]
        spec = roi.mean(axis=(0, 1)).astype(np.float32)
        beans.append({'cx': x+w//2, 'cy': y+h//2, 'area': int(area), 'spec': spec})
    return sorted(beans, key=lambda b: b['cx'])


def process_qs_file(qs_path, capture_env):
    result = subprocess.run(
        [str(PROCESSOR), str(QSBS), str(qs_path)],
        env=capture_env, capture_output=True)
    if result.returncode != 0:
        print(f'[processor] ERROR: {result.stderr.decode()[:200]}', flush=True)
        return None
    data = result.stdout
    if len(data) < 16:
        return None
    n_bands, W, H, dtype = struct.unpack_from('<IIII', data, 0)
    expected = 16 + n_bands * W * H * 4
    if len(data) != expected:
        print(f'[processor] size mismatch: {len(data)} vs {expected}', flush=True)
        return None
    raw = np.frombuffer(data, dtype='<f4', offset=16)
    cube = raw.reshape(n_bands, H, W).transpose(1, 2, 0)
    return np.ascontiguousarray(cube)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--origin',    default='unknown')
    p.add_argument('--process',   default='unknown')
    p.add_argument('--roast',     default='green')
    p.add_argument('--bean-type', default='green', dest='bean_type')
    p.add_argument('--batch-id',  default='batch-001', dest='batch_id')
    p.add_argument('--date',      default=datetime.date.today().isoformat())
    p.add_argument('--interval',  type=float, default=CAPTURE_INTERVAL_S)
    args = p.parse_args()

    QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    conn = init_db(DB_PATH)

    stop = False
    def _sig(s, f):
        nonlocal stop
        stop = True
    signal.signal(signal.SIGINT, _sig)
    signal.signal(signal.SIGTERM, _sig)

    ld_lib = f'{SDK}:{OPENCV_LIB}:{os.environ.get("LD_LIBRARY_PATH", "")}'
    capture_env = {**os.environ,
                   'LD_PRELOAD': str(UVC_FIX),
                   'LD_LIBRARY_PATH': ld_lib}

    frame_n = 0
    total_beans = 0
    print(f'[pipeline] origin={args.origin} process={args.process} '
          f'roast={args.roast} bean_type={args.bean_type} '
          f'batch={args.batch_id} date={args.date} interval={args.interval}s')
    print('[pipeline] Ctrl+C to stop')

    while not stop:
        t_cycle = time.time()
        ts = t_cycle
        qs_path = QUEUE_DIR / f'frame_{frame_n:06d}.qs'

        print(f'[capture] frame {frame_n}...', flush=True)
        cap = subprocess.run(
            [str(CAPTURE_ONE), str(QSBS), str(qs_path)],
            env=capture_env, capture_output=True, timeout=30)
        if cap.returncode != 0 or not qs_path.exists():
            print(f'[capture] FAILED: {cap.stderr.decode()[:100]}', flush=True)
            time.sleep(2)
            continue
        sz = qs_path.stat().st_size
        print(f'[capture] saved {qs_path.name} ({sz:,}b)', flush=True)

        print('[process] qsToQab + 5 indices (may take ~20s)...', flush=True)
        t_proc = time.time()
        cube = process_qs_file(qs_path, capture_env)
        proc_t = time.time() - t_proc
        print(f'[process] done in {proc_t:.1f}s', flush=True)

        if cube is not None:
            beans = detect_beans(cube)
            insert_beans(conn, str(qs_path), ts, beans, args)
            total_beans += len(beans)
            print(f'[detect]  frame={frame_n} beans={len(beans)} total={total_beans}', flush=True)

        qs_path.unlink(missing_ok=True)
        frame_n += 1

        elapsed = time.time() - t_cycle
        wait = max(0, args.interval - elapsed)
        if wait > 0 and not stop:
            print(f'[pipeline] next capture in {wait:.1f}s', flush=True)
            time.sleep(wait)

    stats = conn.execute(
        'SELECT COUNT(*), MIN(capture_date), MAX(capture_date) FROM bean_spectra'
    ).fetchone()
    conn.close()
    print(f'\n[pipeline] done. {frame_n} frames, {total_beans} beans. DB: {stats}')


if __name__ == '__main__':
    main()
