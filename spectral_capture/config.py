from pathlib import Path

PROJECT_ROOT  = Path(__file__).parent
QSBS_PATH     = PROJECT_ROOT / "capture" / "msi.qsbs"
QS_DAEMON_BIN = PROJECT_ROOT / "capture" / "qs_daemon"
DB_PATH       = PROJECT_ROOT / "data" / "beans.db"

CAMERA_W      = 1600
CAMERA_H      = 1200
N_BANDS       = 5
BAND_NM       = [450, 560, 650, 730, 840]
NIR_BAND_IDX  = 4
TARGET_FPS    = 13
FRAME_BUDGET_MS = 1000 // TARGET_FPS  # 77ms

BEAN_MIN_AREA_PX = 500
BEAN_MAX_AREA_PX = 8000
BELT_SPEED_CM_S  = 4.6

ORIGIN       = "unknown"
ROAST_LEVEL  = "green"
