#!/usr/bin/env python3
"""
seg_daemon.py — persistent FastSAM daemon for segment_beans_sam
Loads the model once; accepts JSON requests from stdin and returns JSON results to stdout.

stdin protocol (one JSON line per request):
  {"session_dir": "/path/...", "n_beans": 51, "conf": 0.35, "imgsz": 640}
  {"cmd": "exit"}

stdout protocol (one JSON line per response):
  {"status": "ready"}            -- sent once after model is loaded
  {"status": "ok", "bean_count": N}
  {"status": "error", "msg": "..."}
"""
import sys, os, json, traceback

# Duplicate stdout fd BEFORE redirecting sys.stdout, so all print() calls from
# the segmentation script go to stderr (parent's terminal) not the JSON pipe.
_proto_fd = os.dup(1)
sys.stdout = sys.stderr  # print() → stderr from this point on

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

import torch
torch.set_num_threads(4)        # use all 4 Pi5 cores for inference
torch.set_num_interop_threads(1)

from ultralytics import FastSAM

# Load best available model: INT8 ONNX > FP32 ONNX > PyTorch .pt
# Run export_fastsam_onnx.py once to create the ONNX/INT8 files.
def _find_model():
    for imgsz in (256, 192, 320):
        p = os.path.join(SCRIPT_DIR, f"FastSAM-s-{imgsz}-int8.onnx")
        if os.path.exists(p):
            return p, imgsz
    for imgsz in (256, 192, 320):
        p = os.path.join(SCRIPT_DIR, f"FastSAM-s-{imgsz}.onnx")
        if os.path.exists(p):
            return p, imgsz
    return os.path.join(SCRIPT_DIR, "FastSAM-s.pt"), None

_model_path, _onnx_imgsz = _find_model()
print(f"[daemon] Loading model: {os.path.basename(_model_path)}", flush=True)
_model = FastSAM(_model_path)
print("[daemon] Model loaded. Importing segmentation module...", flush=True)

import segment_beans_sam as _seg

print("[daemon] Ready.", flush=True)

# Open the JSON protocol writer on the saved fd
_proto = os.fdopen(_proto_fd, "w", buffering=1)
_proto.write('{"status":"ready"}\n')
_proto.flush()

# ── Request loop ─────────────────────────────────────────────────────────────
for _raw in sys.stdin:
    _raw = _raw.strip()
    if not _raw:
        continue
    try:
        _req = json.loads(_raw)
    except json.JSONDecodeError as _e:
        _proto.write(json.dumps({"status": "error", "msg": f"JSON parse: {_e}"}) + "\n")
        _proto.flush()
        continue

    if _req.get("cmd") == "exit":
        break

    _session_dir = _req.get("session_dir", "")
    _n_beans     = int(_req.get("n_beans", 51))
    _conf        = float(_req.get("conf", 0.35))
    _imgsz       = _onnx_imgsz if _onnx_imgsz else int(_req.get("imgsz", 256))

    try:
        _count = _seg.run(_session_dir, _n_beans, _model, _conf, _imgsz)
        _proto.write(json.dumps({"status": "ok", "bean_count": _count}) + "\n")
        _proto.flush()
    except Exception as _e:
        sys.stderr.write(f"[daemon] Error:\n{traceback.format_exc()}\n")
        sys.stderr.flush()
        _proto.write(json.dumps({"status": "error", "msg": str(_e)}) + "\n")
        _proto.flush()

_proto.close()
