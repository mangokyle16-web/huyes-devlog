# Spectral Capture Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Pi5 上以 13 fps 持續擷取 CM020D 多光譜影像，解析 5 波段 numpy cube，偵測咖啡豆位置並提取光譜向量，存入 SQLite 供 Siamese 網路訓練使用。

**Architecture:** C++ daemon 使用 QS SDK 以 13 fps 迴圈擷取 .qs 幀並轉成 QAB（5 波段），透過 stdout binary protocol 串流給 Python pipeline。Python 端三個執行緒依序負責：解析幀 → 偵測豆子 → 寫入資料庫。架構設計讓未來接上 Hailo-8 Siamese MLP 只需新增一個推論執行緒。

**Tech Stack:** Python 3.11, C++17 (QS SDK: qs_camera/qs_agriculture/qs_fileio), NumPy, OpenCV, SQLite3, threading/queue

**Belt speed:** 4.6 cm/s ｜ **Target FPS:** 13 ｜ **Camera:** CM020D, 1600×1200, 5 bands (450/560/650/730/840nm)

---

## File Structure

```
KyleClaude/spectral_capture/
├── capture/
│   ├── qs_daemon.cpp       # C++ 迴圈擷取器：QS SDK → QAB → binary stdout
│   └── Makefile            # 在 Pi5 上 link QS SDK shared libs
├── pipeline/
│   ├── frame_reader.py     # 啟動 C++ subprocess，讀 binary frames → Queue
│   ├── qab_parser.py       # QAB bytes → numpy (H×W×5) float32
│   └── bean_detector.py    # NIR 波段分割 → 豆子 bbox + 光譜向量
├── storage/
│   └── collector.py        # 寫入 SQLite：每顆豆的光譜向量 + 元資料
├── config.py               # 路徑、FPS、波段定義、相機參數
├── main.py                 # 主程式：串接所有執行緒，SIGINT graceful stop
└── tests/
    ├── fixtures/
    │   └── make_fake_qab.py  # 產生合成 QAB 測試資料（不需相機）
    ├── test_qab_parser.py
    ├── test_bean_detector.py
    └── test_frame_reader.py
```

**C++ stdout binary protocol**（qs_daemon → Python frame_reader）：
```
每幀 = [frame_id: uint64 LE] [timestamp_us: int64 LE] [qab_size: uint64 LE] [qab_data: qab_size bytes]
```

---

## Task 1: Config + 測試夾具

**Files:**
- Create: `spectral_capture/config.py`
- Create: `spectral_capture/tests/fixtures/make_fake_qab.py`

- [ ] **Step 1: 建立 spectral_capture 目錄結構**

```bash
cd ~/KyleClaude
mkdir -p spectral_capture/capture spectral_capture/pipeline \
         spectral_capture/storage spectral_capture/tests/fixtures
touch spectral_capture/__init__.py spectral_capture/pipeline/__init__.py \
      spectral_capture/storage/__init__.py
```

- [ ] **Step 2: 建立 config.py**

```python
# spectral_capture/config.py
from pathlib import Path

# ── 路徑 ─────────────────────────────────────────────────
PROJECT_ROOT  = Path(__file__).parent
QSBS_PATH     = PROJECT_ROOT / "capture" / "msi.qsbs"   # 相機標定檔
QS_DAEMON_BIN = PROJECT_ROOT / "capture" / "qs_daemon"  # 編譯後執行檔
DB_PATH       = PROJECT_ROOT / "data" / "beans.db"

# ── 相機 ─────────────────────────────────────────────────
CAMERA_W      = 1600
CAMERA_H      = 1200
N_BANDS       = 5
BAND_NM       = [450, 560, 650, 730, 840]  # nm，對應 QAB 波段順序
NIR_BAND_IDX  = 4   # 840nm，用於豆子分割（最高對比）
TARGET_FPS    = 13
FRAME_BUDGET_MS = 1000 // TARGET_FPS  # 77ms

# ── 偵測參數 ─────────────────────────────────────────────
BEAN_MIN_AREA_PX = 500    # 最小豆子面積（像素）
BEAN_MAX_AREA_PX = 8000   # 最大豆子面積（像素）
BELT_SPEED_CM_S  = 4.6    # 實測皮帶速度

# ── 資料收集 ─────────────────────────────────────────────
ORIGIN       = "unknown"   # 執行時可覆蓋: python main.py --origin Ethiopia
ROAST_LEVEL  = "green"
```

- [ ] **Step 3: 建立合成 QAB 測試夾具**

