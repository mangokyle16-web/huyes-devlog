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
    resp = client.post("/api/capture/start", json={
        "origin": "TestOrigin", "roast": "green", "interval": 30
    })
    assert resp.status_code == 200
    assert resp.json()["status"] in ("started", "already_running")


def test_ui_served():
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert b"startCapture" in resp.content
    assert b"/api/status" in resp.content
