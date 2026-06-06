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
    return _pipeline_proc is not None and _pipeline_proc.poll() is None


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

    # 3. 啟動採集 pipeline（讀 shm，不碰相機）
    _pipeline_proc = subprocess.Popen(
        [
            sys.executable, "-u", str(PIPELINE),
            "--origin",    req.origin,
            "--process",   req.process,
            "--roast",     req.roast_level,
            "--batch-id",  req.batch_id,
            "--date",      date,
            "--bean-type", req.bean_type,
            "--interval",  str(req.interval),
        ],
        stdout=LOG_PATH.open("w"),
        stderr=subprocess.STDOUT,
        cwd=str(ROOT),
        env=env,
        start_new_session=True,
    )

    return {"status": "started", "pid": _pipeline_proc.pid}


@app.post("/api/capture/stop")
def stop_capture():
    global _pipeline_proc, _preview_proc
    if not _is_running() and _preview_proc is None:
        return {"status": "not_running"}

    # 同時殺掉 pipeline + preview_daemon（相機熄燈）
    _kill_proc(_pipeline_proc)
    _kill_proc(_preview_proc)
    _pipeline_proc = None
    _preview_proc  = None
    return {"status": "stopped"}


@app.get("/")
def ui():
    if not UI_PATH.exists():
        return JSONResponse({"error": "UI not found"}, status_code=404)
    return FileResponse(str(UI_PATH), media_type="text/html")
