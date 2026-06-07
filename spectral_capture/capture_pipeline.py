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
CAPTURES_DIR = ROOT / 'spectral_capture/data/captures'   # 每批次子目錄
QUEUE_DIR   = Path('/tmp/qs_queue')
SDK         = ROOT / 'sdk_extract/linux-sdk-arm64/qssdk-20250817'
OPENCV_LIB  = SDK / 'libarm64/opencv/lib'
UVC_FIX     = ROOT / 'multispectral_demo/uvc_fix.so'

# preview_daemon 寫到 /dev/shm/
SHM_QS       = Path('/dev/shm/qs_latest.qs')
SHM_FRAME_ID = Path('/dev/shm/qs_frame_id.txt')

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
        ('capture_date', 'TEXT',    "''"),
        ('process',      'TEXT',    "'unknown'"),
        ('bean_type',    'TEXT',    "'green'"),
        ('batch_id',     'TEXT',    "''"),
        ('frame_n',      'INTEGER', '0'),
        ('has_beans',    'INTEGER', '1'),   # 1=有豆, 0=空幀
    ]
    for col, typ, defval in migrations:
        if col not in existing:
            conn.execute(f"ALTER TABLE bean_spectra ADD COLUMN {col} {typ} DEFAULT {defval}")

    # 3. Create indexes on new columns (safe after migration)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_batch_id     ON bean_spectra(batch_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_capture_date ON bean_spectra(capture_date)")

    conn.commit()
    return conn


def insert_beans(conn, qs_file, ts, beans, args, frame_n):
    rows = [(ts, args.date, qs_file, b['cx'], b['cy'], b['area'],
             float(b['spec'][0]), float(b['spec'][1]), float(b['spec'][2]),
             float(b['spec'][3]), float(b['spec'][4]),
             args.origin, args.process, args.roast, args.bean_type, args.batch_id,
             frame_n, 1)
            for b in beans]
    conn.executemany(
        'INSERT INTO bean_spectra '
        '(captured_at, capture_date, qs_file, bean_cx, bean_cy, area_px, '
        ' b0,b1,b2,b3,b4, origin,process,roast_level,bean_type,batch_id, frame_n,has_beans) '
        'VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', rows)
    conn.commit()


def detect_beans(cube, rgb_preview=None):
    """
    豆子偵測：優先用 FastSAM on Hailo-8（視覺精確），
    fallback 用 NDVI Otsu（光譜特徵）。
    cube: (H,W,5) float32 光譜 cube
    rgb_preview: (H,W,3) uint8 RGB，來自 /dev/shm/preview.ppm
    """
    import cv2

    beans_bbox = []  # list of (x, y, w, h)

    # ── 方法 1：FastSAM on Hailo-8 ─────────────────────────
    if rgb_preview is not None:
        try:
            sys.path.insert(0, str(ROOT))
            from spectral_capture.pipeline.fastsam_bean_detector import FastSAMBeanDetector
            if not hasattr(detect_beans, '_fastsam'):
                detect_beans._fastsam = FastSAMBeanDetector()
            detections = detect_beans._fastsam.detect(rgb_preview)
            beans_bbox = [d['bbox'] for d in detections]
            print(f'[detect] FastSAM: {len(beans_bbox)} 豆子', flush=True)
        except Exception as e:
            print(f'[detect] FastSAM 失敗，fallback Otsu: {e}', flush=True)
            beans_bbox = []

    # ── 方法 2：NDVI Otsu fallback ──────────────────────────
    if not beans_bbox:
        nir = cube[:, :, 0]
        nir_max = float(nir.max()) or 1.0
        nir_u8 = (nir / nir_max * 255).clip(0, 255).astype(np.uint8)
        _, mask = cv2.threshold(nir_u8, 0, 255,
                                cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, k)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE,
                                cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9)))
        cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for cnt in cnts:
            area = cv2.contourArea(cnt)
            if 500 < area < 8000:
                beans_bbox.append(cv2.boundingRect(cnt))

    # ── 提取光譜向量 ────────────────────────────────────────
    H, W = cube.shape[:2]
    beans = []
    for (x, y, bw, bh) in beans_bbox:
        x, y = max(0, x), max(0, y)
        bw = min(bw, W - x)
        bh = min(bh, H - y)
        if bw <= 0 or bh <= 0:
            continue
        roi = cube[y:y+bh, x:x+bw]
        spec = roi.mean(axis=(0, 1)).astype(np.float32)
        beans.append({
            'cx':   x + bw // 2,
            'cy':   y + bh // 2,
            'area': bw * bh,
            'bbox': (x, y, bw, bh),
            'spec': spec,
        })
    return sorted(beans, key=lambda b: b['cx'])


SHM_PREVIEW = Path('/dev/shm/preview.ppm')


