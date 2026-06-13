import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from spectral_capture.pipeline.bean_tracker import BeanTracker


FIXTURE = Path(__file__).with_name("fixtures_detect_stream_8cm.jsonl")


def run_replay(tracker):
    result = {"total_crossed": 0}
    with FIXTURE.open("r", encoding="utf-8") as stream:
        for line in stream:
            frame = json.loads(line)
            result = tracker.update(frame["boxes"], frame["frame_id"])
    return result


def test_replay_real_detect_stream_counts_validated_range():
    single_tracker = BeanTracker(line1_pos=0.5, line2_pos=0.5, frame_width=1600)
    dual_tracker = BeanTracker(line1_pos=0.4, line2_pos=0.6, frame_width=1600)

    single_result = run_replay(single_tracker)
    dual_result = run_replay(dual_tracker)

    print(
        "replay single_line_total="
        f"{single_result['total_crossed']} dual_line_total={dual_result['total_crossed']}"
    )
    assert 360 <= single_result["total_crossed"] <= 380
    assert dual_result["total_crossed"] >= single_result["total_crossed"]
    assert dual_result["total_crossed"] >= 368
    assert dual_result["total_crossed"] <= 410
