"""
Huyes App Backend — FastAPI
執行方式：
  cd huyes-app/backend
  source ../../venv/bin/activate
  uvicorn main:app --host 0.0.0.0 --port 8765 --reload
"""

import io
import json
import math
import uuid
from datetime import datetime
from pathlib import Path

import qrcode
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import Batch, Origin, PiEvent, get_db, init_db

app = FastAPI(title="Huyes API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC_DIR = Path(__file__).parent.parent / "frontend" / "dist"

# ── 啟動時初始化資料庫 ────────────────────────────────────────────
@app.on_event("startup")
def startup():
    init_db()


@app.get("/health")
def health():
    return {"status": "ok", "service": "huyes-api", "version": "0.1.0"}


# ── Schemas ───────────────────────────────────────────────────────
class BeanRecord(BaseModel):
    bean_id: int
    bqs: float
    grade: str
    defect: float
    roast: float | None
    safety: float
    morphology: float
    reject: bool


class BatchCreate(BaseModel):
    beans: list[BeanRecord]
    spectra_vec: list[float] | None = None   # mean 10-band vector
    notes: str = ""


class BatchSummary(BaseModel):
    id: str
    created_at: str
    bean_count: int
    avg_bqs: float
    grade_dist: dict
    notes: str


# ── 批次 API ─────────────────────────────────────────────────────
@app.post("/batch", response_model=BatchSummary)
def create_batch(payload: BatchCreate, db: Session = Depends(get_db)):
    batch_id = str(uuid.uuid4())[:8].upper()

    grade_dist = {"精選": 0, "標準": 0, "混豆": 0, "淘汰": 0}
    for b in payload.beans:
        grade_dist[b.grade] = grade_dist.get(b.grade, 0) + 1

    valid = [b for b in payload.beans if not b.reject]
    avg_bqs = sum(b.bqs for b in valid) / len(valid) if valid else 0.0

    batch = Batch(
        id=batch_id,
        created_at=datetime.utcnow(),
        bean_count=len(payload.beans),
        grade_dist=grade_dist,
        avg_bqs=round(avg_bqs, 1),
        beans=[b.model_dump() for b in payload.beans],
        spectra_vec=payload.spectra_vec,
        notes=payload.notes,
    )
    db.add(batch)
    db.commit()
    return BatchSummary(
        id=batch_id,
        created_at=batch.created_at.isoformat(),
        bean_count=batch.bean_count,
        avg_bqs=batch.avg_bqs,
        grade_dist=grade_dist,
        notes=batch.notes,
    )


@app.get("/batch/{batch_id}")
def get_batch(batch_id: str, db: Session = Depends(get_db)):
    batch = db.query(Batch).filter(Batch.id == batch_id.upper()).first()
    if not batch:
        raise HTTPException(404, "Batch not found")
    return {
        "id": batch.id,
        "created_at": batch.created_at.isoformat(),
        "bean_count": batch.bean_count,
        "avg_bqs": batch.avg_bqs,
        "grade_dist": batch.grade_dist,
        "beans": batch.beans,
        "spectra_vec": batch.spectra_vec,
        "notes": batch.notes,
    }


@app.get("/batch/{batch_id}/qr")
def get_qr(batch_id: str, host: str = "localhost", port: int = 8765):
    url = f"http://{host}:{port}/b/{batch_id.upper()}"
    img = qrcode.make(url, box_size=8, border=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return StreamingResponse(buf, media_type="image/png")


@app.get("/batches")
def list_batches(limit: int = 20, db: Session = Depends(get_db)):
    rows = db.query(Batch).order_by(Batch.created_at.desc()).limit(limit).all()
    return [{"id": r.id, "created_at": r.created_at.isoformat(),
             "bean_count": r.bean_count, "avg_bqs": r.avg_bqs,
             "grade_dist": r.grade_dist} for r in rows]


# ── 產地搜尋 API ──────────────────────────────────────────────────
@app.get("/origins/search")
def search_origins(batch_id: str, top_k: int = 5, db: Session = Depends(get_db)):
    batch = db.query(Batch).filter(Batch.id == batch_id.upper()).first()
    if not batch:
        raise HTTPException(404, "Batch not found")

    if not batch.spectra_vec:
        # 無光譜資料時回傳熱門產地
        origins = db.query(Origin).limit(top_k).all()
        return [_origin_dict(o, score=None) for o in origins]

    all_origins = db.query(Origin).all()
    if not all_origins:
        return []

    query_vec = batch.spectra_vec
    scored = []
    for o in all_origins:
        if o.spectra_vec and len(o.spectra_vec) == len(query_vec):
            dist = _cosine_dist(query_vec, o.spectra_vec)
            scored.append((dist, o))

    scored.sort(key=lambda x: x[0])
    return [_origin_dict(o, score=round(1 - d, 3)) for d, o in scored[:top_k]]


def _cosine_dist(a: list, b: list) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x ** 2 for x in a))
    nb = math.sqrt(sum(x ** 2 for x in b))
    return 1 - dot / (na * nb + 1e-8)


def _origin_dict(o: Origin, score) -> dict:
    return {
        "id": o.id, "name": o.name, "country": o.country,
        "region": o.region, "variety": o.variety, "process": o.process,
        "description": o.description, "buy_url": o.buy_url,
        "image_url": o.image_url, "similarity": score,
    }


# ── 前端 PWA（build 後掛載）──────────────────────────────────────
if STATIC_DIR.exists():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    @app.get("/b/{batch_id}")
    @app.get("/")
    def serve_spa(batch_id: str = ""):
        return FileResponse(STATIC_DIR / "index.html")
