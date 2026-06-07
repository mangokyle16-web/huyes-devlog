#!/usr/bin/env python3
"""
Pi5 7" 螢幕 Live Preview Display — 橫向佈局（800×480）
左側：相機 RGB 預覽
右側：採集資訊（metadata + frame + 時間 + 持續時間 + 累計豆子）

Run: python3 spectral_capture/preview_display.py
"""
import os
import json
import sqlite3
import time
from datetime import datetime
from pathlib import Path

os.environ.setdefault('WAYLAND_DISPLAY', 'wayland-0')
os.environ.setdefault('XDG_RUNTIME_DIR', '/run/user/1000')
if 'SDL_VIDEODRIVER' not in os.environ:
    os.environ['SDL_VIDEODRIVER'] = 'wayland'

import pygame
import numpy as np

PREVIEW_PPM  = Path('/dev/shm/preview.ppm')
STATUS_JSON  = Path('/dev/shm/preview_status.json')
META_JSON    = Path('/dev/shm/capture_meta.json')
DB_PATH      = Path('/home/kyle/KyleClaude/spectral_capture/data/beans.db')

# DSI-1 螢幕：800×480 橫向（目前 transform=normal）
SCREEN_W  = 800
SCREEN_H  = 480
INFO_W    = 280        # 右側資訊欄寬度
PREVIEW_W = SCREEN_W - INFO_W   # 520px 左側預覽

# 顏色
BG        = (15, 17, 11)
PANEL_BG  = (22, 24, 34)
GREEN     = (102, 187, 106)
CYAN      = (77, 208, 225)
AMBER     = (255, 183, 77)
TEXT      = (230, 234, 246)
MUTED     = (100, 120, 130)
DIVIDER   = (35, 40, 55)


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


def read_json(path):
    try:
        return json.loads(path.read_text())
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


def draw_right_panel(screen, fonts, status, meta, total_beans, start_time, last_db_beans):
    """Draw the right info panel."""
    x0 = PREVIEW_W
    # Panel background
    pygame.draw.rect(screen, PANEL_BG, (x0, 0, INFO_W, SCREEN_H))
    pygame.draw.line(screen, DIVIDER, (x0, 0), (x0, SCREEN_H), 2)

    fL, fM, fS, fXS = fonts   # large, medium, small, xsmall
    pad = 14
    x = x0 + pad
    y = 14

    def txt(text, font, color=TEXT, align_right=False):
        nonlocal y
        surf = font.render(text, True, color)
        if align_right:
            screen.blit(surf, (x0 + INFO_W - pad - surf.get_width(), y))
        else:
            screen.blit(surf, (x, y))
        return surf.get_height()

    def divider():
        nonlocal y
        y += 6
        pygame.draw.line(screen, DIVIDER, (x, y), (x0 + INFO_W - pad, y), 1)
        y += 8

    # ── 狀態 + 時間 ───────────────────────────────────────
    running = META_JSON.exists()
    dot_color = GREEN if running else MUTED
    pygame.draw.circle(screen, dot_color, (x + 6, y + 8), 5)
    status_txt = fS.render("採集中" if running else "待機", True, dot_color)
    screen.blit(status_txt, (x + 16, y))
    now_str = datetime.now().strftime('%H:%M:%S')
    now_surf = fS.render(now_str, True, CYAN)
    screen.blit(now_surf, (x0 + INFO_W - pad - now_surf.get_width(), y))
    y += max(status_txt.get_height(), now_surf.get_height()) + 4

    # 持續時間
    if running and start_time > 0:
        elapsed_s = int(time.time() - start_time)
        h = elapsed_s // 3600
        m = (elapsed_s % 3600) // 60
        s = elapsed_s % 60
        elapsed_str = f"+{h:02d}:{m:02d}:{s:02d}"
        y += txt(elapsed_str, fS, MUTED)
    y += 2

    divider()

    # ── Frame + FPS ───────────────────────────────────────
    frame_id = status.get('frame_id', 0)
    fps      = status.get('fps', 0.0)

    frame_surf = fL.render(f"#{frame_id}", True, GREEN)
    screen.blit(frame_surf, (x, y))
    fps_surf = fXS.render(f"fps {fps:.1f}", True, MUTED)
    screen.blit(fps_surf, (x0 + INFO_W - pad - fps_surf.get_width(), y + frame_surf.get_height() - fps_surf.get_height()))
    y += frame_surf.get_height() + 4

    divider()

    # ── Metadata ──────────────────────────────────────────
    process_map = {
        'washed': '水洗', 'natural': '日曬', 'honey': '蜜處理',
        'wet_hulled': '濕剝', 'anaerobic': '厭氧', 'other': '其他', 'unknown': '_'
    }
    roast_map = {
        'green': '生豆', 'light': '淺焙', 'medium_light': '中淺',
        'medium': '中焙', 'medium_dark': '中深', 'dark': '深焙'
    }

    def meta_row(label, value, val_color=TEXT):
        nonlocal y
        lbl = fXS.render(label, True, MUTED)
        val = fXS.render(value[:18], True, val_color)  # truncate long values
        screen.blit(lbl, (x, y))
        screen.blit(val, (x0 + INFO_W - pad - val.get_width(), y))
        y += lbl.get_height() + 3

    origin   = meta.get('origin', '_')
    process  = process_map.get(meta.get('process', ''), meta.get('process', '_'))
    roast    = roast_map.get(meta.get('roast_level', ''), meta.get('roast_level', '_'))
    batch    = meta.get('batch_id', '_')
    cap_date = meta.get('capture_date', '_')

    meta_row("產地", origin, AMBER)
    meta_row("處理", process)
    meta_row("烘焙", roast)
    meta_row("批次", batch)
    meta_row("日期", cap_date)

    divider()

    # ── 累計豆子 ──────────────────────────────────────────
    beans_surf = fL.render(str(total_beans), True, GREEN)
    screen.blit(beans_surf, (x, y))
    unit = fS.render("顆", True, MUTED)
    screen.blit(unit, (x + beans_surf.get_width() + 4, y + beans_surf.get_height() - unit.get_height()))


