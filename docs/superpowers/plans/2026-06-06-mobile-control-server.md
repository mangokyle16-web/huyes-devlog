# Mobile Remote Control Server Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Pi5 上建一個 FastAPI 伺服器，讓手機瀏覽器開 `http://raspberrypi.local:8765` 就能啟動/暫停採集、看即時統計。

**Architecture:** `control_server.py` 管理 `capture_pipeline.py` 子程序的生命週期，透過 `/api/*` REST endpoints 暴露狀態；同一個 FastAPI app 靜態服務 `ui/index.html`（單一 HTML 檔，無 framework，手機直立版深色主題）。

**Tech Stack:** Python 3.11, FastAPI, uvicorn, SQLite3（已有）, Vanilla JS + CSS（無 npm）

---

## File Structure

```
KyleClaude/spectral_capture/
├── control_server.py          # NEW: FastAPI app，API + 靜態服務
├── ui/
│   └── index.html             # NEW: 手機 Web UI（單一檔案，inline CSS+JS）
└── tests/
    └── test_control_server.py # NEW: FastAPI TestClient 測試
```

執行方式（Pi5）：
```bash
cd /home/kyle/KyleClaude
uvicorn spectral_capture.control_server:app --host 0.0.0.0 --port 8765
```

---

## Task 1: 安裝依賴 + 建立 ui 目錄

**Files:**
- Create: `spectral_capture/ui/.gitkeep`

- [ ] **Step 1: 在 Pi5 安裝 FastAPI + uvicorn**

```bash
pip3 install fastapi uvicorn[standard]
```
Expected: `Successfully installed fastapi-... uvicorn-...`

- [ ] **Step 2: 確認安裝成功**

```bash
python3 -c "import fastapi, uvicorn; print('ok', fastapi.__version__, uvicorn.__version__)"
```
Expected: `ok 0.11x.x 0.3x.x`（版本號不重要）

- [ ] **Step 3: 建立 ui 目錄**

```bash
mkdir -p /home/kyle/KyleClaude/spectral_capture/ui
touch /home/kyle/KyleClaude/spectral_capture/ui/.gitkeep
```

- [ ] **Step 4: Commit**

```bash
cd ~/KyleClaude
git add spectral_capture/ui/.gitkeep
git commit -m "chore: add ui/ directory for mobile control server"
```

---

## Task 2: FastAPI Control Server

**Files:**
- Create: `spectral_capture/control_server.py`
- Test: `spectral_capture/tests/test_control_server.py`

- [ ] **Step 1: 寫 failing test**

```python
# spectral_capture/tests/test_control_server.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from fastapi.testclient import TestClient
from spectral_capture.control_server import app

client = TestClient(app)


def test_status_when_stopped():
    resp = client.get("/api/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["running"] is False
    assert "total_beans" in data
    assert "recent_log" in data


def test_stop_when_not_running():
    resp = client.post("/api/capture/stop")
    assert resp.status_code == 200
    assert resp.json()["status"] == "not_running"


def test_start_returns_started_or_already_running():
    # We don't actually spawn the real subprocess in tests
    resp = client.post("/api/capture/start", json={
        "origin": "TestOrigin", "roast": "green", "interval": 30
    })
    assert resp.status_code == 200
    assert resp.json()["status"] in ("started", "already_running")


def test_ui_served():
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
```

- [ ] **Step 2: 確認 test fail**

```bash
cd ~/KyleClaude
python3 -m pytest spectral_capture/tests/test_control_server.py -v 2>&1 | head -15
```
Expected: `ImportError: cannot import name 'app'`

- [ ] **Step 3: 實作 control_server.py**

