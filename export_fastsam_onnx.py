#!/usr/bin/env python3
"""
Export FastSAM-s.pt → ONNX + INT8 dynamic quantization.
Run once; the daemon will auto-use the quantized model on next startup.

Usage:
  python3 export_fastsam_onnx.py [imgsz]   default imgsz=256
"""
import os, sys, time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PT_PATH    = os.path.join(SCRIPT_DIR, "FastSAM-s.pt")
imgsz      = int(sys.argv[1]) if len(sys.argv) > 1 else 256

ONNX_PATH  = os.path.join(SCRIPT_DIR, f"FastSAM-s-{imgsz}.onnx")
INT8_PATH  = os.path.join(SCRIPT_DIR, f"FastSAM-s-{imgsz}-int8.onnx")

# ── Step 1: Export .pt → .onnx ───────────────────────────────────────────────
print(f"[1/2] Exporting {PT_PATH} → ONNX (imgsz={imgsz})...")
t0 = time.time()
from ultralytics import FastSAM
model = FastSAM(PT_PATH)
export_path = model.export(format="onnx", imgsz=imgsz, simplify=True, opset=12)
print(f"      Done in {time.time()-t0:.1f}s  →  {export_path}")

# Ultralytics places the file next to the .pt; move/rename if needed
if os.path.abspath(export_path) != ONNX_PATH:
    import shutil
    shutil.move(export_path, ONNX_PATH)
    print(f"      Moved to {ONNX_PATH}")

# ── Step 2: INT8 dynamic quantization ────────────────────────────────────────
print(f"\n[2/2] Quantizing → INT8 ({INT8_PATH})...")
try:
    from onnxruntime.quantization import quantize_dynamic, QuantType
    t1 = time.time()
    quantize_dynamic(ONNX_PATH, INT8_PATH, weight_type=QuantType.QInt8)
    print(f"      Done in {time.time()-t1:.1f}s")
    print(f"\nReady! Daemon will use: {INT8_PATH}")
except ImportError:
    print("      onnxruntime not found; install with:")
    print("        pip install onnxruntime")
    print(f"\nFP32 ONNX ready: {ONNX_PATH}")
    print("Daemon will use FP32 ONNX (still faster than PyTorch).")
