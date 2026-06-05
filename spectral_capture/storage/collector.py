"""
Writes bean spectral vectors to SQLite for Siamese network training (Phase 1 data collection).
Schema matches docs/superpowers/plans/2026-06-01-siamese-bean-defect.md Phase 1.
"""
import sqlite3
from pathlib import Path
import numpy as np
import spectral_capture.config as cfg

CREATE_SQL = """
CREATE TABLE IF NOT EXISTS bean_spectra (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    captured_at REAL    NOT NULL,
    frame_id    INTEGER NOT NULL,
    bean_cx     INTEGER NOT NULL,
    bean_cy     INTEGER NOT NULL,
    area_px     INTEGER NOT NULL,
    b450        REAL NOT NULL,
    b560        REAL NOT NULL,
    b650        REAL NOT NULL,
    b730        REAL NOT NULL,
    b840        REAL NOT NULL,
    origin      TEXT DEFAULT '',
    roast_level TEXT DEFAULT 'green',
    label       TEXT DEFAULT 'unknown'
);
CREATE INDEX IF NOT EXISTS idx_captured_at ON bean_spectra(captured_at);
"""


class Collector:
    def __init__(self, db_path: Path = None):
        if db_path is None:
            db_path = cfg.DB_PATH
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.executescript(CREATE_SQL)
        self._conn.commit()

    def insert_bean(self, frame_id: int, timestamp_us: int,
                    cx: int, cy: int, area_px: int,
                    spec_vec: np.ndarray) -> int:
        """
        Insert one bean's spectral record. Returns row id.
        spec_vec: (5,) float32 corresponding to [450, 560, 650, 730, 840] nm
        """
        row = (
            timestamp_us / 1e6,
            frame_id, cx, cy, area_px,
            float(spec_vec[0]), float(spec_vec[1]), float(spec_vec[2]),
            float(spec_vec[3]), float(spec_vec[4]),
            cfg.ORIGIN, cfg.ROAST_LEVEL,
        )
        cur = self._conn.execute(
            "INSERT INTO bean_spectra "
            "(captured_at, frame_id, bean_cx, bean_cy, area_px, "
            " b450, b560, b650, b730, b840, origin, roast_level) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            row,
        )
        self._conn.commit()
        return cur.lastrowid

    def stats(self) -> dict:
        cur = self._conn.execute(
            "SELECT COUNT(*), MIN(captured_at), MAX(captured_at) FROM bean_spectra"
        )
        total, t_min, t_max = cur.fetchone()
        return {"total": total, "t_min": t_min, "t_max": t_max}

    def close(self):
        self._conn.close()
