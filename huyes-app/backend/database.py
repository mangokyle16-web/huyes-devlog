from datetime import datetime
from pathlib import Path

from sqlalchemy import JSON, Boolean, Column, DateTime, Float, Integer, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

DB_PATH = Path(__file__).parent / "huyes.db"
engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)


class Base(DeclarativeBase):
    pass


class Batch(Base):
    __tablename__ = "batches"
    id          = Column(String, primary_key=True)       # UUID
    created_at  = Column(DateTime, default=datetime.utcnow)
    bean_count  = Column(Integer)
    grade_dist  = Column(JSON)   # {"精選":N, "標準":N, "混豆":N, "淘汰":N}
    avg_bqs     = Column(Float)
    beans       = Column(JSON)   # list of per-bean BQS breakdown dicts
    spectra_vec = Column(JSON)   # mean 10-band vector（for origin matching）
    notes       = Column(String, default="")


class Origin(Base):
    __tablename__ = "origins"
    id          = Column(Integer, primary_key=True, autoincrement=True)
    name        = Column(String)         # 產地/莊園名
    country     = Column(String)
    region      = Column(String)
    variety     = Column(String)
    process     = Column(String)         # washed / natural / honey
    description = Column(String)
    spectra_vec = Column(JSON)           # 10-band 光譜指紋
    buy_url     = Column(String)
    image_url   = Column(String)
    source      = Column(String)         # 爬取來源


class PiEvent(Base):
    """Pi5 主動推送的事件紀錄。"""
    __tablename__ = "pi_events"
    id          = Column(Integer, primary_key=True, autoincrement=True)
    received_at = Column(DateTime, default=datetime.utcnow)
    event_type  = Column(String)   # session_complete | alert | status | log
    session_id  = Column(String, nullable=True)
    payload     = Column(JSON)
    read        = Column(Boolean, default=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    Base.metadata.create_all(engine)