```python
# spectral_capture/tests/fixtures/make_fake_qab.py
"""
產生合成 QAB binary，格式：N_BANDS 個 uint16 頻帶，每個 H×W 順序排列。
不需要相機即可測試 Python pipeline。
"""
import numpy as np
import struct
from pathlib import Path

W, H, N = 1600, 1200, 5

def make_fake_qab(n_beans: int = 5, seed: int = 42) -> bytes:
    """
    生成合成 QAB bytes：
    - 背景：模擬綠色輸送帶（高 NIR 反射率）
    - 豆子：N 個隨機位置的棕色橢圓（低 NIR，有光譜特徵）
    """
    rng = np.random.default_rng(seed)
    # 5 bands, each H×W uint16
    # 背景反射率（归一化後近似值）：[0.15, 0.45, 0.25, 0.20, 0.72]
    bg_vals = np.array([0.15, 0.45, 0.25, 0.20, 0.72])
    # 豆子反射率：[0.08, 0.14, 0.18, 0.22, 0.35]
    bean_vals = np.array([0.08, 0.14, 0.18, 0.22, 0.35])

    cube = np.zeros((N, H, W), dtype=np.float32)
    for b in range(N):
        cube[b] = bg_vals[b]

    # 畫豆子橢圓
    import cv2
    for _ in range(n_beans):
        cx = int(rng.integers(100, W - 100))
        cy = int(rng.integers(100, H - 100))
        rx, ry = int(rng.integers(12, 22)), int(rng.integers(8, 15))
        for b in range(N):
            band = cube[b]
            cv2.ellipse(band, (cx, cy), (rx, ry), 0, 0, 360,
                        bean_vals[b] + rng.uniform(-0.02, 0.02), -1)
        # 模擬一顆瑕疵豆（NIR 更低）
        if _ == 0:
            for b in range(N):
                cv2.ellipse(cube[b], (cx, cy), (rx, ry), 0, 0, 360,
                            bean_vals[b] * 0.7, -1)

    # 轉 uint16
    cube_u16 = (cube * 65535).clip(0, 65535).astype(np.uint16)
    # 序列化：band0[H×W] + band1[H×W] + ...
    return cube_u16.tobytes()


if __name__ == "__main__":
    out = Path(__file__).parent / "fake_5bean.qab"
    data = make_fake_qab(n_beans=5)
    out.write_bytes(data)
    print(f"Written {len(data):,} bytes → {out}")
    # 驗證大小
    expected = W * H * N * 2
    assert len(data) == expected, f"Expected {expected}, got {len(data)}"
    print("OK")
```

- [ ] **Step 4: 執行夾具，確認大小正確**

```bash
cd ~/KyleClaude
python3 spectral_capture/tests/fixtures/make_fake_qab.py
```
Expected output:
```
Written 19,200,000 bytes → .../fake_5bean.qab
OK
```

- [ ] **Step 5: commit**

```bash
git add spectral_capture/
git commit -m "feat: spectral_capture project skeleton + config + test fixture"
```

---

## Task 2: QAB Parser

**Files:**
- Create: `spectral_capture/pipeline/qab_parser.py`
- Create: `spectral_capture/tests/test_qab_parser.py`

- [ ] **Step 1: 寫 failing test**

```python
# spectral_capture/tests/test_qab_parser.py
import numpy as np
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from spectral_capture.pipeline.qab_parser import parse_qab, QABFormatError
from spectral_capture.tests.fixtures.make_fake_qab import make_fake_qab

def test_parse_returns_correct_shape():
    data = make_fake_qab(n_beans=3)
    cube = parse_qab(data)
    assert cube.shape == (1200, 1600, 5), f"Got {cube.shape}"

def test_parse_normalized_range():
    data = make_fake_qab()
    cube = parse_qab(data)
    assert cube.dtype == np.float32
    assert cube.min() >= 0.0
    assert cube.max() <= 1.0

def test_parse_wrong_size_raises():
    import pytest
    with pytest.raises(QABFormatError):
        parse_qab(b"\x00" * 100)

def test_nir_band_background_is_higher():
    """綠色輸送帶 NIR (band 4) 反射率應高於豆子區域"""
    data = make_fake_qab(n_beans=1, seed=0)
    cube = parse_qab(data)
    nir = cube[:, :, 4]
    # 背景（邊角）應高於 0.5，豆子區域應低於 0.5
    corner_mean = np.mean(nir[:50, :50])
    assert corner_mean > 0.5, f"Corner NIR {corner_mean:.3f} not high enough"
```

- [ ] **Step 2: 確認 test fail**

```bash
cd ~/KyleClaude
python3 -m pytest spectral_capture/tests/test_qab_parser.py -v
```
Expected: `ImportError: cannot import name 'parse_qab'`

- [ ] **Step 3: 實作 qab_parser.py**

