#!/usr/bin/env python3
"""Pi Agent API — Mac Mini main brain 遠端呼叫介面"""

import socket
import platform
import time
import subprocess
import threading
import uuid
import os
import json
import requests
from collections import deque
from datetime import datetime
from flask import Flask, jsonify, request, send_file, abort, Response

app = Flask(__name__)
START_TIME = time.time()
WORK_DIR = "/home/kyle/KyleClaude"

BRAIN_HOST = os.environ.get("BRAIN_HOST", "192.168.68.173")
BRAIN_PORT = os.environ.get("BRAIN_PORT", "8081")
BRAIN_WEBHOOK = f"http://{BRAIN_HOST}:{BRAIN_PORT}/agent/event"

_jobs = {}
_jobs_lock = threading.Lock()

_activity_log = deque(maxlen=200)
_log_lock = threading.Lock()


def _log(action: str, detail: dict = None, source: str = None, status: int = None, ms: int = None):
    entry = {
        "time": datetime.now().strftime("%H:%M:%S"),
        "date": datetime.now().strftime("%Y-%m-%d"),
        "source": source or "system",
        "action": action,
        "status": status,
        "ms": ms,
        "detail": detail or {},
    }
    with _log_lock:
        _activity_log.appendleft(entry)


@app.before_request
def _before():
    if request.path in ("/dashboard", "/activity") or request.path.startswith("/static"):
        return
    request._t0 = time.time()


@app.after_request
def _after(response):
    path = request.path
    if path in ("/dashboard", "/activity") or path.startswith("/static"):
        return response
    ms = int((time.time() - getattr(request, "_t0", time.time())) * 1000)
    body = request.get_json(silent=True)
    detail = {}
    if body:
        detail["req"] = body
    if path == "/health":
        detail["note"] = "連線確認"
    elif path == "/pipeline/jobs":
        try:
            detail["jobs_count"] = len(response.get_json())
        except Exception:
            pass
    elif path.startswith("/pipeline/status/"):
        try:
            j = response.get_json()
            detail["status"] = j.get("status")
        except Exception:
            pass
    elif path == "/pipeline/run" and request.method == "POST":
        try:
            j = response.get_json()
            detail["job_id"] = j.get("job_id")
            detail["n_beans"] = j.get("n_beans")
        except Exception:
            pass
    _log(
        action=f"{request.method} {path}",
        detail=detail,
        source=request.remote_addr,
        status=response.status_code,
        ms=ms,
    )
    return response


def _push_to_brain(payload: dict, callback_url: str = None):
    url = callback_url or BRAIN_WEBHOOK
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception:
        pass


# ── Health ─────────────────────────────────────────────────────────────────────

@app.route("/health")
def health():
    uptime = int(time.time() - START_TIME)
    return jsonify({
        "status": "ok",
        "hostname": socket.gethostname(),
        "platform": platform.machine(),
        "uptime_seconds": uptime,
        "timestamp": datetime.utcnow().isoformat() + "Z",
    })

@app.route("/")
def index():
    return jsonify({"node": "raspberry-pi", "role": "sensor-agent"})


# ── Dashboard ──────────────────────────────────────────────────────────────────

