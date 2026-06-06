"""
Pi5 多光譜採集遠端控制伺服器。
Run: uvicorn spectral_capture.control_server:app --host 0.0.0.0 --port 8765
"""
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Optional

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

ROOT       = Path(__file__).parent.parent          # /home/kyle/KyleClaude
PIPELINE   = ROOT / "spectral_capture/capture_pipeline.py"
DB_PATH    = ROOT / "spectral_capture/data/beans.db"
LOG_PATH   = Path("/tmp/pipeline.log")
UI_PATH    = Path(__file__).parent / "ui/index.html"

SDK        = ROOT / "sdk_extract/linux-sdk-arm64/qssdk-20250817"
OPENCV_LIB = SDK / "libarm64/opencv/lib"
UVC_FIX    = ROOT / "multispectral_demo/uvc_fix.so"

def _capture_env() -> dict:
    """Build environment with QS SDK paths for capture_pipeline subprocess."""
    import os
    env = os.environ.copy()
    env["LD_PRELOAD"] = str(UVC_FIX)
    existing_ldlib = env.get("LD_LIBRARY_PATH", "")
    env["LD_LIBRARY_PATH"] = f"{SDK}:{OPENCV_LIB}:{existing_ldlib}"
    return env

app = FastAPI()

_proc: Optional[subprocess.Popen] = None


def _is_running() -> bool:
    return _proc is not None and _proc.poll() is None


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
        return lines[-n:] if len(lines) >= n else lines
    except Exception:
        return []


class StartRequest(BaseModel):
    origin:       str = "unknown"
    process:      str = "unknown"
    roast_level:  str = "green"
    batch_id:     str = "batch-001"
    capture_date: str = ""
    bean_type:    str = "green"   # "green" or "roast"
    interval:     int = 30


@app.get("/api/status")
def status():
    return {
        "running": _is_running(),
        **_db_stats(),
        "recent_log": _recent_log(),
    }


@app.post("/api/capture/start")
def start_capture(req: StartRequest):
    global _proc
    if _is_running():
        return {"status": "already_running"}
    import datetime
    date = req.capture_date or datetime.date.today().isoformat()
    _proc = subprocess.Popen(
        [
            sys.executable, "-u", str(PIPELINE),
            "--origin",       req.origin,
            "--process",      req.process,
            "--roast",        req.roast_level,
            "--batch-id",     req.batch_id,
            "--date",         date,
            "--bean-type",    req.bean_type,
            "--interval",     str(req.interval),
        ],
        stdout=LOG_PATH.open("w"),
        stderr=subprocess.STDOUT,
        cwd=str(ROOT),
        env=_capture_env(),
    )
    return {"status": "started", "pid": _proc.pid}


@app.post("/api/capture/stop")
def stop_capture():
    global _proc
    if not _is_running():
        return {"status": "not_running"}
    _proc.terminate()
    try:
        _proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        _proc.kill()
    _proc = None
    return {"status": "stopped"}


@app.get("/")
def ui():
    if not UI_PATH.exists():
        return JSONResponse({"error": "UI not found"}, status_code=404)
    return FileResponse(str(UI_PATH), media_type="text/html")