```python
# spectral_capture/pipeline/qab_parser.py
"""
QAB binary → numpy cube (H, W, 5) float32 [0,1]

QAB 格式（QS SDK qsToQab() 輸出）：
  5 個波段，每個波段 H×W uint16，依序排列：
  band0[H×W] | band1[H×W] | band2[H×W] | band3[H×W] | band4[H×W]
  對應波長：450 / 560 / 650 / 730 / 840 nm

注意：若 qsToQab() 實際輸出格式不同（例如 uint8 或 interleaved），
      調整 BYTES_PER_PIXEL 和 reshape 順序即可。
"""
import numpy as np
from spectral_capture.config import CAMERA_W, CAMERA_H, N_BANDS

BYTES_PER_PIXEL = 2  # uint16
EXPECTED_BYTES  = CAMERA_H * CAMERA_W * N_BANDS * BYTES_PER_PIXEL


class QABFormatError(ValueError):
    pass


def parse_qab(qab_bytes: bytes) -> np.ndarray:
    """
    QAB bytes → numpy array (H, W, N_BANDS) float32, 正規化至 [0, 1]

    Args:
        qab_bytes: qsToQab() 輸出的 raw bytes

    Returns:
        cube: shape (CAMERA_H, CAMERA_W, N_BANDS), dtype float32
    """
    if len(qab_bytes) != EXPECTED_BYTES:
        raise QABFormatError(
            f"QAB size mismatch: got {len(qab_bytes)}, "
            f"expected {EXPECTED_BYTES} ({CAMERA_H}×{CAMERA_W}×{N_BANDS}×{BYTES_PER_PIXEL})"
        )
    raw = np.frombuffer(qab_bytes, dtype=np.uint16)
    # Shape: (N_BANDS, H, W) → transpose to (H, W, N_BANDS)
    cube = raw.reshape(N_BANDS, CAMERA_H, CAMERA_W).transpose(1, 2, 0)
    return cube.astype(np.float32) / 65535.0
```

- [ ] **Step 4: 確認 test pass**

```bash
python3 -m pytest spectral_capture/tests/test_qab_parser.py -v
```
Expected: 4 tests PASSED

- [ ] **Step 5: commit**

```bash
git add spectral_capture/pipeline/qab_parser.py spectral_capture/tests/test_qab_parser.py
git commit -m "feat: QAB parser with uint16 sequential-band format"
```

---

## Task 3: Bean Detector

**Files:**
- Create: `spectral_capture/pipeline/bean_detector.py`
- Create: `spectral_capture/tests/test_bean_detector.py`

- [ ] **Step 1: 寫 failing test**

```python
# spectral_capture/tests/test_bean_detector.py
import numpy as np
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from spectral_capture.pipeline.qab_parser import parse_qab
from spectral_capture.pipeline.bean_detector import detect_beans, BeanDetection
from spectral_capture.tests.fixtures.make_fake_qab import make_fake_qab

def test_detect_correct_count():
    cube = parse_qab(make_fake_qab(n_beans=5, seed=1))
    beans = detect_beans(cube)
    # 允許 ±1 誤差（橢圓可能部分融合或太小）
    assert 3 <= len(beans) <= 6, f"Expected ~5 beans, got {len(beans)}"

def test_bean_has_spectral_vector():
    cube = parse_qab(make_fake_qab(n_beans=3))
    beans = detect_beans(cube)
    assert len(beans) > 0
    b = beans[0]
    assert isinstance(b, BeanDetection)
    assert b.spec_vec.shape == (5,)
    assert b.spec_vec.dtype == np.float32

def test_bean_bbox_within_image():
    cube = parse_qab(make_fake_qab(n_beans=3))
    beans = detect_beans(cube)
    for b in beans:
        x, y, w, h = b.bbox
        assert x >= 0 and y >= 0
        assert x + w <= 1600
        assert y + h <= 1200

def test_belt_background_not_detected():
    """空白輸送帶（無豆子）應回傳 0 個偵測"""
    # 全部設為背景（高 NIR）
    cube = np.zeros((1200, 1600, 5), dtype=np.float32)
    cube[:, :, 4] = 0.72  # NIR band = 高反射率（綠色輸送帶）
    cube[:, :, :4] = [0.15, 0.45, 0.25, 0.20]
    beans = detect_beans(cube)
    assert len(beans) == 0, f"Expected 0 beans on empty belt, got {len(beans)}"
```

- [ ] **Step 2: 確認 test fail**

```bash
python3 -m pytest spectral_capture/tests/test_bean_detector.py -v
```
Expected: `ImportError: cannot import name 'detect_beans'`

- [ ] **Step 3: 實作 bean_detector.py**

