"""
Mac Mini Agent Receiver — port 8081
接收 Pi5 主動推送的 webhook 事件。

Pi5 的 health_server.py 在 job 完成後會 POST 到：
  http://192.168.68.173:8081/agent/event

執行方式：
  source ~/KyleClaude/venv/bin/activate
  uvicorn agent_receiver:app --host 0.0.0.0 --port 8081
"""

import json
from datetime import datetime

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from database import PiEvent, Batch, SessionLocal, init_db

app = FastAPI(title="Huyes Agent Receiver", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])

HUYES_API = "http://localhost:8765"
PI5_API   = "http://raspberrypi.local:8080"


@app.on_event("startup")
def startup():
    init_db()


@app.post("/agent/event")
async def receive_event(request: Request):
    payload = await request.json()
    event_type = payload.get("event", "unknown")
    job_id = payload.get("job_id")

    print(f"[Pi5 → Brain] {event_type}  job={job_id}")

    db = SessionLocal()
    try:
        # 存事件紀錄
        event = PiEvent(
            event_type=event_type,
            session_id=job_id,
            payload=payload,
        )
        db.add(event)
        db.commit()

        # job 完成 → 拉 Pi5 結果，建立 Batch
        if event_type == "job_finished" and payload.get("status") == "done":
            await _process_completed_job(job_id, payload, db)

    finally:
        db.close()

    return {"status": "received"}


async def _process_completed_job(job_id: str, payload: dict, db):
    """從 Pi5 拉取分析結果，轉成 Batch 存入 Mac Mini DB。"""
    result_url = payload.get("result_url", f"{PI5_API}/pipeline/result/{job_id}")

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(result_url)
            result = r.json()
    except Exception as e:
        print(f"  [warn] 拉取結果失敗：{e}")
        return

    session_dir = result.get("session_dir", "")
    session_name = session_dir.split("/")[-1] if session_dir else job_id

    # 解析 mold report CSV → beans
    beans = _parse_mold_report(result.get("report", {}).get("csv", ""))

    if not beans:
        print(f"  [warn] 無法解析 beans，略過 Batch 建立")
        return

    grade_dist = {"精選": 0, "標準": 0, "混豆": 0, "淘汰": 0}
    for b in beans:
        grade_dist[b["grade"]] = grade_dist.get(b["grade"], 0) + 1
    valid = [b for b in beans if not b.get("reject")]
    avg_bqs = sum(b["bqs"] for b in valid) / len(valid) if valid else 0.0

    batch_id = job_id.upper()
    existing = db.query(Batch).filter(Batch.id == batch_id).first()
    if not existing:
        batch = Batch(
            id=batch_id,
            created_at=datetime.utcnow(),
            bean_count=len(beans),
            grade_dist=grade_dist,
            avg_bqs=round(avg_bqs, 1),
            beans=beans,
            notes=f"Pi5 auto: {session_name}",
        )
        db.add(batch)
        db.commit()
        print(f"  ✓ Batch 建立：{batch_id}  豆子：{len(beans)}  BQS：{avg_bqs:.1f}")
    else:
        print(f"  Batch {batch_id} 已存在，略過")


def _parse_mold_report(csv_text: str) -> list[dict]:
    """把 mold_analysis 的 CSV 轉成 BQS beans list。"""
    if not csv_text:
        return []
    beans = []
    lines = csv_text.strip().splitlines()
    if len(lines) < 2:
        return []
    header = [h.strip() for h in lines[0].split(",")]
    for line in lines[1:]:
        vals = [v.strip() for v in line.split(",")]
        row = dict(zip(header, vals))
        try:
            bean_id  = int(row.get("bean_id", 0))
            fl_norm  = float(row.get("fl_norm", 0))
            mahal    = float(row.get("mahal_dist", row.get("mahalanobis", 0)))
            reject   = fl_norm >= 6.0

            safety_score = max(0.0, min(100.0, 100 - fl_norm * 15))
            defect_score = max(0.0, min(100.0, 100 - mahal * 30))
            bqs = defect_score * 0.55 + safety_score * 0.35 + 75.0 * 0.10

            if reject:        grade = "淘汰"
            elif bqs >= 90:   grade = "精選"
            elif bqs >= 70:   grade = "標準"
            elif bqs >= 40:   grade = "混豆"
            else:              grade = "淘汰"

            beans.append({
                "bean_id": bean_id, "bqs": round(bqs, 1), "grade": grade,
                "defect": round(defect_score, 1), "roast": None,
                "safety": round(safety_score, 1), "morphology": 75.0,
                "reject": reject,
            })
        except (ValueError, KeyError):
            continue
    return beans


@app.get("/health")
def health():
    return {"status": "ok", "service": "huyes-agent-receiver", "port": 8081}


# ── 自動 BQS 計算（整合進 job_finished 流程）────────────────────
def _compute_bqs_from_mold(mold_rows: list[dict]) -> list[dict]:
    """把 mold_analysis 輸出轉成 BQS beans list。"""
    beans = []
    for row in mold_rows:
        fl_norm = float(row.get("fl_norm", 0))
        mahal   = float(row.get("mahal_dist", row.get("mahalanobis", 0)))
        reject  = fl_norm >= 6.0
        safety  = max(0.0, min(100.0, 100 - fl_norm * 15))
        defect  = max(0.0, min(100.0, 100 - mahal * 30))
        bqs     = defect * 0.55 + safety * 0.35 + 75.0 * 0.10
        if reject:       grade = "淘汰"
        elif bqs >= 90:  grade = "精選"
        elif bqs >= 70:  grade = "標準"
        elif bqs >= 40:  grade = "混豆"
        else:             grade = "淘汰"
        beans.append({
            "bean_id": int(row.get("bean_id", 0)),
            "bqs": round(bqs, 1), "grade": grade,
            "defect": round(defect, 1), "roast": None,
            "safety": round(safety, 1), "morphology": 75.0,
            "reject": reject,
        })
    return beans
