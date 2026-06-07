#!/usr/bin/env python3
"""
Pi5 7" 螢幕 Live Preview Display — 800×480 橫向
左側（520px）：相機預覽 + 左上 Huyes 標題
右側（280px）：手機 UI 風格的採集資訊面板

Run: python3 spectral_capture/preview_display.py
"""
import os, json, sqlite3, time
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
CJK_FONT     = '/usr/share/fonts/truetype/wqy/wqy-microhei.ttc'  # Latin + CJK

SCREEN_W  = 800
SCREEN_H  = 480
INFO_W    = 280
PREVIEW_W = SCREEN_W - INFO_W   # 520

# Phone UI colors
BG        = ( 15,  17,  11)   # #0f1117
CARD_BG   = ( 26,  29,  39)   # #1a1d27
STAT_BG   = ( 15,  17,  11)   # #0f1117
GREEN_LT  = (165, 214, 167)   # #a5d6a7
GREEN     = (102, 187, 106)   # #66bb6a
CYAN      = ( 77, 208, 225)   # #4dd0e1
TEXT      = (230, 234, 246)   # #e8eaf6
MUTED     = (120, 144, 156)   # #78909c
DARK_DOT  = ( 84, 110, 122)   # #546e7a
AMBER     = (255, 183,  77)   # #ffb74d
DIVIDER   = ( 30,  33,  48)   # #1e2130

PROCESS_MAP = {
    'washed': '水洗', 'natural': '日曬', 'honey': '蜜處理',
    'wet_hulled': '濕剝', 'anaerobic': '厭氧', 'other': '其他', 'unknown': '_'
}
ROAST_MAP = {
    'green': '生豆', 'light': '淺焙', 'medium_light': '中淺',
    'medium': '中焙', 'medium_dark': '中深', 'dark': '深焙'
}


def read_ppm():
    """Returns (pygame.Surface grayscale, np.ndarray HxWx3 RGB) or (None, None)."""
    try:
        data = PREVIEW_PPM.read_bytes()
        i = 0; lines = []
        while len(lines) < 3:
            j = data.index(b'\n', i); lines.append(data[i:j].decode()); i = j+1
        W, H = map(int, lines[1].split())
        rgb = np.frombuffer(data[i:], dtype=np.uint8).reshape(H, W, 3)
        # Convert to grayscale for display
        gray = (0.299 * rgb[:,:,0] + 0.587 * rgb[:,:,1] + 0.114 * rgb[:,:,2]).astype(np.uint8)
        gray_rgb = np.stack([gray, gray, gray], axis=2)  # pygame needs 3-channel
        return pygame.surfarray.make_surface(gray_rgb.swapaxes(0, 1)), rgb
    except Exception:
        return None, None


def detect_beans_rgb(rgb: np.ndarray) -> list:
    """Fast bean detection on RGB grayscale — runs at preview speed (~2fps)."""
    import cv2
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    _, mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, k)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE,
                             cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9)))
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    beans = []
    for cnt in cnts:
        area = cv2.contourArea(cnt)
        if 500 < area < 8000:
            x, y, w, h = cv2.boundingRect(cnt)
            beans.append((x, y, w, h))
    return beans


def read_json(path):
    try: return json.loads(path.read_text())
    except Exception: return {}


LOG_PATH = Path('/tmp/pipeline.log')

def read_recent_log(n=4):
    try:
        lines = LOG_PATH.read_text().splitlines()
        filtered = [l for l in lines
                    if not l.startswith('[uvc_fix]')
                    and not l.startswith('!name:')
                    and l.strip()]
        return filtered[-n:]
    except Exception:
        return []

def log_color(line):
    if '[detect]'  in line: return (77, 208, 225)   # cyan
    if '[process]' in line and 'done' in line: return (102, 187, 106)  # green
    if 'WARN'  in line or 'ERROR' in line: return (255, 183, 77)  # amber
    if '[capture]' in line: return (165, 214, 167)  # light green
    return (120, 144, 156)  # muted

def db_total_beans():
    try:
        if not DB_PATH.exists(): return 0
        conn = sqlite3.connect(str(DB_PATH))
        n = conn.execute('SELECT COUNT(*) FROM bean_spectra').fetchone()[0]
        conn.close(); return n
    except Exception: return 0


def rounded_rect(surf, color, rect, radius):
    pygame.draw.rect(surf, color, rect, border_radius=radius)