```python
# spectral_capture/pipeline/bean_detector.py
"""
咖啡豆偵測：使用 NIR 波段（840nm）對輸送帶進行 Otsu 閾值分割。
原理：綠色 PVC 輸送帶在 NIR 有高反射率（~0.72），
     咖啡豆在 NIR 反射率較低（~0.35），對比清晰。
"""
import cv2
import numpy as np
from dataclasses import dataclass
from spectral_capture.config import NIR_BAND_IDX, BEAN_MIN_AREA_PX, BEAN_MAX_AREA_PX

@dataclass
class BeanDetection:
    cx: int                   # 中心 x（像素）
    cy: int                   # 中心 y（像素）
    bbox: tuple               # (x, y, w, h)
    area_px: int              # 面積（像素）
    spec_vec: np.ndarray      # shape (5,) float32，波段平均反射率


def detect_beans(cube: np.ndarray) -> list[BeanDetection]:
    """
    Args:
        cube: (H, W, 5) float32 [0,1]，來自 parse_qab()

    Returns:
        list of BeanDetection，依 cx 排序（左→右）
    """
    nir = (cube[:, :, NIR_BAND_IDX] * 255).astype(np.uint8)

    # Otsu 閾值：自動找豆子（暗）vs 背景（亮）分界
    _, mask = cv2.threshold(nir, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    # 形態學清理：去雜訊、填補豆子內部孔洞
    k_open  = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    k_close = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN,  k_open)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k_close)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    results = []
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if not (BEAN_MIN_AREA_PX < area < BEAN_MAX_AREA_PX):
            continue
        x, y, w, h = cv2.boundingRect(cnt)
        cx, cy = x + w // 2, y + h // 2

        # 光譜向量：豆子 ROI 各波段的平均反射率
        roi = cube[y:y+h, x:x+w]           # (h, w, 5)
        spec_vec = roi.mean(axis=(0, 1))    # (5,)

        results.append(BeanDetection(
            cx=cx, cy=cy,
            bbox=(x, y, w, h),
            area_px=int(area),
            spec_vec=spec_vec.astype(np.float32),
        ))

    return sorted(results, key=lambda b: b.cx)
```

- [ ] **Step 4: 確認 test pass**

```bash
python3 -m pytest spectral_capture/tests/test_bean_detector.py -v
```
Expected: 4 tests PASSED

- [ ] **Step 5: commit**

```bash
git add spectral_capture/pipeline/bean_detector.py spectral_capture/tests/test_bean_detector.py
git commit -m "feat: NIR-band bean detector with Otsu threshold + spectral vector extraction"
```

---

## Task 4: C++ Capture Daemon

**Files:**
- Create: `spectral_capture/capture/qs_daemon.cpp`
- Create: `spectral_capture/capture/Makefile`

*此 Task 在 Pi5 上執行（需要 QS SDK）。Mac Mini 上可建立 stub 版本供測試。*

- [ ] **Step 1: 建立 qs_daemon.cpp（Pi5 上執行）**

```cpp
// spectral_capture/capture/qs_daemon.cpp
/**
 * QS Capture Daemon - 13 fps 連續擷取
 * 輸出協定（stdout binary）：
 *   每幀 = [frame_id: uint64 LE][timestamp_us: int64 LE][qab_size: uint64 LE][qab_data: bytes]
 * stderr：狀態訊息（不干擾 binary 輸出）
 */
#include "qs_camera.h"
#include "qs_fileio.h"
#include "qs_agriculture.h"
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <chrono>
#include <thread>
#include <csignal>

static volatile bool g_running = true;
static void onSigint(int) { g_running = false; }

static int64_t now_us() {
    using namespace std::chrono;
    return duration_cast<microseconds>(
        steady_clock::now().time_since_epoch()).count();
}

// 將 little-endian uint64 寫入 stdout
static void write_u64(uint64_t v) {
    fwrite(&v, 8, 1, stdout);
}
static void write_i64(int64_t v) {
    fwrite(&v, 8, 1, stdout);
}

int main(int argc, char* argv[]) {
    const char* qsbs_path = (argc >= 2) ? argv[1] : "msi.qsbs";
    const int   target_fps = (argc >= 3) ? atoi(argv[2]) : 13;
    const int   frame_ms   = 1000 / target_fps;

    signal(SIGINT, onSigint);
    signal(SIGTERM, onSigint);

    // 讀標定檔
    uint8_t* qsbsData = nullptr; size_t qsbsSize = 0;
    if (loadQsbsFile(qsbs_path, &qsbsData, &qsbsSize) != QS_ERR_SUCCESS) {
        fprintf(stderr, "[qs_daemon] ERROR: cannot load %s\n", qsbs_path);
        return 1;
    }
    fprintf(stderr, "[qs_daemon] calibration: %zu bytes\n", qsbsSize);

    // 初始化農業 context（用於 qsToQab）
    QsAgricultureContext* agCtx = nullptr;
    if (initQsAgriculture(&agCtx, qsbsData, qsbsSize) != QS_ERR_SUCCESS) {
        fprintf(stderr, "[qs_daemon] ERROR: initQsAgriculture failed\n");
        return 1;
    }

    // 偵測相機
    QsCameraContext** cameras = nullptr; int camCount = 0;
    if (enumQsCamera(&cameras, &camCount) != QS_ERR_SUCCESS || camCount == 0) {
        fprintf(stderr, "[qs_daemon] ERROR: no QS camera detected\n");
        return 1;
    }
    if (openQsCamera(cameras[0], false) != QS_ERR_SUCCESS) {
        fprintf(stderr, "[qs_daemon] ERROR: openQsCamera failed\n");
        return 1;
    }
    fprintf(stderr, "[qs_daemon] ready @ %d fps\n", target_fps);

    // stdout binary 模式（Windows 相容，Linux 無差異）
    freopen(nullptr, "wb", stdout);

    uint64_t frame_id = 0;
    while (g_running) {
        auto t0 = std::chrono::steady_clock::now();

        // 擷取原始 QS 幀
        size_t   qsSize  = 0;
        uint8_t* qsData  = getQsData(cameras[0], &qsSize);
        if (!qsData) {
            fprintf(stderr, "[qs_daemon] WARN: getQsData returned null, skip\n");
            continue;
        }

        // 轉換成 5 波段 QAB
        uint8_t* qabData = nullptr; size_t qabSize = 0;
        if (qsToQab(agCtx, qsData, qsSize, &qabData, &qabSize) != QS_ERR_SUCCESS) {
            fprintf(stderr, "[qs_daemon] WARN: qsToQab failed, skip\n");
            freeQsData(qsData);
            continue;
        }

        // 寫入 binary frame header + data
        write_u64(frame_id);
        write_i64(now_us());
        write_u64((uint64_t)qabSize);
        fwrite(qabData, 1, qabSize, stdout);
        fflush(stdout);

        ++frame_id;
        freeQsData(qsData);
        delete[] qabData;

        // 幀率控制
        auto elapsed_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
            std::chrono::steady_clock::now() - t0).count();
        if (elapsed_ms < frame_ms)
            std::this_thread::sleep_for(std::chrono::milliseconds(frame_ms - elapsed_ms));
    }

    closeQsCamera(cameras[0]);
    releaseQsCamera(cameras, camCount);
    deinitQsAgriculture(agCtx);
    freeQsData(qsbsData);
    fprintf(stderr, "[qs_daemon] stopped after %llu frames\n",
            (unsigned long long)frame_id);
    return 0;
}
```

