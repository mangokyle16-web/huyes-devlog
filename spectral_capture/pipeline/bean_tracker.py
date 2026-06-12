"""Conveyor-belt bean tracking and virtual-line counting.

The detector reports beans in every frame, so summing frame counts double-counts
beans while they remain visible. BeanTracker keeps short-lived tracks across
frames and counts each confirmed track once when it crosses a configured line.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np


@dataclass
class _Track:
    id: int
    bbox: List[float]
    center: Tuple[float, float]
    velocity: Tuple[float, float] = (0.0, 0.0)
    hits: int = 1
    misses: int = 0
    confirmed: bool = False
    counted: bool = False
    prev_center: Optional[Tuple[float, float]] = None
    history: List[Tuple[float, float]] = field(default_factory=list)
    stable_side: int = 0


class BeanTracker:
    def __init__(
        self,
        iou_threshold=0.15,
        centroid_gate=80,
        min_hits=3,
        max_age=5,
        line_pos=0.5,
        axis="x",
        direction="auto",
        guard_band=30,
    ):
        if axis not in ("x", "y"):
            raise ValueError("axis must be 'x' or 'y'")
        if direction not in ("auto", "positive", "negative", "both", 1, -1):
            raise ValueError("direction must be auto, positive, negative, both, 1, or -1")

        self.iou_threshold = float(iou_threshold)
        self.centroid_gate = float(centroid_gate)
        self.min_hits = int(min_hits)
        self.max_age = int(max_age)
        self.line_pos = float(line_pos)
        self.axis = axis
        self.direction = direction
        self.guard_band = float(guard_band)

        self.tracks: Dict[int, _Track] = {}
        self.next_id = 1
        self.total_crossed = 0
        self.frame_w: Optional[int] = None
        self.frame_h: Optional[int] = None
        self._flow_samples: List[float] = []
        self._flow_sign: Optional[int] = None

    def set_frame_size(self, w, h):
        self.frame_w = int(w)
        self.frame_h = int(h)

    def update(self, boxes, frame_id, frame_size=None) -> dict:
        """Update tracks from detector boxes and return crossing counters."""
        del frame_id  # reserved for callers/logging; tracking is frame-order based
        if frame_size is not None:
            self.set_frame_size(frame_size[0], frame_size[1])
        elif (self.frame_w is None or self.frame_h is None) and boxes:
            self._infer_frame_size_from_boxes(boxes)

        detections = [self._clean_box(box) for box in boxes]
        centers = [self._center(box) for box in detections]

        matches, unmatched_tracks, unmatched_dets = self._match(detections, centers)
        new_crossings = 0

        for track_id, det_idx in matches:
            track = self.tracks[track_id]
            old_center = track.center
            new_center = centers[det_idx]
            measured_v = (new_center[0] - old_center[0], new_center[1] - old_center[1])
            track.velocity = (
                0.5 * measured_v[0] + 0.5 * track.velocity[0],
                0.5 * measured_v[1] + 0.5 * track.velocity[1],
            )
            track.prev_center = old_center
            track.center = new_center
            track.bbox = detections[det_idx]
            track.hits += 1
            track.misses = 0
            track.history.append(new_center)
            if len(track.history) > 20:
                track.history = track.history[-20:]
            if track.hits >= self.min_hits:
                track.confirmed = True
                self._record_flow_sample(track)
            if self._maybe_count_crossing(track):
                new_crossings += 1

        for track_id in unmatched_tracks:
            track = self.tracks[track_id]
            track.misses += 1

        for det_idx in unmatched_dets:
            self._create_track(detections[det_idx], centers[det_idx])

        expired = [track_id for track_id, track in self.tracks.items()
                   if track.misses > self.max_age]
        for track_id in expired:
            del self.tracks[track_id]

        return {
            "new_crossings": new_crossings,
            "live_tracks": len(self.tracks),
            "total_crossed": self.total_crossed,
        }

    def _clean_box(self, box: Sequence[float]) -> List[float]:
        x, y, w, h = box
        return [float(x), float(y), float(w), float(h)]

    def _infer_frame_size_from_boxes(self, boxes):
        max_x = max(float(x) + float(w) for x, y, w, h in boxes)
        max_y = max(float(y) + float(h) for x, y, w, h in boxes)
        self.frame_w = int(np.ceil(max_x))
        self.frame_h = int(np.ceil(max_y))

    def _create_track(self, box, center):
        track = _Track(
            id=self.next_id,
            bbox=box,
            center=center,
            history=[center],
            stable_side=self._side(center),
        )
        self.tracks[track.id] = track
        self.next_id += 1

    def _match(self, detections, centers):
        if not self.tracks or not detections:
            return [], list(self.tracks.keys()), list(range(len(detections)))

        candidates = []
        for track_id, track in self.tracks.items():
            predicted = (
                track.center[0] + track.velocity[0],
                track.center[1] + track.velocity[1],
            )
            for det_idx, det_box in enumerate(detections):
                dist = float(np.hypot(
                    centers[det_idx][0] - predicted[0],
                    centers[det_idx][1] - predicted[1],
                ))
                if dist >= self.centroid_gate:
                    continue
                iou = self._iou(track.bbox, det_box)
                if iou >= self.iou_threshold:
                    candidates.append((iou, -dist, track_id, det_idx))

        candidates.sort(reverse=True)
        matches = []
        used_tracks = set()
        used_dets = set()
        for iou, neg_dist, track_id, det_idx in candidates:
            del iou, neg_dist
            if track_id in used_tracks or det_idx in used_dets:
                continue
            matches.append((track_id, det_idx))
            used_tracks.add(track_id)
            used_dets.add(det_idx)

        unmatched_tracks = [track_id for track_id in self.tracks if track_id not in used_tracks]
        unmatched_dets = [det_idx for det_idx in range(len(detections)) if det_idx not in used_dets]
        return matches, unmatched_tracks, unmatched_dets

    def _maybe_count_crossing(self, track: _Track) -> bool:
        current_side = self._side(track.center)
        if current_side == 0:
            return False

        previous_side = track.stable_side
        if previous_side == 0:
            track.stable_side = current_side
            return False

        if (
            track.confirmed
            and not track.counted
            and previous_side != current_side
            and self._direction_allows(previous_side, current_side)
        ):
            track.counted = True
            self.total_crossed += 1
            track.stable_side = current_side
            return True

        track.stable_side = current_side
        return False

    def _line_coord(self) -> Optional[float]:
        if self.axis == "x":
            if self.frame_w is None:
                return None
            return self.frame_w * self.line_pos
        if self.frame_h is None:
            return None
        return self.frame_h * self.line_pos

    def _side(self, center) -> int:
        line = self._line_coord()
        if line is None:
            return 0
        value = center[0] if self.axis == "x" else center[1]
        if value < line - self.guard_band:
            return -1
        if value > line + self.guard_band:
            return 1
        return 0

    def _direction_allows(self, previous_side: int, current_side: int) -> bool:
        crossing_sign = 1 if current_side > previous_side else -1
        if self.direction in ("both",):
            return True
        if self.direction in ("positive", 1):
            return crossing_sign > 0
        if self.direction in ("negative", -1):
            return crossing_sign < 0
        if self._flow_sign is None:
            return True
        return crossing_sign == self._flow_sign

    def _record_flow_sample(self, track: _Track):
        component = track.velocity[0] if self.axis == "x" else track.velocity[1]
        if abs(component) < 0.5:
            return
        self._flow_samples.append(float(component))
        if len(self._flow_samples) > 50:
            self._flow_samples = self._flow_samples[-50:]
        if self.direction == "auto" and len(self._flow_samples) >= 5:
            median = float(np.median(np.asarray(self._flow_samples, dtype=np.float32)))
            if abs(median) >= 0.5:
                self._flow_sign = 1 if median > 0 else -1

    def _center(self, box) -> Tuple[float, float]:
        x, y, w, h = box
        return (x + w / 2.0, y + h / 2.0)

    def _iou(self, a, b) -> float:
        ax1, ay1, aw, ah = a
        bx1, by1, bw, bh = b
        ax2, ay2 = ax1 + aw, ay1 + ah
        bx2, by2 = bx1 + bw, by1 + bh

        ix1 = max(ax1, bx1)
        iy1 = max(ay1, by1)
        ix2 = min(ax2, bx2)
        iy2 = min(ay2, by2)
        iw = max(0.0, ix2 - ix1)
        ih = max(0.0, iy2 - iy1)
        inter = iw * ih
        if inter <= 0:
            return 0.0
        union = aw * ah + bw * bh - inter
        if union <= 0:
            return 0.0
        return float(inter / union)