@app.route("/dashboard")
def dashboard():
    with _jobs_lock:
        jobs_snapshot = list(_jobs.items())
    with _log_lock:
        log_snapshot = list(_activity_log)

    status_color = {"queued": "#f59e0b", "running": "#3b82f6", "done": "#22c55e", "error": "#ef4444"}

    jobs_html = ""
    for jid, j in sorted(jobs_snapshot, key=lambda x: x[1]["started_at"], reverse=True):
        color = status_color.get(j["status"], "#888")
        finished = j["finished_at"] or "—"
        jobs_html += f"""
        <tr>
          <td><code>{jid}</code></td>
          <td><span style="color:{color};font-weight:bold">{j['status']}</span></td>
          <td>{j['n_beans']} 顆</td>
          <td>{j['started_at'][11:19]}</td>
          <td>{finished[11:19] if finished != '—' else '—'}</td>
          <td style="font-size:11px;color:#888">{j.get('error','')[:60] if j.get('error') else ''}</td>
        </tr>"""

    log_html = ""
    for e in log_snapshot[:50]:
        status_val = e.get("status") or ""
        status_color_inline = "#22c55e" if str(status_val).startswith("2") else "#ef4444" if str(status_val).startswith(("4","5")) else "#94a3b8"
        ms_val = f"{e['ms']}ms" if e.get("ms") is not None else ""
        detail = e.get("detail", {})
        detail_str = ""
        if detail.get("req"):
            detail_str = json.dumps(detail["req"], ensure_ascii=False)[:80]
        elif detail.get("note"):
            detail_str = detail["note"]
        elif detail.get("status"):
            detail_str = f"→ {detail['status']}"
        elif detail.get("jobs_count") is not None:
            detail_str = f"{detail['jobs_count']} jobs"
        elif detail.get("job_id"):
            detail_str = f"job={detail['job_id']} beans={detail.get('n_beans','?')}"
        log_html += f"""
        <tr>
          <td style="color:#64748b;white-space:nowrap">{e['date']}<br>{e['time']}</td>
          <td><code style="color:#60a5fa;font-size:11px">{e['source']}</code></td>
          <td style="font-weight:500">{e['action']}</td>
          <td><span style="color:{status_color_inline}">{status_val}</span> <span style="color:#475569;font-size:11px">{ms_val}</span></td>
          <td style="font-size:11px;color:#6b7280;max-width:160px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{detail_str}</td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta http-equiv="refresh" content="5">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Pi Agent Dashboard</title>
<style>
  body {{ background:#0f172a; color:#e2e8f0; font-family:monospace; padding:12px; margin:0; font-size:13px }}
  h2 {{ color:#7dd3fc; margin:0 0 6px; font-size:16px }}
  .badge {{ background:#1e293b; border-radius:6px; padding:3px 8px; font-size:11px; color:#94a3b8; margin-right:6px }}
  table {{ width:100%; border-collapse:collapse; margin-bottom:20px }}
  th {{ text-align:left; color:#475569; font-size:11px; padding:5px 6px; border-bottom:1px solid #1e293b }}
  td {{ padding:5px 6px; border-bottom:1px solid #1e293b; vertical-align:top }}
  tr:hover td {{ background:#1e293b }}
  .section {{ color:#94a3b8; font-size:10px; margin:14px 0 4px; text-transform:uppercase; letter-spacing:1px }}
  .refresh {{ color:#334155; font-size:10px; margin-top:8px }}
</style>
</head>
<body>
<h2>Pi Agent Dashboard</h2>
<div style="margin-bottom:12px">
  <span class="badge">host: {socket.gethostname()}</span>
  <span class="badge">uptime: {int(time.time()-START_TIME)}s</span>
  <span class="badge">jobs: {len(jobs_snapshot)}</span>
  <span class="badge" style="color:#22c55e">● online</span>
</div>

<div class="section">Jobs</div>
<table>
  <tr><th>ID</th><th>狀態</th><th>豆數</th><th>開始</th><th>完成</th><th>錯誤</th></tr>
  {jobs_html or '<tr><td colspan="6" style="color:#475569">尚無 job</td></tr>'}
</table>

<div class="section">指令記錄 (Mac Mini → Pi)</div>
<table>
  <tr><th>時間</th><th>來源</th><th>指令</th><th>狀態/耗時</th><th>細節</th></tr>
  {log_html or '<tr><td colspan="5" style="color:#475569">尚無記錄</td></tr>'}
</table>

<div class="refresh">每 5 秒自動刷新</div>
</body>
</html>"""
    return Response(html, mimetype="text/html")


@app.route("/activity")
def activity():
    with _log_lock:
        return jsonify(list(_activity_log))


# ── Pipeline ───────────────────────────────────────────────────────────────────