def main():
    pygame.init()
    screen = pygame.display.set_mode((SCREEN_W, SCREEN_H), pygame.FULLSCREEN)
    pygame.display.set_caption('Huyes Preview')
    pygame.mouse.set_visible(False)

    # CJK font for Chinese characters
    CJK_FONT = '/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf'
    try:
        fL  = pygame.font.Font(CJK_FONT, 38)
        fM  = pygame.font.Font(CJK_FONT, 26)
        fS  = pygame.font.Font(CJK_FONT, 20)
        fXS = pygame.font.Font(CJK_FONT, 17)
    except Exception:
        # Fallback to system monospace if font not found
        fL  = pygame.font.SysFont('monospace', 38, bold=True)
        fM  = pygame.font.SysFont('monospace', 26, bold=True)
        fS  = pygame.font.SysFont('monospace', 20)
        fXS = pygame.font.SysFont('monospace', 17)
    fonts = (fL, fM, fS, fXS)

    clock      = pygame.time.Clock()
    total_beans = 0
    last_db_t  = 0
    last_db_beans = 0

    no_signal = pygame.Surface((PREVIEW_W, SCREEN_H))
    no_signal.fill(BG)
    msg = fS.render("Waiting for camera...", True, MUTED)
    no_signal.blit(msg, ((PREVIEW_W - msg.get_width()) // 2, SCREEN_H // 2 - 10))

    running = True
    while running:
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                running = False
            elif ev.type == pygame.KEYDOWN and ev.key in (pygame.K_q, pygame.K_ESCAPE):
                running = False

        screen.fill(BG)

        # ── 左側：相機預覽 ────────────────────────────────
        surf = read_ppm()
        if surf:
            w, h = surf.get_size()
            scale = min(PREVIEW_W / w, SCREEN_H / h)
            nw, nh = int(w * scale), int(h * scale)
            scaled = pygame.transform.smoothscale(surf, (nw, nh))
            x0 = (PREVIEW_W - nw) // 2
            y0 = (SCREEN_H - nh) // 2
            screen.blit(scaled, (x0, y0))
        else:
            screen.blit(no_signal, (0, 0))

        # ── 右側：資訊面板 ────────────────────────────────
        status = read_json(STATUS_JSON)
        meta   = read_json(META_JSON)
        start_time = meta.get('start_epoch', 0)

        now = time.time()
        if now - last_db_t > 4:
            total_beans = db_total_beans()
            last_db_t = now

        draw_right_panel(screen, fonts, status, meta, total_beans, start_time, last_db_beans)

        pygame.display.flip()
        clock.tick(10)

    pygame.quit()


if __name__ == '__main__':
    main()
