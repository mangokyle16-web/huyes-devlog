"""
Pi5 多光譜採集遠端控制伺服器。
Run: uvicorn spectral_capture.control_server:app --host 0.0.0.0 --port 8765

生命週期：
  手機按「開始採集」→ 啟動 preview_daemon（相機亮燈）+ capture_pipeline
  手機按「暫停採集」→ 同時殺掉兩者（相機熄燈）
"""
import sqlite3
import subprocess
import sys
import os
import signal as _sig
import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

ROOT          = Path(__file__).parent.parent
PIPELINE      = ROOT / "spectral_capture/capture_pipeline.py"
PREVIEW_BIN   = ROOT / "spectral_capture/capture/preview_daemon"
QSBS          = ROOT / "spectral_capture/capture/msi.qsbs"
DB_PATH       = ROOT / "spectral_capture/data/beans.db"
LOG_PATH      = Path("/tmp/pipeline.log")
UI_PATH       = Path(__file__).parent / "ui/index.html"
SDK           = ROOT / "sdk_extract/linux-sdk-arm64/qssdk-20250817"
OPENCV_LIB    = SDK / "libarm64/opencv/lib"
UVC_FIX       = ROOT / "multispectral_demo/uvc_fix.so"
PREVIEW_FPS   = 2


def _sdk_env() -> dict:
    env = os.environ.copy()
    env["LD_PRELOAD"] = str(UVC_FIX)
    env["LD_LIBRARY_PATH"] = f"{SDK}:{OPENCV_LIB}:{env.get('LD_LIBRARY_PATH', '')}"
    return env


app = FastAPI()

_pipeline_proc: Optional[subprocess.Popen] = None
_preview_proc:  Optional[subprocess.Popen] = None


def _is_running() -> bool:
    if _pipeline_proc is not None and _pipeline_proc.poll() is None:
        return True
    # Also check if preview_daemon is alive (camera might be on without pipeline)
    if _preview_proc is not None and _preview_proc.poll() is None:
        return True
    return False


def _kill_proc(proc: Optional[subprocess.Popen]):
    if proc is None:
        return
    try:
        os.killpg(os.getpgid(proc.pid), _sig.SIGKILL)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
    try:
        proc.wait(timeout=2)
    except Exception:
        pass


def _pkill_by_name():
    """Fallback: kill any lingering processes by name regardless of PID tracking."""
    for name in ('preview_daemon', 'capture_pipeline', 'qs_file_processor', 'capture_one'):
        try:
            subprocess.run(['pkill', '-9', '-f', name],
                           capture_output=True, timeout=2)
        except Exception:
            pass


def _db_stats() -> dict:
    if not DB_PATH.exists():
        return {"total_beans": 0}
    try:
        conn = sqlite3.connect(str(DB_PATH))
        total = conn.execute("SELECT COUNT(*) FROM bean_spectra").fetchone()[0]
        conn.close()
        return {"total_beans": total}
    except Exception:
        return {"total_beans": 0}


def _recent_log(n: int = 8) -> list:
    if not LOG_PATH.exists():
        return []
    try:
        lines = LOG_PATH.read_text().splitlines()
        filtered = [l for l in lines
                    if not l.startswith('[uvc_fix]')
                    and not l.startswith('!name:')]
        return filtered[-n:] if len(filtered) >= n else filtered
    except Exception:
        return []


class StartRequest(BaseModel):
    origin:       str = "unknown"
    process:      str = "unknown"
    roast_level:  str = "green"
    batch_id:     str = "batch-001"
    capture_date: str = ""
    bean_type:    str = "green"
    interval:     int = 30
    mode:         str = "image"   # "image" = 只存圖, "spectral" = 光譜採集


@app.get("/api/status")
def status():
    return {
        "running": _is_running(),
        **_db_stats(),
        "recent_log": _recent_log(),
    }


@app.post("/api/capture/start")
def start_capture(req: StartRequest):
    global _pipeline_proc, _preview_proc
    if _is_running():
        return {"status": "already_running"}

    date = req.capture_date or datetime.date.today().isoformat()
    env  = _sdk_env()

    # 寫 metadata 到 shm 供 7" 螢幕顯示
    import json, time
    meta = {
        "origin":      req.origin,
        "process":     req.process,
        "roast_level": req.roast_level,
        "batch_id":    req.batch_id,
        "capture_date": date,
        "bean_type":   req.bean_type,
        "start_epoch": time.time(),
    }
    Path("/dev/shm/capture_meta.json").write_text(json.dumps(meta))

    # 1. 先啟動 preview_daemon（相機亮燈、開始 live preview）
    _preview_proc = subprocess.Popen(
        [str(PREVIEW_BIN), str(QSBS), str(PREVIEW_FPS)],
        stdout=open("/tmp/preview_daemon.log", "w"),
        stderr=subprocess.STDOUT,
        cwd=str(ROOT),
        env=env,
        start_new_session=True,
    )

    # 2. 等相機初始化（約 1-2 秒後 shm 就緒）
    import time
    time.sleep(2)

    # 3. 啟動採集程式（根據 mode 選擇）
    CAPTURE_IMAGES = ROOT / "spectral_capture/capture_images.py"
    if req.mode == "image":
        # 快速影像模式：只存 preview JPEG + .qs，不做光譜處理
        cmd = [
            sys.executable, "-u", str(CAPTURE_IMAGES),
            "--batch-id", req.batch_id,
            "--save-qs",
            "--qs-every", "5",   # 每 5 幀存一次 .qs，節省空間
        ]
    else:
        # 光譜採集模式：完整處理
        cmd = [
            sys.executable, "-u", str(PIPELINE),
            "--origin",    req.origin,
            "--process",   req.process,
            "--roast",     req.roast_level,
            "--batch-id",  req.batch_id,
            "--date",      date,
            "--bean-type", req.bean_type,
            "--interval",  str(req.interval),
        ]

    _pipeline_proc = subprocess.Popen(
        cmd,
        stdout=LOG_PATH.open("w"),
        stderr=subprocess.STDOUT,
        cwd=str(ROOT),
        env=env,
        start_new_session=True,
    )

    return {"status": "started", "mode": req.mode, "pid": _pipeline_proc.pid}


@app.post("/api/capture/stop")
def stop_capture():
    global _pipeline_proc, _preview_proc

    # 無論 PID 是否有效，一律 pkill 兜底（處理殭屍/失去追蹤的情況）
    _kill_proc(_pipeline_proc)
    _kill_proc(_preview_proc)
    _pkill_by_name()   # 確保清乾淨

    _pipeline_proc = None
    _preview_proc  = None
    try:
        Path("/dev/shm/capture_meta.json").unlink(missing_ok=True)
    except Exception:
        pass
    return {"status": "stopped"}


@app.get("/")
def ui():
    if not UI_PATH.exists():
        return JSONResponse({"error": "UI not found"}, status_code=404)
    return FileResponse(str(UI_PATH), media_type="text/html")