- [ ] **Step 2: 建立 Makefile（Pi5 上調整 QS SDK 路徑）**

```makefile
# spectral_capture/capture/Makefile
# 在 Pi5 上執行：make
# QS SDK 路徑：依照實際安裝位置調整 QS_SDK_DIR

CXX      = g++
CXXFLAGS = -std=c++17 -O2 -Wall
TARGET   = qs_daemon

# ── 調整此路徑為 Pi5 上 QS SDK 實際位置 ──────────────────
QS_SDK_DIR ?= /opt/qs_sdk
QS_INC      = $(QS_SDK_DIR)/include
QS_LIB      = $(QS_SDK_DIR)/lib

CXXFLAGS += -I$(QS_INC)
LDFLAGS   = -L$(QS_LIB) -lqs_camera -lqs_agriculture -lqs_fileio -lqs_imgproc \
            -Wl,-rpath,$(QS_LIB)

$(TARGET): qs_daemon.cpp
	$(CXX) $(CXXFLAGS) $< -o $@ $(LDFLAGS)
	@echo "[OK] Built $(TARGET)"

clean:
	rm -f $(TARGET)

.PHONY: clean
```

- [ ] **Step 3: 在 Pi5 上編譯並測試**

```bash
# 在 Pi5 上執行
cd ~/KyleClaude/spectral_capture/capture
# 先確認 QS SDK 路徑
ls /opt/qs_sdk/include/qs_camera.h || ls ~/qs_sdk/include/qs_camera.h
# 調整 Makefile 的 QS_SDK_DIR，然後：
make
./qs_daemon msi.qsbs 1    # 以 1 fps 測試，接 Ctrl+C
```
Expected stderr: `[qs_daemon] ready @ 1 fps` 接著每秒一行 (frame_id 增加)
Expected stdout: binary data（不要直接看，會亂碼）

- [ ] **Step 4: commit**

```bash
git add spectral_capture/capture/
git commit -m "feat: qs_daemon C++ continuous capture at configurable fps, binary stdout protocol"
```

---

## Task 5: Python Frame Reader

**Files:**
- Create: `spectral_capture/pipeline/frame_reader.py`
- Create: `spectral_capture/tests/test_frame_reader.py`

- [ ] **Step 1: 建立 stub qs_daemon（Mac/無相機測試用）**