def _run_job(job_id, n_beans, callback_url=None):
    with _jobs_lock:
        _jobs[job_id]["status"] = "running"
    _log("job_started", {"job_id": job_id, "n_beans": n_beans}, source="system")
    _push_to_brain({"event": "job_started", "job_id": job_id, "n_beans": n_beans}, callback_url)

    try:
        result = subprocess.run(
            ["bash", f"{WORK_DIR}/run_pipeline.sh", str(n_beans)],
            capture_output=True, text=True, cwd=WORK_DIR
        )
        log = result.stdout + result.stderr
        session_dir = None
        for line in log.splitlines():
            if "Session" in line and "GigaImage_" in line:
                session_dir = line.split(":")[-1].strip()
                break

        finished_at = datetime.utcnow().isoformat() + "Z"
        status = "done" if result.returncode == 0 else "error"
        with _jobs_lock:
            _jobs[job_id]["status"] = status
            _jobs[job_id]["session_dir"] = session_dir
            _jobs[job_id]["error"] = log[-2000:] if status == "error" else None
            _jobs[job_id]["log"] = log[-3000:]
            _jobs[job_id]["finished_at"] = finished_at

        _log(f"job_{status}", {"job_id": job_id, "session_dir": session_dir}, source="system")
        _push_to_brain({
            "event": "job_finished", "job_id": job_id, "status": status,
            "session_dir": session_dir, "finished_at": finished_at,
            "result_url": f"http://{socket.gethostname()}.local:8080/pipeline/result/{job_id}",
        }, callback_url)

    except Exception as e:
        finished_at = datetime.utcnow().isoformat() + "Z"
        with _jobs_lock:
            _jobs[job_id]["status"] = "error"
            _jobs[job_id]["error"] = str(e)
            _jobs[job_id]["finished_at"] = finished_at
        _log("job_error", {"job_id": job_id, "error": str(e)}, source="system")
        _push_to_brain({"event": "job_error", "job_id": job_id, "error": str(e)}, callback_url)


@app.route("/pipeline/run", methods=["POST"])
def pipeline_run():
    body = request.get_json(silent=True) or {}
    n_beans = int(body.get("n_beans", 51))
    callback_url = body.get("callback_url")

    job_id = str(uuid.uuid4())[:8]
    with _jobs_lock:
        _jobs[job_id] = {
            "status": "queued", "n_beans": n_beans, "callback_url": callback_url,
            "session_dir": None, "started_at": datetime.utcnow().isoformat() + "Z",
            "finished_at": None, "error": None, "log": None,
        }

    threading.Thread(target=_run_job, args=(job_id, n_beans, callback_url), daemon=True).start()
    return jsonify({"job_id": job_id, "status": "queued", "n_beans": n_beans}), 202


@app.route("/pipeline/status/<job_id>")
def pipeline_status(job_id):
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        abort(404)
    return jsonify({"job_id": job_id, **{k: v for k, v in job.items() if k != "log"}})


@app.route("/pipeline/result/<job_id>")
def pipeline_result(job_id):
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        abort(404)
    if job["status"] != "done":
        return jsonify({"error": "not ready", "status": job["status"]}), 409

    session_dir = job["session_dir"]
    result_dir = os.path.join(session_dir, "mold_result") if session_dir else None
    report = {}
    if result_dir:
        for fname in ["mold_report.csv", "report.csv"]:
            csv_path = os.path.join(result_dir, fname)
            if os.path.exists(csv_path):
                with open(csv_path) as f:
                    report["csv"] = f.read()
                break

    return jsonify({"job_id": job_id, "session_dir": session_dir, "result_dir": result_dir, "report": report})


@app.route("/pipeline/image/<job_id>/<filename>")
def pipeline_image(job_id, filename):
    if ".." in filename or "/" in filename:
        abort(400)
    allowed = {"overview_labeled.png", "high_beans_zoom.png", "mold_report.png"}
    if filename not in allowed:
        abort(400)
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job or job["status"] != "done":
        abort(404)
    img_path = os.path.join(job["session_dir"], "mold_result", filename)
    if not os.path.exists(img_path):
        abort(404)
    return send_file(img_path, mimetype="image/png")


@app.route("/pipeline/jobs")
def pipeline_jobs():
    with _jobs_lock:
        jobs = {jid: {k: v for k, v in j.items() if k != "log"} for jid, j in _jobs.items()}
    return jsonify(jobs)


@app.route("/file/<filename>")
def serve_file(filename):
    allowed = {"PI_CONNECTION.md"}
    if filename not in allowed:
        abort(404)
    path = os.path.join(WORK_DIR, filename)
    if not os.path.exists(path):
        abort(404)
    return send_file(path, mimetype="text/plain")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False)
