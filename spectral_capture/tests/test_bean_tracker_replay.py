import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from spectral_capture.pipeline.bean_tracker import BeanTracker


FIXTURE = Path(__file__).with_name("fixtures_detect_stream_8cm.jsonl")


def test_replay_real_detect_stream_counts_validated_range():
    tracker = BeanTracker(line_pos=0.5, frame_width=1600)
    result = {"total_crossed": 0}

    with FIXTURE.open("r", encoding="utf-8") as stream:
        for line in stream:
            frame = json.loads(line)
            result = tracker.update(frame["boxes"], frame["frame_id"])

    print(f"replay total_crossed={result['total_crossed']}")
    assert 360 <= result["total_crossed"] <= 380