def save_detection_image(cube, beans, capture_dir, frame_n, ts):
    """
    儲存灰階偵測圖片（RGB preview 轉灰階 + 豆子邊框）到 capture_dir。
    優先使用 /dev/shm/preview.ppm 作為底圖（實際相機影像）。
    """
    import cv2 as _cv2
    import datetime as _dt

    gray = None
    # 嘗試讀 preview.ppm（RGB → 灰階）
    try:
        data = SHM_PREVIEW.read_bytes()
        i = 0; lines = []
        while len(lines) < 3:
            j = data.index(b'\n', i); lines.append(data[i:j].decode()); i = j+1
        W, H = map(int, lines[1].split())
        rgb = np.frombuffer(data[i:], dtype=np.uint8).reshape(H, W, 3)
        gray = _cv2.cvtColor(rgb, _cv2.COLOR_RGB2GRAY)
        # 也存一份 preview 快照
        preview_path = capture_dir / f'frame_{frame_n:06d}_preview.jpg'
        _cv2.imwrite(str(preview_path), gray, [_cv2.IMWRITE_JPEG_QUALITY, 85])
    except Exception:
        pass

    # fallback：用 NDVI 波段
    if gray is None:
        nir = cube[:, :, 0]
        nir_max = float(nir.max()) or 1.0
        gray = (nir / nir_max * 255).clip(0, 255).astype(np.uint8)

    vis = _cv2.cvtColor(gray, _cv2.COLOR_GRAY2BGR)
    for b in beans:
        x, y, w, h = b['bbox']
        _cv2.rectangle(vis, (x, y), (x+w, y+h), (255, 255, 255), 2)
        _cv2.putText(vis, f"{b['area']}px", (x, y-4),
                     _cv2.FONT_HERSHEY_SIMPLEX, 0.35, (200, 200, 200), 1)
    # 右下角：幀資訊
    ts_str = _dt.datetime.fromtimestamp(ts).strftime('%H:%M:%S')
    info = f"frame={frame_n}  beans={len(beans)}  {ts_str}"
    H, W = vis.shape[:2]
    _cv2.putText(vis, info, (6, H-8),
                 _cv2.FONT_HERSHEY_SIMPLEX, 0.45, (180, 180, 180), 1)
    out_path = capture_dir / f'frame_{frame_n:06d}_detect.jpg'
    _cv2.imwrite(str(out_path), vis, [_cv2.IMWRITE_JPEG_QUALITY, 85])
    return out_path


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
    # 每批次獨立目錄
    capture_dir = CAPTURES_DIR / args.batch_id
    capture_dir.mkdir(parents=True, exist_ok=True)
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

    # 偵測 preview_daemon 是否在跑（有 /dev/shm/qs_frame_id.txt）
    use_shm = SHM_QS.exists() or SHM_FRAME_ID.exists()
    if use_shm:
        print('[pipeline] preview_daemon detected — reading from /dev/shm/ (no camera conflict)')
    else:
        print('[pipeline] no preview_daemon — using capture_one')

    last_frame_id = -1

    while not stop:
        t_cycle = time.time()
        ts = t_cycle

        if use_shm:
            # 等待 preview_daemon 寫入新幀（polling，每 0.5 秒檢查一次）
            print(f'[capture] frame {frame_n}: waiting for preview_daemon...', flush=True)
            waited = 0
            while not stop:
                try:
                    fid = int(SHM_FRAME_ID.read_text().strip())
                except Exception:
                    fid = last_frame_id
                if fid != last_frame_id and SHM_QS.exists():
                    last_frame_id = fid
                    break
                time.sleep(0.5)
                waited += 0.5
                if waited > 60:
                    print('[capture] TIMEOUT waiting for frame', flush=True)
                    break
            if stop:
                break
            # 複製 shm 檔案（避免 preview_daemon 覆寫中讀取）
            qs_path = QUEUE_DIR / f'frame_{frame_n:06d}.qs'
            import shutil
            shutil.copy2(str(SHM_QS), str(qs_path))
            sz = qs_path.stat().st_size
            print(f'[capture] frame {frame_n} from shm (fid={last_frame_id}, {sz:,}b)', flush=True)
        else:
            # 沒有 preview_daemon，用 capture_one（舊模式）
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
            # 讀 preview RGB 供 FastSAM 使用
            rgb_preview = None
            try:
                ppm_data = SHM_PREVIEW.read_bytes()
                i2 = 0; lines2 = []
                while len(lines2) < 3:
                    j2 = ppm_data.index(b'\n', i2)
                    lines2.append(ppm_data[i2:j2].decode()); i2 = j2+1
                W2, H2 = map(int, lines2[1].split())
                rgb_preview = np.frombuffer(ppm_data[i2:], dtype=np.uint8).reshape(H2, W2, 3)
            except Exception:
                pass
            beans = detect_beans(cube, rgb_preview)

            # 1. 儲存原始 .qs 到批次目錄（無論有無豆子）
            import shutil as _shutil
            saved_qs = capture_dir / f'frame_{frame_n:06d}.qs'
            _shutil.copy2(str(qs_path), str(saved_qs))

            # 2. 儲存灰階偵測圖片
            detect_img = save_detection_image(cube, beans, capture_dir, frame_n, ts)

            # 3. 寫入 DB（qs_file 指向永久路徑）
            if beans:
                insert_beans(conn, str(saved_qs), ts, beans, args, frame_n)
            else:
                # 空幀也記一筆（has_beans=0）供分析
                conn.execute(
                    'INSERT INTO bean_spectra '
                    '(captured_at, capture_date, qs_file, bean_cx, bean_cy, area_px, '
                    ' b0,b1,b2,b3,b4, origin,process,roast_level,bean_type,batch_id, frame_n,has_beans) '
                    'VALUES (?,?,?,0,0,0, 0,0,0,0,0, ?,?,?,?,?,?,0)',
                    (ts, args.date, str(saved_qs),
                     args.origin, args.process, args.roast, args.bean_type, args.batch_id, frame_n))
                conn.commit()

            total_beans += len(beans)
            print(f'[detect]  frame={frame_n} beans={len(beans)} total={total_beans} '
                  f'qs={saved_qs.name} img={detect_img.name}', flush=True)

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
