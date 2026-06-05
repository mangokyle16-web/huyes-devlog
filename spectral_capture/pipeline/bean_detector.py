"""
Coffee bean detection using NIR band (840nm) Otsu threshold.
Green PVC belt: NIR ~3.5 radiance (high). Coffee beans: NIR ~1.2 (low). High contrast.
Values are calibrated radiance from qabToGray() — not normalized 0-1.
Otsu threshold is scale-invariant so it works regardless of absolute range.
"""
import cv2
import numpy as np
from dataclasses import dataclass
from spectral_capture.config import NIR_BAND_IDX, BEAN_MIN_AREA_PX, BEAN_MAX_AREA_PX


@dataclass
class BeanDetection:
    cx: int               # center x (pixels)
    cy: int               # center y (pixels)
    bbox: tuple           # (x, y, w, h)
    area_px: int
    spec_vec: np.ndarray  # shape (5,) float32, mean reflectance per band


def detect_beans(cube: np.ndarray) -> list[BeanDetection]:
    """
    Args:
        cube: (H, W, 5) float32 [0,1] from parse_qab()
    Returns:
        list of BeanDetection sorted by cx (left→right)
    """
    # Normalize NIR band to uint8 for OpenCV threshold (scale-invariant)
    nir_f = cube[:, :, NIR_BAND_IDX]
    nir_max = float(nir_f.max()) or 1.0
    nir = (nir_f / nir_max * 255).clip(0, 255).astype(np.uint8)

    # Otsu threshold: beans (dark) vs belt background (bright)
    _, mask = cv2.threshold(nir, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    # Morphology: remove noise, fill bean interior holes
    k_open  = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    k_close = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN,  k_open)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k_close)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    results = []
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if not (BEAN_MIN_AREA_PX < area < BEAN_MAX_AREA_PX):
            continue
        x, y, w, h = cv2.boundingRect(cnt)
        cx, cy = x + w // 2, y + h // 2
        roi = cube[y:y+h, x:x+w]           # (h, w, 5)
        spec_vec = roi.mean(axis=(0, 1))    # (5,) mean reflectance per band
        results.append(BeanDetection(
            cx=cx, cy=cy,
            bbox=(x, y, w, h),
            area_px=int(area),
            spec_vec=spec_vec.astype(np.float32),
        ))
    return sorted(results, key=lambda b: b.cx)