```python
# spectral_capture/tests/fixtures/stub_qs_daemon.py
"""
模擬 qs_daemon 的 stdout binary 輸出，用於 Mac Mini 上測試 frame_reader。
以 fake QAB 資料按 fps 速率產生幀。
"""
import sys, struct, time, os
sys.path.insert(0, str(__file__ + "/../../.."))  # 確保可 import spectral_capture

from spectral_capture.tests.fixtures.make_fake_qab import make_fake_qab
from spectral_capture.config import TARGET_FPS

FRAME_INTERVAL = 1.0 / TARGET_FPS

def main():
    # stdout 改為 binary 模式
    out = sys.stdout.buffer
    frame_id = 0
    while True:
        t0 = time.time()
        qab = make_fake_qab(n_beans=5, seed=frame_id % 10)
        ts_us = int(time.time() * 1e6)
        # Protocol: frame_id(u64) + timestamp_us(i64) + qab_size(u64) + qab_data
        header = struct.pack("<QqQ", frame_id, ts_us, len(qab))
        out.write(header)
        out.write(qab)
        out.flush()
        frame_id += 1
        elapsed = time.time() - t0
        sleep = FRAME_INTERVAL - elapsed
        if sleep > 0:
            time.sleep(sleep)

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 寫 failing test**

```python
# spectral_capture/tests/test_frame_reader.py
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from spectral_capture.pipeline.frame_reader import FrameReader, CapturedFrame

STUB = str(Path(__file__).parent / "fixtures" / "stub_qs_daemon.py")

def test_frame_reader_produces_frames():
    reader = FrameReader(daemon_cmd=["python3", STUB])
    reader.start()
    time.sleep(0.5)         # 等 ~6 幀（13 fps × 0.5s）
    frame = reader.get_frame(timeout=1.0)
    reader.stop()

    assert frame is not None
    assert isinstance(frame, CapturedFrame)
    assert frame.frame_id >= 0
    assert frame.timestamp_us > 0

def test_frame_reader_cube_shape():
    reader = FrameReader(daemon_cmd=["python3", STUB])
    reader.start()
    frame = reader.get_frame(timeout=2.0)
    reader.stop()

    assert frame.cube.shape == (1200, 1600, 5)
    assert frame.cube.dtype.__str__() == "float32"

def test_frame_reader_stop_is_clean():
    reader = FrameReader(daemon_cmd=["python3", STUB])
    reader.start()
    reader.get_frame(timeout=2.0)
    reader.stop()
    # 停止後不應 hang 或 raise
    assert not reader._thread.is_alive()
```

- [ ] **Step 3: 確認 test fail**

```bash
python3 -m pytest spectral_capture/tests/test_frame_reader.py -v
```
Expected: `ImportError: cannot import name 'FrameReader'`

- [ ] **Step 4: 實作 frame_reader.py**

```python
# spectral_capture/pipeline/frame_reader.py
"""
啟動 qs_daemon 子程序，讀取 binary stdout 幀流，
解析成 CapturedFrame 放入 queue。
使用 segment_beans_sam 的 seg_daemon 相同子程序模式。
"""
import struct
import threading
import queue
import subprocess
import sys
from dataclasses import dataclass
import numpy as np

from spectral_capture.pipeline.qab_parser import parse_qab, QABFormatError
from spectral_capture.config import QS_DAEMON_BIN, QSBS_PATH, TARGET_FPS

HEADER_FMT  = "<QqQ"   # frame_id(u64) + timestamp_us(i64) + qab_size(u64)
HEADER_SIZE = struct.calcsize(HEADER_FMT)
MAX_QUEUE   = 4  # 超過則丟棄最舊幀（避免記憶體爆炸）


@dataclass
class CapturedFrame:
    frame_id:     int
    timestamp_us: int
    cube:         np.ndarray  # (H, W, 5) float32


class FrameReader:
    """
    啟動 qs_daemon 子程序，持續讀取幀，通過 get_frame() 取得最新幀。
    """

    def __init__(self, daemon_cmd: list[str] | None = None):
        if daemon_cmd is None:
            daemon_cmd = [str(QS_DAEMON_BIN), str(QSBS_PATH), str(TARGET_FPS)]
        self._cmd    = daemon_cmd
        self._queue  = queue.Queue(maxsize=MAX_QUEUE)
        self._proc   = None
        self._thread = None
        self._stop_evt = threading.Event()

    def start(self):
        self._proc = subprocess.Popen(
            self._cmd,
            stdout=subprocess.PIPE,
            stderr=sys.stderr,   # daemon 的 stderr 直接顯示到終端
            bufsize=0,
        )
        self._thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._thread.start()

    def get_frame(self, timeout: float = 1.0) -> CapturedFrame | None:
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def stop(self):
        self._stop_evt.set()
        if self._proc:
            self._proc.terminate()
            self._proc.wait(timeout=3)
        if self._thread:
            self._thread.join(timeout=3)

    def _reader_loop(self):
        buf = self._proc.stdout
        while not self._stop_evt.is_set():
            # 讀 header
            header_bytes = self._read_exact(buf, HEADER_SIZE)
            if not header_bytes:
                break
            frame_id, ts_us, qab_size = struct.unpack(HEADER_FMT, header_bytes)

            # 讀 QAB data
            qab_bytes = self._read_exact(buf, qab_size)
            if not qab_bytes:
                break

            try:
                cube = parse_qab(bytes(qab_bytes))
            except QABFormatError as e:
                print(f"[FrameReader] parse error frame {frame_id}: {e}", file=sys.stderr)
                continue

            frame = CapturedFrame(
                frame_id=frame_id,
                timestamp_us=ts_us,
                cube=cube,
            )
            # 非阻塞放入：若 queue 滿，丟棄最舊的
            if self._queue.full():
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    pass
            self._queue.put_nowait(frame)

    @staticmethod
    def _read_exact(stream, n: int) -> bytes | None:
        """從 stream 精確讀取 n bytes，EOF 時回傳 None"""
        data = b""
        while len(data) < n:
            chunk = stream.read(n - len(data))
            if not chunk:
                return None
            data += chunk
        return data