```python
# spectral_capture/control_server.py
"""
Pi5 多光譜採集遠端控制伺服器。
Run: uvicorn spectral_capture.control_server:app --host 0.0.0.0 --port 8765
"""
import sqlite3
import subprocess
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

ROOT       = Path(__file__).parent.parent          # /home/kyle/KyleClaude
PIPELINE   = ROOT / "spectral_capture/capture_pipeline.py"
DB_PATH    = ROOT / "spectral_capture/data/beans.db"
LOG_PATH   = Path("/tmp/pipeline.log")
UI_PATH    = Path(__file__).parent / "ui/index.html"

app = FastAPI()

# ── subprocess handle ──────────────────────────────────────
_proc: subprocess.Popen | None = None


def _is_running() -> bool:
    return _proc is not None and _proc.poll() is None


def _db_stats() -> dict:
    if not DB_PATH.exists():
        return {"total_beans": 0, "today_beans": 0}
    try:
        conn = sqlite3.connect(str(DB_PATH))
        total = conn.execute("SELECT COUNT(*) FROM bean_spectra").fetchone()[0]
        conn.close()
        return {"total_beans": total}
    except Exception:
        return {"total_beans": 0}


def _recent_log(n: int = 8) -> list[str]:
    if not LOG_PATH.exists():
        return []
    try:
        lines = LOG_PATH.read_text().splitlines()
        return lines[-n:] if len(lines) >= n else lines
    except Exception:
        return []


# ── API ───────────────────────────────────────────────────

class StartRequest(BaseModel):
    origin: str = "unknown"
    roast: str = "green"
    interval: int = 30


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
    _proc = subprocess.Popen(
        [
            sys.executable, "-u", str(PIPELINE),
            "--origin", req.origin,
            "--roast",  req.roast,
            "--interval", str(req.interval),
        ],
        stdout=LOG_PATH.open("w"),
        stderr=subprocess.STDOUT,
        cwd=str(ROOT),
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
```

- [ ] **Step 4: 確認 test pass**

```bash
cd ~/KyleClaude
python3 -m pytest spectral_capture/tests/test_control_server.py -v
```
Expected: 4 tests PASSED

- [ ] **Step 5: Commit**

```bash
git add spectral_capture/control_server.py spectral_capture/tests/test_control_server.py
git commit -m "feat: FastAPI control server with start/stop/status API"
```

---

## Task 3: 手機 Web UI

**Files:**
- Create: `spectral_capture/ui/index.html`

- [ ] **Step 1: 建立 index.html**

