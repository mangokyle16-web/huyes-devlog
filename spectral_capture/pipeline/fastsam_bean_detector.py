"""
FastSAM on Hailo-8 NPU — 咖啡豆偵測器

輸入：RGB 影像（任意尺寸）
輸出：list of dict {'bbox':(x,y,w,h), 'cx':int, 'cy':int, 'score':float, 'area':int}

濾波邏輯：
  1. 面積過濾：MIN_AREA ~ MAX_AREA px²（太小=雜訊，太大=背景區塊）
  2. 長寬比過濾：≤ MAX_ASPECT（豆子是橢圓形，不應過長）
  3. 亮度過濾：排除 IR LED 亮點（mean brightness > BRIGHT_THRESH）
"""
import sys
import numpy as np
import cv2
from pathlib import Path

FASTSAM_HEF    = Path('/home/kyle/KyleClaude/fastsam_s_v3.hef')
FASTSAM_SRC    = Path('/home/kyle/KyleClaude')

CONF_THRESH    = 0.50   # 信心門檻（越高越嚴格）
IOU_THRESH     = 0.15
MIN_AREA       = 600    # px²，原始影像座標（太小=雜訊）
MAX_AREA       = 15000  # px²（太大=背景或 LED 光暈）
MAX_ASPECT     = 2.5    # max(w,h)/min(w,h)（豆子是橢圓，不應太長）
BRIGHT_THRESH  = 160    # 平均亮度超過此值 → IR LED 亮點，排除（調低）


class FastSAMBeanDetector:
    """
    使用 FastSAM on Hailo-8 偵測咖啡豆。
    在背景 worker thread 持有 Hailo context（同 fastsam_hailo.py 模式）。
    初始化需要 ~5 秒（NPU warmup）。
    """

    def __init__(self, hef_path: str = str(FASTSAM_HEF)):
        if str(FASTSAM_SRC) not in sys.path:
            sys.path.insert(0, str(FASTSAM_SRC))
        from fastsam_hailo import FastSAMHailo
        self._model = FastSAMHailo(hef_path)
        print(f"[FastSAMBeanDetector] 就緒 hef={hef_path}")

    def detect(self, img_rgb: np.ndarray) -> list:
        """
        img_rgb: np.ndarray (H, W, 3) uint8 RGB
        Returns: list of {'bbox':(x,y,w,h), 'cx', 'cy', 'score', 'area'}
        """
        if img_rgb is None or img_rgb.size == 0:
            return []

        img_bgr  = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR)
        img_gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)

        try:
            _, boxes_px, scores = self._model.predict(
                img_bgr, conf=CONF_THRESH, iou_thr=IOU_THRESH, max_det=200)
        except Exception as e:
            print(f"[FastSAMBeanDetector] predict error: {e}")
            return []

        if len(boxes_px) == 0:
            return []

        beans = []
        for box, score in zip(boxes_px, scores):
            x1, y1, x2, y2 = box
            bw = max(int(x2 - x1), 1)
            bh = max(int(y2 - y1), 1)
            area = bw * bh

            # 1. 面積過濾
            if not (MIN_AREA < area < MAX_AREA):
                continue

            # 2. 長寬比過濾（豆子接近橢圓）
            if max(bw, bh) / min(bw, bh) > MAX_ASPECT:
                continue

            # 3. 亮度過濾：排除 IR LED 亮點
            ry1, ry2 = max(0, int(y1)), min(img_gray.shape[0], int(y2))
            rx1, rx2 = max(0, int(x1)), min(img_gray.shape[1], int(x2))
            if ry2 > ry1 and rx2 > rx1:
                roi_mean = img_gray[ry1:ry2, rx1:rx2].mean()
                if roi_mean > BRIGHT_THRESH:
                    continue

            cx = int((x1 + x2) / 2)
            cy = int((y1 + y2) / 2)
            beans.append({
                'bbox':  (int(x1), int(y1), bw, bh),
                'cx':    cx,
                'cy':    cy,
                'score': float(score),
                'area':  area,
            })

        return sorted(beans, key=lambda b: b['cx'])

    def close(self):
        self._model.close()
