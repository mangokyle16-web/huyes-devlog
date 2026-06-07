#!/usr/bin/env python3
"""
快速影像採集腳本 — 只存圖，不做光譜處理。

每幀存：
  frame_NNNNNN.jpg   灰階 preview（~50KB，快速）
  frame_NNNNNN.qs    原始光譜檔（~3.8MB，可選）

速率：跟 preview_daemon 同步（~2fps）
用途：人工標注資料集

Run: python3 spectral_capture/capture_images.py --batch-id 20260607-label --save-qs
"""
import argparse
import signal
import time
import os
import sys
from pathlib import Path
import numpy as np
import cv2

ROOT        = Path('/home/kyle/KyleClaude')
CAPTURES    = ROOT / 'spectral_capture/data/captures'
SHM_PREVIEW = Path('/dev/shm/preview.ppm')
SHM_QS      = Path('/dev/shm/qs_latest.qs')
SHM_FRAME_ID = Path('/dev/shm/qs_frame_id.txt')


def read_preview_gray():
    try:
        data = SHM_PREVIEW.read_bytes()
        i = 0; lines = []
        while len(lines) < 3:
            j = data.index(b'\n', i); lines.append(data[i:j].decode()); i = j+1
        W, H = map(int, lines[1].split())
        rgb = np.frombuffer(data[i:], dtype=np.uint8).reshape(H, W, 3)
        return cv2.cvtColor(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), cv2.COLOR_BGR2GRAY)
    except Exception:
        return None


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--batch-id',  default='label-session', dest='batch_id')
    p.add_argument('--save-qs',   action='store_true', help='每幀也存 .qs 原始光譜')
    p.add_argument('--qs-every',  type=int, default=1,
                   help='每幾幀存一次 .qs（預設 1=每幀，10=每10幀，省空間）')
    args = p.parse_args()

    capture_dir = CAPTURES / args.batch_id
    capture_dir.mkdir(parents=True, exist_ok=True)

    stop = False
    def _sig(s, f): nonlocal stop; stop = True
    signal.signal(signal.SIGINT, _sig)
    signal.signal(signal.SIGTERM, _sig)

    print(f'[capture_images] 批次={args.batch_id}  save_qs={args.save_qs}  qs_every={args.qs_every}')
    print(f'[capture_images] 存到 {capture_dir}')
    print('[capture_images] Ctrl+C 停止\n')

    last_fid = -1
    frame_n  = 0

    while not stop:
        # 等 preview_daemon 寫入新幀
        try:
            fid = int(SHM_FRAME_ID.read_text().strip())
        except Exception:
            time.sleep(0.1)
            continue

        if fid == last_fid:
            time.sleep(0.05)
            continue

        last_fid = fid
        ts = time.time()

        # 存灰階 JPEG
        gray = read_preview_gray()
        if gray is not None:
            jpg_path = capture_dir / f'frame_{frame_n:06d}.jpg'
            cv2.imwrite(str(jpg_path), gray, [cv2.IMWRITE_JPEG_QUALITY, 90])
        else:
            print(f'[frame {frame_n:06d}] preview 讀取失敗', flush=True)

        # 存 .qs（可選，按 qs_every 頻率）
        if args.save_qs and (frame_n % args.qs_every == 0):
            try:
                import shutil
                qs_path = capture_dir / f'frame_{frame_n:06d}.qs'
                shutil.copy2(str(SHM_QS), str(qs_path))
            except Exception as e:
                print(f'[frame {frame_n:06d}] .qs 存失敗: {e}', flush=True)

        print(f'[frame {frame_n:06d}]  fid={fid}  jpg={jpg_path.name}', flush=True)
        frame_n += 1

    print(f'\n[capture_images] 完成，共 {frame_n} 幀存入 {capture_dir}')


if __name__ == '__main__':
    main()