```html
<!-- spectral_capture/ui/index.html -->
<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
<title>Huyes 採集指揮台</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: #0f1117;
    color: #e8eaf6;
    font-family: -apple-system, system-ui, sans-serif;
    max-width: 480px;
    margin: 0 auto;
    padding: 16px;
  }
  h1 {
    font-size: 18px;
    font-weight: 600;
    color: #a5d6a7;
    margin-bottom: 4px;
  }
  .subtitle { font-size: 12px; color: #78909c; margin-bottom: 20px; }

  /* Status card */
  .card {
    background: #1a1d27;
    border-radius: 12px;
    padding: 16px;
    margin-bottom: 12px;
  }
  .status-row {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 12px;
  }
  .dot {
    width: 10px; height: 10px;
    border-radius: 50%;
    background: #546e7a;
  }
  .dot.running { background: #66bb6a; box-shadow: 0 0 6px #66bb6a; }
  .status-label { font-size: 15px; font-weight: 500; }

  .stat-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 8px;
  }
  .stat {
    background: #0f1117;
    border-radius: 8px;
    padding: 10px 12px;
  }
  .stat-val {
    font-size: 24px;
    font-weight: 700;
    color: #a5d6a7;
    line-height: 1.1;
  }
  .stat-key { font-size: 11px; color: #78909c; margin-top: 2px; }

  /* Button */
  .btn {
    width: 100%;
    padding: 16px;
    border: none;
    border-radius: 12px;
    font-size: 17px;
    font-weight: 600;
    cursor: pointer;
    transition: opacity 0.15s;
  }
  .btn:active { opacity: 0.7; }
  .btn-start { background: #388e3c; color: #fff; margin-bottom: 12px; }
  .btn-stop  { background: #b71c1c; color: #fff; margin-bottom: 12px; }

  /* Params */
  .param-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 8px 0;
    border-bottom: 1px solid #1e2130;
  }
  .param-row:last-child { border-bottom: none; }
  .param-label { font-size: 13px; color: #b0bec5; }
  select, input[type=number] {
    background: #0f1117;
    color: #e8eaf6;
    border: 1px solid #37474f;
    border-radius: 6px;
    padding: 6px 8px;
    font-size: 13px;
    width: 120px;
    text-align: right;
  }

  /* Log */
  .log-lines {
    font-family: monospace;
    font-size: 11px;
    color: #78909c;
    line-height: 1.6;
    max-height: 180px;
    overflow-y: auto;
  }
  .log-line { padding: 1px 0; }
  .log-line.ok { color: #81c784; }
  .log-line.warn { color: #ffb74d; }
  .log-line.detect { color: #4dd0e1; }

  .section-title {
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: #546e7a;
    margin-bottom: 8px;
  }
</style>
</head>
<body>

<h1>🌿 Huyes 採集指揮台</h1>
<p class="subtitle">Pi5 多光譜豆子採集控制</p>

<!-- Status -->
<div class="card">
  <div class="status-row">
    <div class="dot" id="dot"></div>
    <span class="status-label" id="status-label">載入中...</span>
  </div>
  <div class="stat-grid">
    <div class="stat">
      <div class="stat-val" id="total-beans">—</div>
      <div class="stat-key">累計豆子</div>
    </div>
    <div class="stat">
      <div class="stat-val" id="frame-count">—</div>
      <div class="stat-key">目前幀</div>
    </div>
  </div>
</div>

<!-- Control buttons -->
<button class="btn btn-start" id="btn-start" onclick="startCapture()">▶ 開始採集</button>
<button class="btn btn-stop"  id="btn-stop"  onclick="stopCapture()"  style="display:none">⏸ 暫停採集</button>

<!-- Params -->
<div class="card">
  <div class="section-title">採集設定</div>
  <div class="param-row">
    <span class="param-label">產地</span>
    <input type="text" id="param-origin" value="Taiwan" style="width:120px;text-align:right">
  </div>
  <div class="param-row">
    <span class="param-label">烘焙程度</span>
    <select id="param-roast">
      <option value="green">生豆 green</option>
      <option value="light">淺焙 light</option>
      <option value="medium">中焙 medium</option>
      <option value="dark">深焙 dark</option>
    </select>
  </div>
  <div class="param-row">
    <span class="param-label">採集間隔（秒）</span>
    <input type="number" id="param-interval" value="30" min="10" max="300">
  </div>
</div>

<!-- Log -->
<div class="card">
  <div class="section-title">最近 log</div>
  <div class="log-lines" id="log-lines">—</div>
</div>

<script>
const API = '';  // same origin

function colorLine(line) {
  if (line.includes('[detect]'))  return 'detect';
  if (line.includes('[OK]') || line.includes('done'))    return 'ok';
  if (line.includes('WARN') || line.includes('ERROR')) return 'warn';
  return '';
}

let lastTotal = 0;
let frameCount = 0;

async function refresh() {
  try {
    const r = await fetch(API + '/api/status');
    const d = await r.json();

    const running = d.running;
    document.getElementById('dot').className = 'dot' + (running ? ' running' : '');
    document.getElementById('status-label').textContent = running ? '● 採集中' : '○ 已停止';
    document.getElementById('btn-start').style.display = running ? 'none' : 'block';
    document.getElementById('btn-stop').style.display  = running ? 'block' : 'none';

    document.getElementById('total-beans').textContent = d.total_beans ?? '—';

    // count [detect] lines for frame estimate
    const detects = (d.recent_log || []).filter(l => l.includes('[detect]'));
    if (detects.length) {
      const m = detects[detects.length-1].match(/frame=(\d+)/);
      if (m) document.getElementById('frame-count').textContent = '#' + m[1];
    }

    const logEl = document.getElementById('log-lines');
    logEl.innerHTML = (d.recent_log || []).map(l =>
      `<div class="log-line ${colorLine(l)}">${escHtml(l)}</div>`
    ).join('');
    logEl.scrollTop = logEl.scrollHeight;
  } catch(e) {
    document.getElementById('status-label').textContent = '連線失敗';
  }
}

function escHtml(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

async function startCapture() {
  const body = {
    origin:   document.getElementById('param-origin').value   || 'unknown',
    roast:    document.getElementById('param-roast').value     || 'green',
    interval: parseInt(document.getElementById('param-interval').value) || 30,
  };
  await fetch(API + '/api/capture/start', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body),
  });
  await refresh();
}

async function stopCapture() {
  await fetch(API + '/api/capture/stop', { method: 'POST' });
  await refresh();
}

// Auto-refresh every 3s
refresh();
setInterval(refresh, 3000);
</script>
</body>
</html>
```

