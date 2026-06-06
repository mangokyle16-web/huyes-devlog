#!/usr/bin/env python3
"""
Pi5 7" 螢幕 Live Preview Display（pygame 版）
- 獨立程式，不依賴 capture_pipeline 或桌面 app
- 讀取 /dev/shm/preview.ppm（preview_daemon 寫入）
- 全螢幕 480×800 直立顯示（Wayland/KMS）

Run: python3 spectral_capture/preview_display.py
"""
import os
import json
import sqlite3
import time
from datetime import datetime
from pathlib import Path

# ── Wayland / display 環境設定 ───────────────────────────
os.environ.setdefault('WAYLAND_DISPLAY', 'wayland-0')
os.environ.setdefault('XDG_RUNTIME_DIR', '/run/user/1000')
# 讓 SDL2 優先嘗試 Wayland，退回 KMS framebuffer
if 'SDL_VIDEODRIVER' not in os.environ:
    os.environ['SDL_VIDEODRIVER'] = 'wayland'

import pygame
import numpy as np

PREVIEW_PPM  = Path('/dev/shm/preview.ppm')
STATUS_JSON  = Path('/dev/shm/preview_status.json')
DB_PATH      = Path('/home/kyle/KyleClaude/spectral_capture/data/beans.db')

SCREEN_W  = 480
SCREEN_H  = 800
PREVIEW_H = int(SCREEN_H * 0.60)   # 480×480 上方預覽
INFO_H    = SCREEN_H - PREVIEW_H   # 480×320 下方資訊

# Colours (RGB)
BG         = (15, 17, 11)
GREEN      = (102, 187, 106)
CYAN       = (77, 208, 225)
TEXT       = (230, 234, 246)
MUTED      = (121, 144, 156)
CARD_BG    = (27, 29, 39)


def read_ppm():
    try:
        data = PREVIEW_PPM.read_bytes()
        i = 0
        lines = []
        while len(lines) < 3:
            j = data.index(b'\n', i)
            lines.append(data[i:j].decode())
            i = j + 1
        W, H = map(int, lines[1].split())
        pixels = np.frombuffer(data[i:], dtype=np.uint8).reshape(H, W, 3)
        return pygame.surfarray.make_surface(pixels.swapaxes(0, 1))
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


def main():
    pygame.init()
    screen = pygame.display.set_mode((SCREEN_W, SCREEN_H), pygame.FULLSCREEN)
    pygame.display.set_caption('Huyes Preview')
    pygame.mouse.set_visible(False)

    font_large  = pygame.font.SysFont('monospace', 36, bold=True)
    font_medium = pygame.font.SysFont('monospace', 24)
    font_small  = pygame.font.SysFont('monospace', 20)

    clock       = pygame.time.Clock()
    start_time  = time.time()
    total_beans = 0
    last_db_t   = 0

    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_q, pygame.K_ESCAPE):
                    running = False

        screen.fill(BG)

        # ── Preview image ────────────────────────────────
        surf = read_ppm()
        if surf:
            # Scale to fit SCREEN_W × PREVIEW_H
            w, h = surf.get_size()
            scale = min(SCREEN_W / w, PREVIEW_H / h)
            nw, nh = int(w * scale), int(h * scale)
            scaled = pygame.transform.smoothscale(surf, (nw, nh))
            x0 = (SCREEN_W - nw) // 2
            y0 = (PREVIEW_H - nh) // 2
            screen.blit(scaled, (x0, y0))
        else:
            msg = font_small.render('Waiting for camera...', True, MUTED)
            screen.blit(msg, (80, PREVIEW_H // 2 - 10))

        # ── Divider ──────────────────────────────────────
        pygame.draw.line(screen, (40, 40, 55),
                         (0, PREVIEW_H), (SCREEN_W, PREVIEW_H), 2)

        # ── Info panel ───────────────────────────────────
        status = read_status()
        frame_id = status.get('frame_id', 0)
        fps      = status.get('fps', 0.0)

        # DB update every 5s
        now = time.time()
        if now - last_db_t > 5:
            total_beans = db_total_beans()
            last_db_t = now

        elapsed_s = int(now - start_time)
        elapsed   = f"{elapsed_s//3600:02d}:{(elapsed_s%3600)//60:02d}:{elapsed_s%60:02d}"
        start_str = datetime.fromtimestamp(start_time).strftime('%H:%M:%S')

        pad = 20
        y = PREVIEW_H + 20

        # Frame + FPS
        txt = font_medium.render(f"Frame  #{frame_id}", True, GREEN)
        screen.blit(txt, (pad, y))
        txt2 = font_small.render(f"FPS {fps:.1f}", True, MUTED)
        screen.blit(txt2, (SCREEN_W - 90, y + 4))
        y += 36

        # Start time + elapsed
        txt = font_small.render(f"Start  {start_str}  +{elapsed}", True, MUTED)
        screen.blit(txt, (pad, y))
        y += 32

        # Divider
        pygame.draw.line(screen, (40, 40, 55), (pad, y), (SCREEN_W - pad, y), 1)
        y += 18

        # Bean count (big)
        label = font_small.render("累計豆子", True, MUTED)
        screen.blit(label, (pad, y))
        y += 28
        count_txt = font_large.render(str(total_beans), True, GREEN)
        screen.blit(count_txt, (pad, y))
        unit = font_medium.render("顆", True, MUTED)
        screen.blit(unit, (pad + count_txt.get_width() + 8, y + 8))

        # Status dot
        dot_color = GREEN if PREVIEW_PPM.exists() else MUTED
        pygame.draw.circle(screen, dot_color,
                           (SCREEN_W - pad - 8, PREVIEW_H + 16), 7)

        pygame.display.flip()
        clock.tick(10)   # 10fps UI refresh

    pygame.quit()


if __name__ == '__main__':
    main()
