import importlib.util
import sys
import types
from pathlib import Path


def load_preview_display(monkeypatch):
    pygame_stub = types.SimpleNamespace()
    monkeypatch.setitem(sys.modules, "pygame", pygame_stub)
    path = Path(__file__).resolve().parents[1] / "preview_display.py"
    spec = importlib.util.spec_from_file_location("preview_display_for_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_save_batch_json_writes_expected_payload(tmp_path, monkeypatch):
    preview_display = load_preview_display(monkeypatch)
    frames = [
        {"frame_id": 7, "count": 2, "boxes": [[1, 2, 3, 4], [5, 6, 7, 8]]},
        {"frame_id": 8, "count": 1, "boxes": [[9, 10, 11, 12]]},
    ]

    out_path = preview_display.save_batch_json("20260612_153045", 3, frames, tmp_path)

    assert out_path == tmp_path / "batch_20260612_153045.json"
    assert out_path.read_text() == (
        '{"batch_id":"20260612_153045","total_beans":3,'
        '"frames":[{"frame_id":7,"count":2,"boxes":[[1,2,3,4],[5,6,7,8]]},'
        '{"frame_id":8,"count":1,"boxes":[[9,10,11,12]]}]}'
    )