```

- [ ] **Step 5: 確認 test pass**

```bash
python3 -m pytest spectral_capture/tests/test_frame_reader.py -v
```
Expected: 3 tests PASSED

- [ ] **Step 6: commit**

```bash
git add spectral_capture/pipeline/frame_reader.py \
        spectral_capture/tests/test_frame_reader.py \
        spectral_capture/tests/fixtures/stub_qs_daemon.py
git commit -m "feat: FrameReader subprocess driver + stub daemon for testing"
```

---

## Task 6: Collector (SQLite) + Main Orchestrator

**Files:**
- Create: `spectral_capture/storage/collector.py`
- Create: `spectral_capture/main.py`

- [ ] **Step 1: 建立 SQLite schema + collector**

```python
# spectral_capture/storage/collector.py
"""
寫入 SQLite 作為 Siamese 訓練資料集。
Schema 對應 docs/superpowers/plans/2026-06-01-siamese-bean-defect.md Phase 1。
"""
import sqlite3
import time
import numpy as np
from pathlib import Path
from spectral_capture.config import DB_PATH, ORIGIN, ROAST_LEVEL, BAND_NM

CREATE_SQL = """
CREATE TABLE IF NOT EXISTS bean_spectra (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    captured_at REAL    NOT NULL,   -- Unix timestamp
    frame_id    INTEGER NOT NULL,
    bean_cx     INTEGER NOT NULL,   -- 像素，用於判斷皮帶位置
    bean_cy     INTEGER NOT NULL,
    area_px     INTEGER NOT NULL,
    b450        REAL NOT NULL,
    b560        REAL NOT NULL,
    b650        REAL NOT NULL,
    b730        REAL NOT NULL,
    b840        REAL NOT NULL,
    origin      TEXT DEFAULT '',
    roast_level TEXT DEFAULT 'green',
    label       TEXT DEFAULT 'unknown'   -- 後期人工標註
);
CREATE INDEX IF NOT EXISTS idx_captured_at ON bean_spectra(captured_at);
"""