def main():
    pygame.init()
    screen = pygame.display.set_mode((SCREEN_W, SCREEN_H), pygame.FULLSCREEN)
    pygame.display.set_caption('Huyes Preview')
    pygame.mouse.set_visible(False)

    try:
        fXL = pygame.font.Font(CJK_FONT, 34)  # big stat numbers
        fL  = pygame.font.Font(CJK_FONT, 22)
        fM  = pygame.font.Font(CJK_FONT, 17)
        fS  = pygame.font.Font(CJK_FONT, 14)
        fXS = pygame.font.Font(CJK_FONT, 12)
    except Exception:
        fXL = pygame.font.SysFont('monospace', 34, bold=True)
        fL  = pygame.font.SysFont('monospace', 22, bold=True)
        fM  = pygame.font.SysFont('monospace', 17)
        fS  = pygame.font.SysFont('monospace', 14)
        fXS = pygame.font.SysFont('monospace', 12)

    clock = pygame.time.Clock()
    total_beans = 0
    last_db_t   = 0

    while True:
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT: return
            if ev.type == pygame.KEYDOWN and ev.key in (pygame.K_q, pygame.K_ESCAPE): return

        screen.fill(BG)

        # ── 左側：相機預覽 + 即時偵測框 ────────────────────────
        surf, rgb_arr = read_ppm()
        bean_boxes = []
        if surf and rgb_arr is not None:
            w, h = surf.get_size()
            scale = min(PREVIEW_W / w, SCREEN_H / h)
            nw, nh = int(w * scale), int(h * scale)
            scaled = pygame.transform.smoothscale(surf, (nw, nh))
            px0 = (PREVIEW_W - nw) // 2
            py0 = (SCREEN_H  - nh) // 2
            screen.blit(scaled, (px0, py0))

            # 偵測豆子並畫框（CPU 灰階 Otsu，~5ms）
            bean_boxes = detect_beans_rgb(rgb_arr)
            for (bx, by, bw, bh) in bean_boxes:
                # 把原始座標 scale 到螢幕座標
                sx = px0 + int(bx * scale)
                sy = py0 + int(by * scale)
                sw = int(bw * scale)
                sh = int(bh * scale)
                pygame.draw.rect(screen, GREEN, (sx, sy, sw, sh), 2)
        else:
            msg = fM.render("Waiting for camera...", True, MUTED)
            screen.blit(msg, ((PREVIEW_W - msg.get_width()) // 2, SCREEN_H // 2 - 10))

        # 預覽左上：標題 badge
        badge_surf = pygame.Surface((160, 28), pygame.SRCALPHA)
        badge_surf.fill((0, 0, 0, 140))
        screen.blit(badge_surf, (8, 8))
        title = fM.render("🌿 Huyes 採集平台", True, GREEN_LT)
        screen.blit(title, (12, 10))

        # 左右分隔線
        pygame.draw.line(screen, DIVIDER, (PREVIEW_W, 0), (PREVIEW_W, SCREEN_H), 1)

        # ── 右側：資訊面板 ──────────────────────────────────────
        x0   = PREVIEW_W
        pad  = 10
        xL   = x0 + pad           # left edge of content
        xR   = SCREEN_W - pad     # right edge
        y    = 8

        status    = read_json(STATUS_JSON)
        meta      = read_json(META_JSON)
        running   = META_JSON.exists()
        start_t   = meta.get('start_epoch', 0)
        frame_id  = status.get('frame_id', 0)
        fps_val   = status.get('fps', 0.0)

        if time.time() - last_db_t > 4:
            total_beans = db_total_beans()
            last_db_t   = time.time()

        # ── Card 1: 狀態 + 時間 ────────────────────────────────
        rounded_rect(screen, CARD_BG, (x0 + 6, y, INFO_W - 12, 46), 8)
        # Status dot
        dot_col = GREEN if running else DARK_DOT
        pygame.draw.circle(screen, dot_col, (xL + 7, y + 14), 5)
        status_lbl = fS.render("採集中" if running else "待機", True, dot_col)
        screen.blit(status_lbl, (xL + 16, y + 6))
        # Current time
        now_str = datetime.now().strftime('%H:%M:%S')
        t_surf = fS.render(now_str, True, CYAN)
        screen.blit(t_surf, (xR - t_surf.get_width(), y + 6))
        # Elapsed
        if running and start_t > 0:
            es = int(time.time() - start_t)
            elapsed = f"+{es//3600:02d}:{(es%3600)//60:02d}:{es%60:02d}"
        else:
            elapsed = "+00:00:00"
        el_surf = fXS.render(elapsed, True, MUTED)
        screen.blit(el_surf, (xL + 16, y + 26))
        y += 52

        # ── Card 2: Stats (2欄) ─────────────────────────────────
        rounded_rect(screen, CARD_BG, (x0 + 6, y, INFO_W - 12, 62), 8)
        cw = (INFO_W - 12 - pad*2 - 6) // 2   # column width
        live_count = str(len(bean_boxes)) if bean_boxes is not None else "_"
        for i, (val, lbl, col) in enumerate([
            (str(total_beans), "累計豆子",   GREEN_LT),
            (live_count,       "即時偵測",   GREEN if bean_boxes else MUTED),
        ]):
            cx = xL + i * (cw + 6)
            rounded_rect(screen, STAT_BG, (cx, y + 6, cw, 50), 6)
            v_surf = fXL.render(val, True, col)
            # Scale down if too wide
            if v_surf.get_width() > cw - 8:
                v_surf = pygame.transform.smoothscale(v_surf, (cw - 8, v_surf.get_height() * (cw - 8) // v_surf.get_width()))
            screen.blit(v_surf, (cx + 6, y + 10))
            l_surf = fXS.render(lbl, True, MUTED)
            screen.blit(l_surf, (cx + 6, y + 44))
        y += 68

        # ── Card 3: FPS 小列 ────────────────────────────────────
        fps_lbl = fXS.render(f"fps  {fps_val:.1f}", True, MUTED)
        screen.blit(fps_lbl, (xL, y))
        y += fps_lbl.get_height() + 6

        # ── 分隔線 ───────────────────────────────────────────────
        pygame.draw.line(screen, DIVIDER, (xL, y), (xR, y), 1)
        y += 8

        # ── Card 4: Metadata ─────────────────────────────────────
        rounded_rect(screen, CARD_BG, (x0 + 6, y, INFO_W - 12, 118), 8)
        origin  = meta.get('origin', '_')
        process = PROCESS_MAP.get(meta.get('process', ''), '_')
        roast   = ROAST_MAP.get(meta.get('roast_level', ''), '_')
        batch   = meta.get('batch_id', '_')
        capdate = meta.get('capture_date', '_')

        def meta_row(label, value, val_color=TEXT):
            nonlocal y
            lbl_s = fXS.render(label, True, MUTED)
            val_s = fXS.render(value[:16], True, val_color)
            screen.blit(lbl_s, (xL + 6, y + 4))
            screen.blit(val_s, (xR - val_s.get_width() - 4, y + 4))
            # thin divider
            dh = lbl_s.get_height() + 8
            pygame.draw.line(screen, DIVIDER,
                (xL + 6, y + dh), (xR - 4, y + dh), 1)
            y += dh

        meta_row("產地", origin,  AMBER)
        meta_row("處理", process, TEXT)
        meta_row("烘焙", roast,   TEXT)
        meta_row("批次", batch,   TEXT)
        # Last row: no divider
        lbl_s = fXS.render("日期", True, MUTED)
        val_s = fXS.render(capdate[:16], True, TEXT)
        screen.blit(lbl_s, (xL + 6, y + 4))
        screen.blit(val_s, (xR - val_s.get_width() - 4, y + 4))
        y += lbl_s.get_height() + 10

        # ── Log 區塊 ─────────────────────────────────────────────
        log_lines = read_recent_log(4)
        remaining = SCREEN_H - y - 4
        if log_lines and remaining > 20:
            # section title
            sec = fXS.render("LOG", True, (50, 60, 80))
            screen.blit(sec, (xL, y))
            pygame.draw.line(screen, DIVIDER, (xL + sec.get_width() + 4, y + 5),
                             (xR, y + 5), 1)
            y += sec.get_height() + 4

            line_h = fXS.size("A")[1] + 2
            for line in log_lines:
                if y + line_h > SCREEN_H - 2:
                    break
                # Truncate long lines to fit INFO_W
                txt = line
                while fXS.size(txt)[0] > INFO_W - pad * 2 - 4 and len(txt) > 4:
                    txt = txt[:-1]
                surf = fXS.render(txt, True, log_color(line))
                screen.blit(surf, (xL, y))
                y += line_h

        pygame.display.flip()
        clock.tick(10)

    pygame.quit()


if __name__ == '__main__':
    main()
