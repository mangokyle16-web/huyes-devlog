import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from spectral_capture.pipeline.bean_tracker import BeanTracker


def moving_box(center_x, center_y=600, size=80):
    half = size // 2
    return [center_x - half, center_y - half, size, size]


def test_one_bean_crossing_left_to_right_counts_once():
    tracker = BeanTracker(line_pos=0.5, frame_width=1600)
    tracker.set_frame_size(1600, 1200)

    result = None
    for frame_id, center_x in enumerate([500, 650, 800, 950, 1100], start=1):
        result = tracker.update([moving_box(center_x)], frame_id)

    assert result["total_crossed"] == 1
    assert result["new_crossings"] == 0


def test_stationary_bean_never_crosses():
    tracker = BeanTracker(line_pos=0.5, frame_width=1600)
    tracker.set_frame_size(1600, 1200)

    result = None
    for frame_id in range(1, 21):
        result = tracker.update([moving_box(760)], frame_id)

    assert result["total_crossed"] == 0
    assert result["new_crossings"] == 0