class Collector:
    def __init__(self, db_path: Path = DB_PATH):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.executescript(CREATE_SQL)
        self._conn.commit()

    def insert_bean(self, frame_id: int, timestamp_us: int,
                    cx: int, cy: int, area_px: int,
                    spec_vec: np.ndarray) -> int:
        """
        插入一顆豆的光譜記錄，回傳 row id。
        spec_vec: (5,) float32，對應 [450, 560, 650, 730, 840] nm
        """
        row = (
            timestamp_us / 1e6,   # Unix timestamp
            frame_id, cx, cy, area_px,
            float(spec_vec[0]), float(spec_vec[1]), float(spec_vec[2]),
            float(spec_vec[3]), float(spec_vec[4]),
            ORIGIN, ROAST_LEVEL,
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
```

- [ ] **Step 2: 建立 main.py**

```python
# spectral_capture/main.py
"""
Pi5 多光譜擷取 Pipeline 主程式。
執行：python3 -m spectral_capture.main [--origin Ethiopia] [--fps 13] [--stub]

執行緒架構：
  FrameReader (T1) → detect loop (main thread) → Collector (T3)

使用 --stub 在沒有相機的情況下以合成資料測試整個 pipeline。
"""
import argparse
import signal
import sys
import time
from pathlib import Path

from spectral_capture.pipeline.frame_reader import FrameReader
from spectral_capture.pipeline.bean_detector import detect_beans
from spectral_capture.storage.collector import Collector
import spectral_capture.config as cfg


def build_args():
    p = argparse.ArgumentParser()
    p.add_argument("--origin",    default=cfg.ORIGIN,      help="豆子產地標記")
    p.add_argument("--roast",     default=cfg.ROAST_LEVEL, help="烘焙程度")
    p.add_argument("--fps",       type=int, default=cfg.TARGET_FPS)
    p.add_argument("--stub",      action="store_true",     help="使用合成資料（無相機測試）")
    p.add_argument("--db",        default=str(cfg.DB_PATH))
    return p.parse_args()


def main():
    args = build_args()
    cfg.ORIGIN      = args.origin
    cfg.ROAST_LEVEL = args.roast

    # 決定使用真實 daemon 或 stub
    if args.stub:
        stub_path = Path(__file__).parent / "tests/fixtures/stub_qs_daemon.py"
        daemon_cmd = [sys.executable, str(stub_path)]
        print("[main] stub mode — using synthetic QAB data")
    else:
        daemon_cmd = None  # 使用 config.QS_DAEMON_BIN

    reader    = FrameReader(daemon_cmd=daemon_cmd)
    collector = Collector(db_path=Path(args.db))

    # Graceful stop on Ctrl+C
    stop = False
    def _sig(s, f): nonlocal stop; stop = True
    signal.signal(signal.SIGINT,  _sig)
    signal.signal(signal.SIGTERM, _sig)

    reader.start()
    print(f"[main] capturing @ {args.fps} fps  origin={args.origin}  db={args.db}")
    print("[main] Ctrl+C to stop\n")

    total_frames = 0
    total_beans  = 0
    t_report     = time.time()

    while not stop:
        frame = reader.get_frame(timeout=0.5)
        if frame is None:
            continue

        beans = detect_beans(frame.cube)
        for b in beans:
            collector.insert_bean(
                frame_id=frame.frame_id,
                timestamp_us=frame.timestamp_us,
                cx=b.cx, cy=b.cy, area_px=b.area_px,
                spec_vec=b.spec_vec,
            )

        total_frames += 1
        total_beans  += len(beans)

        # 每 30 幀列印一次統計
        if total_frames % 30 == 0:
            elapsed = time.time() - t_report
            fps_actual = 30 / elapsed
            print(f"  frame={frame.frame_id:6d}  fps={fps_actual:.1f}  "
                  f"beans_this_frame={len(beans)}  total_beans={total_beans}")
            t_report = time.time()

    reader.stop()
    stats = collector.stats()
    collector.close()
    print(f"\n[main] done. {total_frames} frames, {total_beans} bean records.")
    print(f"[main] DB stats: {stats}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: 建立 data/ 目錄 + .gitkeep**

```bash
mkdir -p ~/KyleClaude/spectral_capture/data
touch ~/KyleClaude/spectral_capture/data/.gitkeep
echo "*.db" >> ~/KyleClaude/.gitignore
```

- [ ] **Step 4: 端到端測試（stub 模式，無需相機）**

```bash
cd ~/KyleClaude
python3 -m spectral_capture.main --stub --origin TestOrigin --db /tmp/test_beans.db
# 等 10 秒後 Ctrl+C
```
Expected output（每 30 幀一行）：
```
[main] stub mode — using synthetic QAB data
[main] capturing @ 13 fps  origin=TestOrigin  db=/tmp/test_beans.db
[main] Ctrl+C to stop

  frame=    30  fps=12.8  beans_this_frame=5  total_beans=150
  frame=    60  fps=13.1  beans_this_frame=4  total_beans=295
  ...
[main] done. 130 frames, 652 bean records.
[main] DB stats: {'total': 652, 't_min': ..., 't_max': ...}
```

- [ ] **Step 5: 確認 SQLite 資料正確**

```bash
sqlite3 /tmp/test_beans.db "
  SELECT COUNT(*), ROUND(AVG(b840),3), ROUND(AVG(b450),3)
  FROM bean_spectra;
"
```
Expected: `652|0.35x|0.08x`（NIR b840 >> b450，符合咖啡豆光譜）

- [ ] **Step 6: 最終 commit**

```bash
cd ~/KyleClaude
git add spectral_capture/storage/collector.py spectral_capture/main.py \
        spectral_capture/data/.gitkeep .gitignore
git commit -m "feat: complete spectral capture pipeline — 13fps capture, bean detection, SQLite collection"
```

---

## 驗收標準

| 測試 | 方式 | Pass 條件 |
|------|------|-----------|
| Parser | `pytest test_qab_parser.py` | 4/4 pass |
| Detector | `pytest test_bean_detector.py` | 4/4 pass |
| FrameReader | `pytest test_frame_reader.py` | 3/3 pass |
| 端到端 stub | `main.py --stub` 10 秒 | fps ≥ 12.5，DB 有紀錄 |
| 端到端 Pi5 | `main.py` (有相機) 10 秒 | fps ≥ 12.5，DB 有紀錄 |

## 接下來（本計畫範圍外）

1. **QAB 格式確認**：Pi5 上執行 `qs_daemon` 後，用 `struct.unpack` 探測 qabSize，確認是否為 `H×W×5×2 bytes`。若格式不符，只需修改 `qab_parser.py` 的 `BYTES_PER_PIXEL` 和 `reshape`。
2. **Siamese MLP 訓練**（Phase 2-3）：從 `beans.db` 取出光譜向量訓練，見 `2026-06-01-siamese-bean-defect.md`。
3. **Hailo-8 推論整合**：訓練完成後，參照 `fastsam_hailo.py` 的 worker thread 模式，在 `main.py` 加入第四個執行緒。
