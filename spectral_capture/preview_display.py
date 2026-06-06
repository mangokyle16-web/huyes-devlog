#!/usr/bin/env python3
"""
Pi5 7" 螢幕 Live Preview Display
- 獨立程式，不依賴 capture_pipeline 或桌面 app
- 讀取 /dev/shm/preview.ppm（preview_daemon 寫入）
- 全螢幕 480×800 直立顯示
- 上方：相機 RGB 預覽
- 下方：frame 編號、開始時間、累計豆子數、fps

Run: python3 spectral_capture/preview_display.py
     （需要有顯示器，在 Pi5 桌面環境執行）
"""
import json
import sqlite3
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

PREVIEW_PPM    = Path('/dev/shm/preview.ppm')
STATUS_JSON    = Path('/dev/shm/preview_status.json')
DB_PATH        = Path('/home/kyle/KyleClaude/spectral_capture/data/beans.db')

# 7" DSI 螢幕：480×800 直立
SCREEN_W = 480
SCREEN_H = 800

# 預覽區佔上方 60%
PREVIEW_H = int(SCREEN_H * 0.60)
INFO_H    = SCREEN_H - PREVIEW_H

# 顏色
BG_COLOR      = (17, 17, 15)      # #0f1117
GREEN_COLOR   = (106, 187, 102)   # #66bb6a
CYAN_COLOR    = (225, 208, 77)    # #4dd0e1
TEXT_COLOR    = (230, 234, 246)   # #e8eaf6
MUTED_COLOR   = (121, 144, 156)   # #78909c
DARK_CARD     = (39, 29, 26)      # #1a1d27


def read_ppm(path: Path):
    """Read PPM file → numpy BGR array."""
    try:
        data = path.read_bytes()
        # Parse PPM header: P6\n<W> <H>\n<maxval>\n
        lines = []
        i = 0
        while len(lines) < 3:
            j = data.index(b'\n', i)
            lines.append(data[i:j].decode())
            i = j + 1
        W, H = map(int, lines[1].split())
        pixels = np.frombuffer(data[i:], dtype=np.uint8).reshape(H, W, 3)
        return cv2.cvtColor(pixels, cv2.COLOR_RGB2BGR)
    except Exception:
        return None


def read_status():
    try:
        return json.loads(STATUS_JSON.read_text())
    except Exception:
        return {}


def db_total_beans():
    try:
        if not DB_PATH.exists():
            return 0
        conn = sqlite3.connect(str(DB_PATH))
        n = conn.execute('SELECT COUNT(*) FROM bean_spectra').fetchone()[0]
        conn.close()
        return n
    except Exception:
        return 0


def draw_info_panel(canvas, status, total_beans, start_time):
    """Draw info panel in the bottom INFO_H area."""
    y0 = PREVIEW_H
    # Background
    canvas[y0:, :] = BG_COLOR

    frame_id = status.get('frame_id', 0)
    fps      = status.get('fps', 0.0)
    cur_time = status.get('time', '--:--:--')

    elapsed_s = int(time.time() - start_time)
    elapsed   = f"{elapsed_s//3600:02d}:{(elapsed_s%3600)//60:02d}:{elapsed_s%60:02d}"

    font   = cv2.FONT_HERSHEY_SIMPLEX
    pad    = 20
    y      = y0 + 28

    def txt(text, x, y, color=TEXT_COLOR, scale=0.55, thick=1):
        cv2.putText(canvas, text, (x, y), font, scale, color, thick, cv2.LINE_AA)

    # ── Row 1: Frame + FPS ─────────────────────────────────
    txt(f"Frame  #{frame_id}", pad, y, GREEN_COLOR, 0.65, 2)
    txt(f"FPS {fps:.1f}", SCREEN_W - 110, y, MUTED_COLOR, 0.55)
    y += 34

    # ── Row 2: 開始時間 ─────────────────────────────────────
    start_str = datetime.fromtimestamp(start_time).strftime('%H:%M:%S')
    txt(f"Start  {start_str}", pad, y, MUTED_COLOR, 0.55)
    txt(f"+{elapsed}", SCREEN_W - 110, y, MUTED_COLOR, 0.50)
    y += 30

    # ── Divider ────────────────────────────────────────────
    cv2.line(canvas, (pad, y), (SCREEN_W - pad, y), (40, 40, 50), 1)
    y += 18

    # ── Row 3: 累計豆子（大字）──────────────────────────────
    txt("累計豆子", pad, y, MUTED_COLOR, 0.48)
    y += 34
    cv2.putText(canvas, str(total_beans), (pad, y),
                font, 1.4, GREEN_COLOR, 2, cv2.LINE_AA)
    txt("顆", pad + 90, y, MUTED_COLOR, 0.55)

    # ── Status dot ────────────────────────────────────────
    dot_color = GREEN_COLOR if PREVIEW_PPM.exists() else (100, 100, 100)
    cv2.circle(canvas, (SCREEN_W - pad - 8, y0 + 16), 7, dot_color, -1)
    status_txt = "採集中" if PREVIEW_PPM.exists() else "待機"
    txt(status_txt, SCREEN_W - pad - 70, y0 + 22, dot_color, 0.48)


def main():
    window = 'Huyes Preview'
    cv2.namedWindow(window, cv2.WND_PROP_FULLSCREEN)
    cv2.setWindowProperty(window, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)

    canvas     = np.zeros((SCREEN_H, SCREEN_W, 3), dtype=np.uint8)
    start_time = time.time()
    last_db_check = 0
    total_beans   = 0

    # Placeholder preview
    no_signal = np.zeros((PREVIEW_H, SCREEN_W, 3), dtype=np.uint8)
    cv2.putText(no_signal, "Waiting for camera...",
                (60, PREVIEW_H // 2), cv2.FONT_HERSHEY_SIMPLEX,
                0.7, (80, 80, 80), 1, cv2.LINE_AA)

    while True:
        # 1. Load preview image
        preview = read_ppm(PREVIEW_PPM)
        if preview is None:
            canvas[:PREVIEW_H, :] = no_signal
        else:
            # Scale to fit SCREEN_W × PREVIEW_H (maintain aspect ratio, letterbox)
            h, w = preview.shape[:2]
            scale = min(SCREEN_W / w, PREVIEW_H / h)
            nw, nh = int(w * scale), int(h * scale)
            resized = cv2.resize(preview, (nw, nh))
            canvas[:PREVIEW_H, :] = 0
            x0 = (SCREEN_W - nw) // 2
            canvas[:nh, x0:x0+nw] = resized

        # 2. Status
        status = read_status()

        # 3. DB beans (update every 5s)
        if time.time() - last_db_check > 5:
            total_beans = db_total_beans()
            last_db_check = time.time()

        # 4. Draw info panel
        draw_info_panel(canvas, status, total_beans, start_time)

        cv2.imshow(window, canvas)
        if cv2.waitKey(300) & 0xFF == ord('q'):
            break

    cv2.destroyAllWindows()


if __name__ == '__main__':
    main()
