"""Global-motion-compensated bean tracker for conveyor line counting.

At 2-3 fps the conveyor moves coffee beans about one box-width per frame.
That means a bean usually has little or no overlap with itself in consecutive
frames, so per-bean IOU or centroid tracking fragments tracks and double-counts
or misses crossings.

This tracker uses the validated offline approach instead: estimate the global
left-to-right conveyor motion from the frame-to-frame x-center histogram
cross-correlation, predict every live track forward by that shared velocity,
match detections to those predicted positions, then count a confirmed track
when its observed center crosses the vertical line.
"""

from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

import numpy as np


LINE_X = 800
MIN_HITS = 2
MAX_AGE = 2
X_GATE_LIVE = 90
X_GATE_FALLBACK = 120
Y_GATE = 100
IOU_TH = 0.15
V_DEFAULT = 140
V_MIN = 40
V_MAX = 260
HIST_FRAME_WIDTH = 1600


def iou(a: Sequence[float], b: Sequence[float]) -> float:
    """Return intersection-over-union for [x, y, w, h] boxes."""
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    x1 = max(ax, bx)
    y1 = max(ay, by)
    x2 = min(ax + aw, bx + bw)
    y2 = min(ay + ah, by + bh)
    iw = max(0.0, x2 - x1)
    ih = max(0.0, y2 - y1)
    inter = iw * ih
    union = aw * ah + bw * bh - inter
    return float(inter / union) if union > 0 else 0.0


def xhist(boxes: Sequence[Sequence[float]], bins: int = 80) -> np.ndarray:
    """Histogram detection x-centers, ignoring near-edge detections."""
    hist = np.zeros(bins)
    for x, _y, w, _h in boxes:
        center_x = x + w / 2.0
        if 150 < center_x < 1450:
            hist[min(bins - 1, int(center_x / HIST_FRAME_WIDTH * bins))] += 1
    return hist


def global_v(
    prev_boxes: Sequence[Sequence[float]],
    cur_boxes: Sequence[Sequence[float]],
) -> Optional[float]:
    """Estimate global conveyor velocity in px/frame via cross-correlation."""
    if not prev_boxes or not cur_boxes:
        return None

    prev_hist = xhist(prev_boxes)
    cur_hist = xhist(cur_boxes)
    if prev_hist.sum() < 6 or cur_hist.sum() < 6:
        return None

    best = -1.0
    best_lag = 0
    for lag in range(int(V_MIN / 20), int(V_MAX / 20) + 1):
        corr = float(np.dot(cur_hist, np.roll(prev_hist, lag)))
        if corr > best:
            best = corr
            best_lag = lag
    return float(best_lag * 20)


@dataclass
class _Track:
    bbox: List[float]
    cx: float
    cy: float
    prev_cx: float
    hits: int = 1
    counted: bool = False
    miss: int = 0


class BeanTracker:
    """Track beans with global conveyor motion and count line crossings."""

    def __init__(
        self,
        iou_threshold: float = IOU_TH,
        centroid_gate: Optional[float] = None,
        min_hits: int = MIN_HITS,
        max_age: int = MAX_AGE,
        line_pos: float = 0.5,
        axis: str = "x",
        direction: str = "positive",
        guard_band: Optional[float] = None,
        frame_width: int = HIST_FRAME_WIDTH,
    ):
        del iou_threshold, centroid_gate, min_hits, max_age, guard_band
        if axis != "x":
            raise ValueError("BeanTracker only supports vertical x-line counting")
        if direction not in ("positive", "auto", "both", 1):
            raise ValueError("BeanTracker only supports left-to-right positive x flow")

        self.min_hits = MIN_HITS
        self.max_age = MAX_AGE
        self.line_pos = float(line_pos)
        self.frame_width = int(frame_width)
        self.frame_height: Optional[int] = None
        self.line_x = self.frame_width * self.line_pos

        self.tracks: List[_Track] = []
        self.prev_boxes: List[List[float]] = []
        self.vh: List[float] = []
        self.total_crossed = 0

    def set_frame_size(self, w: int, h: int) -> None:
        self.frame_width = int(w)
        self.frame_height = int(h)
        self.line_x = self.frame_width * self.line_pos

    def update(self, boxes, frame_id, frame_size=None) -> dict:
        """Update tracks from detector boxes and return crossing counters."""
        del frame_id
        if frame_size is not None:
            self.set_frame_size(frame_size[0], frame_size[1])

        detections = [self._clean_box(box) for box in boxes]
        g = global_v(self.prev_boxes, detections)
        if g:
            self.vh.append(g)
            self.vh = self.vh[-5:]

        if g is not None:
            v = float(np.median(np.asarray(self.vh, dtype=np.float32)))
            gate = X_GATE_LIVE
        else:
            v = (
                float(np.median(np.asarray(self.vh, dtype=np.float32)))
                if self.vh
                else float(V_DEFAULT)
            )
            gate = X_GATE_FALLBACK

        centers = [self._center(box) for box in detections]
        used_detections = set()
        new_crossings = 0

        for track in self.tracks:
            det_idx = self._best_detection(track, detections, centers, used_detections, v, gate)
            if det_idx is None:
                track.miss += 1
                continue

            used_detections.add(det_idx)
            prev_cx = track.cx
            cx, cy = centers[det_idx]
            track.prev_cx = prev_cx
            track.cx = cx
            track.cy = cy
            track.bbox = detections[det_idx]
            track.hits += 1
            track.miss = 0

            if (
                not track.counted
                and track.hits >= self.min_hits
                and track.prev_cx < self.line_x <= track.cx
            ):
                track.counted = True
                self.total_crossed += 1
                new_crossings += 1

        self.tracks = [track for track in self.tracks if track.miss <= self.max_age]

        for det_idx, det in enumerate(detections):
            if det_idx in used_detections:
                continue
            cx, cy = centers[det_idx]
            self.tracks.append(_Track(bbox=det, cx=cx, cy=cy, prev_cx=cx - v))

        self.prev_boxes = detections

        return {
            "new_crossings": new_crossings,
            "live_tracks": len(self.tracks),
            "total_crossed": self.total_crossed,
        }

    def _best_detection(
        self,
        track: _Track,
        detections: Sequence[Sequence[float]],
        centers: Sequence[Tuple[float, float]],
        used_detections: set,
        v: float,
        gate: float,
    ) -> Optional[int]:
        pred_cx = track.cx + v
        pred_cy = track.cy
        pred_bbox = [track.bbox[0] + v, track.bbox[1], track.bbox[2], track.bbox[3]]

        best_idx = None
        best_score = -float("inf")
        for det_idx, det in enumerate(detections):
            if det_idx in used_detections:
                continue
            cx, cy = centers[det_idx]
            dx = cx - pred_cx
            dy = cy - pred_cy
            if abs(dx) > gate or abs(dy) > Y_GATE:
                continue

            score = (1.0 - abs(dx) / gate) + iou(pred_bbox, det)
            if score > best_score:
                best_score = score
                best_idx = det_idx

        return best_idx

    def _clean_box(self, box: Sequence[float]) -> List[float]:
        x, y, w, h = box
        return [float(x), float(y), float(w), float(h)]

    def _center(self, box: Sequence[float]) -> Tuple[float, float]:
        x, y, w, h = box
        return (x + w / 2.0, y + h / 2.0)