- [ ] **Step 2: 本機快速確認 HTML 格式正確（optional，Mac 上）**

```bash
python3 -c "
from pathlib import Path
html = Path('spectral_capture/ui/index.html').read_text()
assert '<title>' in html
assert 'startCapture' in html
assert '/api/status' in html
print('HTML OK:', len(html), 'bytes')
"
```
Expected: `HTML OK: ~6000 bytes`

- [ ] **Step 3: Commit**

```bash
git add spectral_capture/ui/index.html
git commit -m "feat: mobile web UI for capture control (dark theme, vanilla JS)"
```

---

## Task 4: 整合測試 + Push + Pi5 執行

**Files:**
- Modify: `spectral_capture/tests/test_control_server.py`（加 UI 路由測試）

- [ ] **Step 1: 加 UI 路由測試並確認 pass**

在 `spectral_capture/tests/test_control_server.py` 的 `test_ui_served` 已存在，確認包含以下 assertions：

```python
def test_ui_served():
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert b"startCapture" in resp.content   # JS function exists
    assert b"/api/status" in resp.content    # API URL referenced
```

如果 `test_ui_served` 尚未包含後兩個 assert，補上後執行：

```bash
cd ~/KyleClaude
python3 -m pytest spectral_capture/tests/test_control_server.py -v
```
Expected: 4 tests PASSED

- [ ] **Step 2: Push 到 GitHub**

```bash
cd ~/KyleClaude
git push origin main
```

- [ ] **Step 3: Pi5 pull + 安裝依賴 + 啟動**

```bash
# 在 Pi5 上執行
ssh kyle@raspberrypi.local

cd ~/KyleClaude
git pull origin main --rebase

pip3 install fastapi "uvicorn[standard]"

# 啟動控制伺服器
cd ~/KyleClaude
uvicorn spectral_capture.control_server:app --host 0.0.0.0 --port 8765 &
echo "Server started"
```

- [ ] **Step 4: 手機驗證**

手機連上同一 WiFi，開瀏覽器：
```
http://raspberrypi.local:8765
```

預期看到：深色主題介面，顯示「○ 已停止」，累計豆子數字，「▶ 開始採集」按鈕。

Tap「開始採集」→ 狀態變「● 採集中」，log 開始出現。

- [ ] **Step 5: 設定 Pi5 開機自啟（可選）**

```bash
# Pi5 上建立 systemd service
cat > /tmp/huyes-control.service << 'EOF'
[Unit]
Description=Huyes Capture Control Server
After=network.target

[Service]
User=kyle
WorkingDirectory=/home/kyle/KyleClaude
ExecStart=/usr/local/bin/uvicorn spectral_capture.control_server:app --host 0.0.0.0 --port 8765
Restart=always

[Install]
WantedBy=multi-user.target
EOF

sudo mv /tmp/huyes-control.service /etc/systemd/system/
sudo systemctl enable huyes-control
sudo systemctl start huyes-control
sudo systemctl status huyes-control
```
Expected: `Active: active (running)`

- [ ] **Step 6: Final commit**

```bash
cd ~/KyleClaude
git add -A
git commit -m "feat: complete mobile capture control server — FastAPI + mobile UI + systemd"
```

---

## 驗收標準

| 測試 | 方式 | Pass 條件 |
|------|------|-----------|
| API 單元測試 | `pytest test_control_server.py` | 4/4 pass |
| 手機 UI 載入 | 手機瀏覽器開 `http://raspberrypi.local:8765` | 顯示採集指揮台介面 |
| 開始採集 | Tap「▶ 開始採集」 | log 出現 `[capture] frame 0` |
| 停止採集 | Tap「⏸ 暫停採集」 | log 出現 `stopped`，按鈕切換 |
| 統計更新 | 等待 1 幀完成 | 累計豆子數字增加 |
