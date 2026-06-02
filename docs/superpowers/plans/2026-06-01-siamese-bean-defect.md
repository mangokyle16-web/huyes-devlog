# Siamese 多光譜豆子瑕疵偵測系統 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立一套以 Siamese MLP 為核心的少樣本咖啡豆瑕疵偵測系統，從輸送帶採集、特徵提取、模型訓練到即時推理一條龍。

**Architecture:** RPi5 透過現有互動式多光譜系統採集單豆 spec_raw.csv；Python 工具提取 10-band 光譜向量並建立標記資料集；Siamese MLP（10→128 embedding + Euclidean 距離分類）在 Mac Mini 上訓練（支援 MPS 加速）；推理時比對參考向量集，輸出相似度分數。

**Tech Stack:** Python 3.11, PyTorch 2.x (MPS), NumPy, scikit-learn（評估用）, RPi.GPIO（Phase 4）

**參考論文:** Hu et al. 2025, LWT 235, 118631 — Siamese networks for few-shot coffee bean defect detection

---

## 資料夾結構

```
siamese_bean/
├── collect/
│   └── session_watcher.py      # 監控 Desktop，自動搬移並標記新採集
├── data/
│   ├── extract.py              # spec_raw.csv → per-class feature CSV
│   ├── normalize.py            # 計算並儲存 z-score 統計
│   ├── pairs.py                # feature CSV → train/val/test pair CSV
│   └── dataset.py              # PyTorch BeanPairDataset
├── model/
│   ├── net.py                  # SiameseMLP 架構
│   └── train.py                # 訓練入口（MPS-aware）
├── inference/
│   └── predict.py              # 載入模型 + 參考集，分類單顆豆子
└── tests/
    ├── test_extract.py
    ├── test_pairs.py
    ├── test_net.py
    └── test_predict.py

data/
├── raw/                        # 採集原始 session 目錄
│   ├── normal/
│   │   ├── bean001_pass01/     # 含 spec_raw.csv
│   │   └── ...
│   └── mold/
│       └── ...
├── features/
│   ├── normal.csv              # bean_id, pass_id, band_0..band_9
│   └── mold.csv
├── pairs/
│   ├── train_pairs.csv
│   ├── val_pairs.csv
│   └── test_pairs.csv
└── stats.json                  # 訓練集 mean/std per band
```

**重要設計決策：**
- **Train/val/test 以 bean_id 切割**（非以檔案），避免同一顆豆子的 10 次 pass 同時出現在 train 和 test 造成 data leakage
- bean_id 1-40 → train，41-45 → val，46-50 → test（各 400/50/50 樣本/類）
- 採集階段沿用現有互動式多光譜系統（不修改 C++），Python 只負責搬移與標記

---

## Phase 1 — 資料採集流程

### Task 1: 採集 Session 監控器

**說明：** 採集時在 RPi5 上啟動此腳本，指定當前豆子的 class 和 bean_id。腳本監控 Desktop，每當多光譜系統存下一個新 session 目錄，自動搬到 `data/raw/{class}/bean{id}_pass{N}/`。

**Files:**
- Create: `siamese_bean/collect/session_watcher.py`
- Test: `siamese_bean/tests/test_session_watcher.py`

- [ ] **Step 1: 建立目錄結構**

  ```bash
  mkdir -p /home/kyle/KyleClaude/siamese_bean/collect
  mkdir -p /home/kyle/KyleClaude/siamese_bean/tests
  mkdir -p /home/kyle/KyleClaude/siamese_bean/data
  mkdir -p /home/kyle/KyleClaude/siamese_bean/model
  mkdir -p /home/kyle/KyleClaude/siamese_bean/inference
  mkdir -p /home/kyle/KyleClaude/data/raw
  mkdir -p /home/kyle/KyleClaude/data/features
  mkdir -p /home/kyle/KyleClaude/data/pairs
  touch /home/kyle/KyleClaude/siamese_bean/__init__.py
  touch /home/kyle/KyleClaude/siamese_bean/collect/__init__.py
  touch /home/kyle/KyleClaude/siamese_bean/data/__init__.py
  touch /home/kyle/KyleClaude/siamese_bean/model/__init__.py
  touch /home/kyle/KyleClaude/siamese_bean/inference/__init__.py
  ```

- [ ] **Step 2: 撰寫 session_watcher.py**

  ```python
  # siamese_bean/collect/session_watcher.py
  """
  用法：
    python3 session_watcher.py --class normal --bean 1
  效果：監控 ~/Desktop，每出現新的 GigaImage_* 目錄就搬到
        data/raw/normal/bean001_pass01/ (自動遞增 pass)
  按 Ctrl+C 結束。
  """
  import argparse
  import shutil
  import time
  from pathlib import Path

  DESKTOP = Path.home() / "Desktop"
  DATA_RAW = Path(__file__).parents[2] / "data" / "raw"

  def next_pass(class_name: str, bean_id: int) -> int:
      base = DATA_RAW / class_name
      existing = list(base.glob(f"bean{bean_id:03d}_pass*"))
      return len(existing) + 1

  def find_new_sessions(known: set) -> list:
      current = {p for p in DESKTOP.iterdir()
                 if p.is_dir() and p.name.startswith("GigaImage_")}
      return sorted(current - known)

  def run(class_name: str, bean_id: int):
      dest_base = DATA_RAW / class_name
      dest_base.mkdir(parents=True, exist_ok=True)

      known = {p for p in DESKTOP.iterdir()
               if p.is_dir() and p.name.startswith("GigaImage_")}
      print(f"[watcher] class={class_name} bean={bean_id:03d}")
      print(f"[watcher] Monitoring {DESKTOP} ... Press Ctrl+C to stop.")

      try:
          while True:
              new = find_new_sessions(known)
              for session_dir in new:
                  # 確認 spec_raw.csv 存在（採集完成）
                  spec = session_dir / "spec_raw.csv"
                  if not spec.exists():
                      time.sleep(1)
                      if not spec.exists():
                          print(f"[watcher] SKIP {session_dir.name} (no spec_raw.csv)")
                          known.add(session_dir)
                          continue

                  pass_id = next_pass(class_name, bean_id)
                  dest = dest_base / f"bean{bean_id:03d}_pass{pass_id:02d}"
                  shutil.copytree(str(session_dir), str(dest))
                  known.add(session_dir)
                  print(f"[watcher] SAVED → {dest.relative_to(Path.home())}")
              time.sleep(0.5)
      except KeyboardInterrupt:
          total = next_pass(class_name, bean_id) - 1
          print(f"\n[watcher] Done. {total} passes saved for bean {bean_id:03d}.")

  if __name__ == "__main__":
      parser = argparse.ArgumentParser()
      parser.add_argument("--class", dest="class_name", required=True)
      parser.add_argument("--bean", type=int, required=True)
      args = parser.parse_args()
      run(args.class_name, args.bean)
  ```

- [ ] **Step 3: 撰寫測試**

  ```python
  # siamese_bean/tests/test_session_watcher.py
  import shutil, tempfile
  from pathlib import Path
  from unittest.mock import patch

  def test_next_pass_empty(tmp_path):
      with patch("siamese_bean.collect.session_watcher.DATA_RAW", tmp_path):
          from siamese_bean.collect.session_watcher import next_pass
          (tmp_path / "normal").mkdir()
          assert next_pass("normal", 1) == 1

  def test_next_pass_existing(tmp_path):
      with patch("siamese_bean.collect.session_watcher.DATA_RAW", tmp_path):
          from siamese_bean.collect.session_watcher import next_pass
          base = tmp_path / "normal"
          (base / "bean001_pass01").mkdir(parents=True)
          (base / "bean001_pass02").mkdir()
          assert next_pass("normal", 1) == 3
  ```

- [ ] **Step 4: 執行測試**

  ```bash
  cd /home/kyle/KyleClaude
  python3 -m pytest siamese_bean/tests/test_session_watcher.py -v
  ```
  預期：2 PASSED

- [ ] **Step 5: Commit**

  ```bash
  git add siamese_bean/ data/
  git commit -m "feat: add conveyor session watcher for labeled data collection"
  ```

---

## Phase 2 — 特徵提取與資料集建立

### Task 2: 光譜向量提取器

**說明：** 讀取 `data/raw/{class}/bean{id}_pass{N}/spec_raw.csv`，提取 `bean_1` 欄位（單豆採集固定是 bean_1），輸出 per-class 的 feature CSV。

**Files:**
- Create: `siamese_bean/data/extract.py`
- Test: `siamese_bean/tests/test_extract.py`

- [ ] **Step 1: 撰寫測試**

  ```python
  # siamese_bean/tests/test_extract.py
  import csv, tempfile
  from pathlib import Path
  from siamese_bean.data.extract import load_spec_raw, extract_class_features

  def make_spec_csv(path: Path, n_bands=10):
      """Helper: 建立假的 spec_raw.csv"""
      path.parent.mkdir(parents=True, exist_ok=True)
      wavelengths = [700 + i * 30 for i in range(n_bands)]
      with open(path, "w", newline="") as f:
          w = csv.DictWriter(f, fieldnames=["wavelength_nm", "bean_1"])
          w.writeheader()
          for i, wl in enumerate(wavelengths):
              w.writerow({"wavelength_nm": wl, "bean_1": float(i) * 0.1})

  def test_load_spec_raw(tmp_path):
      spec = tmp_path / "spec_raw.csv"
      make_spec_csv(spec)
      vec = load_spec_raw(str(spec))
      assert vec.shape == (10,)
      assert abs(vec[0] - 0.0) < 1e-6
      assert abs(vec[9] - 0.9) < 1e-6

  def test_extract_class_features(tmp_path):
      raw_dir = tmp_path / "normal"
      for bean_id in range(1, 4):
          for pass_id in range(1, 3):
              spec = raw_dir / f"bean{bean_id:03d}_pass{pass_id:02d}" / "spec_raw.csv"
              make_spec_csv(spec)

      out_csv = tmp_path / "features" / "normal.csv"
      extract_class_features(str(raw_dir), str(out_csv))

      with open(out_csv) as f:
          rows = list(csv.DictReader(f))
      assert len(rows) == 6  # 3 beans × 2 passes
      assert rows[0]["bean_id"] == "1"
      assert "band_0" in rows[0]
      assert "band_9" in rows[0]
  ```

- [ ] **Step 2: 執行測試確認失敗**

  ```bash
  python3 -m pytest siamese_bean/tests/test_extract.py -v
  ```
  預期：ImportError（模組還不存在）

- [ ] **Step 3: 撰寫 extract.py**

  ```python
  # siamese_bean/data/extract.py
  import csv
  from pathlib import Path
  import numpy as np

  def load_spec_raw(spec_csv_path: str) -> np.ndarray:
      """
      讀取單豆採集的 spec_raw.csv，回傳 shape=(n_bands,) 的光譜向量。
      固定讀 bean_1 欄（輸送帶單豆採集）。
      """
      with open(spec_csv_path) as f:
          reader = csv.DictReader(f)
          rows = list(reader)
      return np.array([float(row["bean_1"]) for row in rows])

  def extract_class_features(raw_class_dir: str, output_csv: str):
      """
      掃描 raw_class_dir 下所有 bean{id}_pass{N}/ 目錄，
      提取光譜向量並寫入 output_csv。

      output_csv 格式：bean_id, pass_id, band_0, band_1, ..., band_N
      """
      raw_dir = Path(raw_class_dir)
      sessions = sorted(raw_dir.glob("bean*_pass*"))

      if not sessions:
          raise FileNotFoundError(f"No sessions found in {raw_class_dir}")

      rows = []
      for session in sessions:
          spec_path = session / "spec_raw.csv"
          if not spec_path.exists():
              continue
          parts = session.name.split("_")
          bean_id = int(parts[0].replace("bean", ""))
          pass_id = int(parts[1].replace("pass", ""))
          vec = load_spec_raw(str(spec_path))
          rows.append({
              "bean_id": bean_id,
              "pass_id": pass_id,
              **{f"band_{i}": float(v) for i, v in enumerate(vec)},
          })

      if not rows:
          raise ValueError(f"No valid spec_raw.csv found in {raw_class_dir}")

      n_bands = sum(1 for k in rows[0] if k.startswith("band_"))
      fieldnames = ["bean_id", "pass_id"] + [f"band_{i}" for i in range(n_bands)]

      Path(output_csv).parent.mkdir(parents=True, exist_ok=True)
      with open(output_csv, "w", newline="") as f:
          writer = csv.DictWriter(f, fieldnames=fieldnames)
          writer.writeheader()
          writer.writerows(rows)

      print(f"[extract] {len(rows)} samples → {output_csv}")

  if __name__ == "__main__":
      import argparse, os
      parser = argparse.ArgumentParser()
      parser.add_argument("--raw-dir", required=True, help="data/raw/{class}/")
      parser.add_argument("--out", required=True, help="data/features/{class}.csv")
      args = parser.parse_args()
      extract_class_features(args.raw_dir, args.out)
  ```

- [ ] **Step 4: 執行測試確認通過**

  ```bash
  python3 -m pytest siamese_bean/tests/test_extract.py -v
  ```
  預期：2 PASSED

- [ ] **Step 5: Commit**

  ```bash
  git add siamese_bean/data/extract.py siamese_bean/tests/test_extract.py
  git commit -m "feat: add spectral vector extractor for single-bean captures"
  ```

---

### Task 3: 標準化統計計算

**說明：** 從訓練集計算每個 band 的 mean/std，儲存為 `data/stats.json`。推理時使用相同統計做 z-score。

**Files:**
- Create: `siamese_bean/data/normalize.py`
- Test: `siamese_bean/tests/test_normalize.py`

- [ ] **Step 1: 撰寫測試**

  ```python
  # siamese_bean/tests/test_normalize.py
  import csv, json
  import numpy as np
  from siamese_bean.data.normalize import compute_stats, apply_stats

  def make_feature_csv(path, n_samples=20, n_bands=10, seed=0):
      rng = np.random.default_rng(seed)
      path.parent.mkdir(parents=True, exist_ok=True)
      rows = []
      for i in range(n_samples):
          row = {"bean_id": i // 10 + 1, "pass_id": i % 10 + 1}
          row.update({f"band_{b}": float(rng.uniform(0.1, 0.9)) for b in range(n_bands)})
          rows.append(row)
      fieldnames = ["bean_id", "pass_id"] + [f"band_{b}" for b in range(n_bands)]
      with open(path, "w", newline="") as f:
          w = csv.DictWriter(f, fieldnames=fieldnames)
          w.writeheader()
          w.writerows(rows)

  def test_compute_stats_shape(tmp_path):
      csv1 = tmp_path / "normal.csv"
      csv2 = tmp_path / "mold.csv"
      make_feature_csv(csv1)
      make_feature_csv(csv2, seed=1)
      stats = compute_stats([str(csv1), str(csv2)], train_bean_max=40)
      assert "mean" in stats and "std" in stats
      assert len(stats["mean"]) == 10
      assert len(stats["std"]) == 10

  def test_apply_stats_zero_mean(tmp_path):
      csv1 = tmp_path / "normal.csv"
      make_feature_csv(csv1, n_samples=100)
      stats = compute_stats([str(csv1)], train_bean_max=40)
      vec = np.array([stats["mean"][i] for i in range(10)])
      normalized = apply_stats(vec, stats)
      assert np.allclose(normalized, 0.0, atol=1e-5)
  ```

- [ ] **Step 2: 撰寫 normalize.py**

  ```python
  # siamese_bean/data/normalize.py
  import csv, json
  import numpy as np
  from pathlib import Path

  def _load_train_vectors(csv_paths: list, train_bean_max: int) -> np.ndarray:
      """只載入 bean_id <= train_bean_max 的樣本（訓練集）。"""
      all_vecs = []
      for path in csv_paths:
          with open(path) as f:
              for row in csv.DictReader(f):
                  if int(row["bean_id"]) > train_bean_max:
                      continue
                  bands = [k for k in row if k.startswith("band_")]
                  bands.sort(key=lambda x: int(x.split("_")[1]))
                  all_vecs.append([float(row[b]) for b in bands])
      return np.array(all_vecs)  # shape: (N, n_bands)

  def compute_stats(csv_paths: list, train_bean_max: int = 40) -> dict:
      """
      計算訓練集的 per-band mean 和 std。
      csv_paths: feature CSV 路徑列表（所有 class）
      train_bean_max: bean_id <= 此值視為訓練集
      """
      vecs = _load_train_vectors(csv_paths, train_bean_max)
      mean = vecs.mean(axis=0).tolist()
      std  = vecs.std(axis=0).tolist()
      # 避免除以零
      std = [max(s, 1e-8) for s in std]
      return {"mean": mean, "std": std}

  def apply_stats(vec: np.ndarray, stats: dict) -> np.ndarray:
      """Z-score 標準化。"""
      mean = np.array(stats["mean"])
      std  = np.array(stats["std"])
      return (vec - mean) / std

  def save_stats(stats: dict, path: str):
      with open(path, "w") as f:
          json.dump(stats, f, indent=2)
      print(f"[normalize] stats saved → {path}")

  def load_stats(path: str) -> dict:
      with open(path) as f:
          return json.load(f)
  ```

- [ ] **Step 3: 執行測試**

  ```bash
  python3 -m pytest siamese_bean/tests/test_normalize.py -v
  ```
  預期：2 PASSED

- [ ] **Step 4: Commit**

  ```bash
  git add siamese_bean/data/normalize.py siamese_bean/tests/test_normalize.py
  git commit -m "feat: add z-score normalization stats (per-band, train-only)"
  ```

---

### Task 4: 配對資料集生成器

**說明：** 把 per-class feature CSV 組合成 Siamese 訓練所需的 pair CSV（正樣本=同類、負樣本=不同類，1:1 平衡）。以 bean_id 切 train/val/test，避免 data leakage。

**Files:**
- Create: `siamese_bean/data/pairs.py`
- Test: `siamese_bean/tests/test_pairs.py`

- [ ] **Step 1: 撰寫測試**

  ```python
  # siamese_bean/tests/test_pairs.py
  import csv
  from pathlib import Path
  import numpy as np
  from siamese_bean.data.pairs import build_pairs

  def make_feature_csv(path, class_name, n_beans=50, n_passes=10, n_bands=10):
      path.parent.mkdir(parents=True, exist_ok=True)
      rows = []
      rng = np.random.default_rng(hash(class_name) % 2**32)
      for bean_id in range(1, n_beans + 1):
          for pass_id in range(1, n_passes + 1):
              row = {"bean_id": bean_id, "pass_id": pass_id}
              row.update({f"band_{b}": float(rng.uniform(0, 1)) for b in range(n_bands)})
              rows.append(row)
      fieldnames = ["bean_id", "pass_id"] + [f"band_{b}" for b in range(n_bands)]
      with open(path, "w", newline="") as f:
          w = csv.DictWriter(f, fieldnames=fieldnames)
          w.writeheader()
          w.writerows(rows)

  def test_build_pairs_balance(tmp_path):
      make_feature_csv(tmp_path / "normal.csv", "normal")
      make_feature_csv(tmp_path / "mold.csv", "mold")
      out = tmp_path / "pairs"
      build_pairs(str(tmp_path), str(out), n_train=1000, seed=42)

      with open(out / "train_pairs.csv") as f:
          rows = list(csv.DictReader(f))
      labels = [int(r["label"]) for r in rows]
      pos = sum(labels)
      neg = len(labels) - pos
      # 正負比例在 40/60 到 60/40 之間
      assert 0.4 <= pos / len(labels) <= 0.6

  def test_build_pairs_no_leakage(tmp_path):
      make_feature_csv(tmp_path / "normal.csv", "normal")
      make_feature_csv(tmp_path / "mold.csv", "mold")
      out = tmp_path / "pairs"
      build_pairs(str(tmp_path), str(out), n_train=500, seed=42)

      with open(out / "test_pairs.csv") as f:
          rows = list(csv.DictReader(f))
      # test 集 bean_id 必須 > 45（train_bean_max=40, val 41-45, test 46-50）
      for r in rows:
          assert int(r["bean_a_id"]) > 45
          assert int(r["bean_b_id"]) > 45

  def test_build_pairs_columns(tmp_path):
      make_feature_csv(tmp_path / "normal.csv", "normal")
      make_feature_csv(tmp_path / "mold.csv", "mold")
      out = tmp_path / "pairs"
      build_pairs(str(tmp_path), str(out), n_train=200, seed=0)
      with open(out / "train_pairs.csv") as f:
          reader = csv.DictReader(f)
          row = next(reader)
      assert "label" in row
      assert "a_band_0" in row and "b_band_9" in row
  ```

- [ ] **Step 2: 執行測試確認失敗**

  ```bash
  python3 -m pytest siamese_bean/tests/test_pairs.py -v
  ```
  預期：ImportError

- [ ] **Step 3: 撰寫 pairs.py**

  ```python
  # siamese_bean/data/pairs.py
  import csv
  import random
  from pathlib import Path

  TRAIN_BEAN_MAX = 40   # bean_id 1-40 → train
  VAL_BEAN_MAX   = 45   # bean_id 41-45 → val
  # bean_id 46-50 → test

  def _load_csv(path: str) -> list:
      with open(path) as f:
          return list(csv.DictReader(f))

  def _split(rows: list) -> tuple:
      train = [r for r in rows if int(r["bean_id"]) <= TRAIN_BEAN_MAX]
      val   = [r for r in rows if TRAIN_BEAN_MAX < int(r["bean_id"]) <= VAL_BEAN_MAX]
      test  = [r for r in rows if int(r["bean_id"]) > VAL_BEAN_MAX]
      return train, val, test

  def _make_pairs(pos_rows: list, neg_rows: list, n: int, rng: random.Random) -> list:
      """生成 n 個配對（正負各半），回傳 list of (row_a, row_b, label)。"""
      half = n // 2
      pairs = []
      for _ in range(half):
          a, b = rng.sample(pos_rows, 2) if len(pos_rows) >= 2 else (pos_rows[0], pos_rows[0])
          pairs.append((a, b, 1))
      for _ in range(half):
          a = rng.choice(pos_rows)
          b = rng.choice(neg_rows)
          pairs.append((a, b, 0))
      rng.shuffle(pairs)
      return pairs

  def build_pairs(features_dir: str, output_dir: str, n_train: int = 10000, seed: int = 42):
      """
      讀取 features_dir 下所有 *.csv（每個檔案一個類別），
      生成 train/val/test pair CSV 到 output_dir。
      """
      rng = random.Random(seed)
      Path(output_dir).mkdir(parents=True, exist_ok=True)

      class_data = {}
      for csv_path in sorted(Path(features_dir).glob("*.csv")):
          class_data[csv_path.stem] = _load_csv(str(csv_path))

      if len(class_data) < 2:
          raise ValueError("需要至少 2 個類別才能生成配對")

      classes = list(class_data.keys())
      # 取第一個樣本確認 band 數量
      sample_row = class_data[classes[0]][0]
      n_bands = sum(1 for k in sample_row if k.startswith("band_"))

      fieldnames = (
          ["label", "class_a", "bean_a_id", "pass_a_id",
           "class_b", "bean_b_id", "pass_b_id"] +
          [f"a_band_{i}" for i in range(n_bands)] +
          [f"b_band_{i}" for i in range(n_bands)]
      )

      splits_data = {}
      for cls, rows in class_data.items():
          tr, va, te = _split(rows)
          splits_data[cls] = {"train": tr, "val": va, "test": te}

      pair_counts = {"train": n_train, "val": n_train // 5, "test": n_train // 5}

      for split_name, n_pairs in pair_counts.items():
          all_pairs = []
          n_combos = len(classes) * (len(classes) - 1) // 2
          per_combo = max(n_pairs // n_combos, 10)

          for i, cls_a in enumerate(classes):
              for cls_b in classes[i + 1:]:
                  neg_a = splits_data[cls_a][split_name]
                  neg_b = splits_data[cls_b][split_name]
                  if not neg_a or not neg_b:
                      continue
                  all_pairs.extend(_make_pairs(neg_a, neg_b, per_combo, rng))

          rng.shuffle(all_pairs)
          out_path = Path(output_dir) / f"{split_name}_pairs.csv"

          with open(out_path, "w", newline="") as f:
              writer = csv.DictWriter(f, fieldnames=fieldnames)
              writer.writeheader()
              for row_a, row_b, label in all_pairs:
                  record = {
                      "label":      label,
                      "class_a":    [c for c, d in class_data.items() if row_a in d][0]
                                    if row_a in sum(class_data.values(), []) else "",
                      "bean_a_id":  row_a["bean_id"],
                      "pass_a_id":  row_a["pass_id"],
                      "class_b":    [c for c, d in class_data.items() if row_b in d][0]
                                    if row_b in sum(class_data.values(), []) else "",
                      "bean_b_id":  row_b["bean_id"],
                      "pass_b_id":  row_b["pass_id"],
                  }
                  for i in range(n_bands):
                      record[f"a_band_{i}"] = row_a[f"band_{i}"]
                      record[f"b_band_{i}"] = row_b[f"band_{i}"]
                  writer.writerow(record)

          print(f"[pairs] {split_name}: {len(all_pairs)} pairs → {out_path}")
  ```

- [ ] **Step 4: 執行測試**

  ```bash
  python3 -m pytest siamese_bean/tests/test_pairs.py -v
  ```
  預期：3 PASSED

- [ ] **Step 5: Commit**

  ```bash
  git add siamese_bean/data/pairs.py siamese_bean/tests/test_pairs.py
  git commit -m "feat: add pair generator with bean-level train/val/test split"
  ```

---

### Task 5: PyTorch Dataset

**Files:**
- Create: `siamese_bean/data/dataset.py`

- [ ] **Step 1: 撰寫 dataset.py**

  ```python
  # siamese_bean/data/dataset.py
  import csv
  import numpy as np
  import torch
  from torch.utils.data import Dataset
  from siamese_bean.data.normalize import load_stats, apply_stats

  class BeanPairDataset(Dataset):
      def __init__(self, pairs_csv: str, stats_path: str):
          self.stats = load_stats(stats_path)
          with open(pairs_csv) as f:
              self.rows = list(csv.DictReader(f))
          # 確認 band 數量
          self.n_bands = sum(1 for k in self.rows[0] if k.startswith("a_band_"))

      def __len__(self):
          return len(self.rows)

      def __getitem__(self, idx):
          row = self.rows[idx]
          vec_a = np.array([float(row[f"a_band_{i}"]) for i in range(self.n_bands)])
          vec_b = np.array([float(row[f"b_band_{i}"]) for i in range(self.n_bands)])
          vec_a = apply_stats(vec_a, self.stats)
          vec_b = apply_stats(vec_b, self.stats)
          label = float(row["label"])
          return (
              torch.tensor(vec_a, dtype=torch.float32),
              torch.tensor(vec_b, dtype=torch.float32),
              torch.tensor(label, dtype=torch.float32),
          )
  ```

- [ ] **Step 2: Commit**

  ```bash
  git add siamese_bean/data/dataset.py
  git commit -m "feat: add PyTorch BeanPairDataset with z-score normalization"
  ```

---

## Phase 3 — Siamese MLP 訓練（Mac Mini）

### Task 6: Siamese MLP 架構

**說明：** 與論文相同的 Siamese 架構，但輸入從 224×224 圖片改為 10-dim 光譜向量。
論文：ResNet-18 → 512-dim → Euclidean → 3層 FC → Sigmoid
本版：MLP(10→128) → Euclidean → 2層 FC → Sigmoid

**Files:**
- Create: `siamese_bean/model/net.py`
- Test: `siamese_bean/tests/test_net.py`

- [ ] **Step 1: 撰寫測試**

  ```python
  # siamese_bean/tests/test_net.py
  import torch
  from siamese_bean.model.net import SpectralEmbedder, SiameseMLP

  def test_embedder_output_shape():
      model = SpectralEmbedder(n_bands=10, embed_dim=128)
      x = torch.randn(8, 10)
      out = model(x)
      assert out.shape == (8, 128)

  def test_embedder_l2_norm():
      model = SpectralEmbedder(n_bands=10, embed_dim=128)
      x = torch.randn(4, 10)
      out = model(x)
      norms = out.norm(dim=1)
      assert torch.allclose(norms, torch.ones(4), atol=1e-5)

  def test_siamese_output_range():
      model = SiameseMLP(n_bands=10, embed_dim=128)
      x1 = torch.randn(16, 10)
      x2 = torch.randn(16, 10)
      out = model(x1, x2)
      assert out.shape == (16,)
      assert (out >= 0).all() and (out <= 1).all()

  def test_same_input_high_similarity():
      model = SiameseMLP(n_bands=10, embed_dim=128)
      model.eval()
      x = torch.randn(4, 10)
      with torch.no_grad():
          out = model(x, x)
      # 相同輸入距離=0，sigmoid(classifier(zeros)) 應 > 0.5
      assert (out > 0.5).all()
  ```

- [ ] **Step 2: 執行測試確認失敗**

  ```bash
  python3 -m pytest siamese_bean/tests/test_net.py -v
  ```
  預期：ImportError

- [ ] **Step 3: 撰寫 net.py**

  ```python
  # siamese_bean/model/net.py
  import torch
  import torch.nn as nn
  import torch.nn.functional as F

  class SpectralEmbedder(nn.Module):
      """10-band 光譜向量 → L2-normalized embedding"""
      def __init__(self, n_bands: int = 10, embed_dim: int = 128):
          super().__init__()
          self.net = nn.Sequential(
              nn.Linear(n_bands, 64),
              nn.BatchNorm1d(64),
              nn.ReLU(),
              nn.Dropout(0.3),
              nn.Linear(64, embed_dim),
          )

      def forward(self, x: torch.Tensor) -> torch.Tensor:
          return F.normalize(self.net(x), p=2, dim=1)

  class SiameseMLP(nn.Module):
      """
      Siamese MLP：兩個 SpectralEmbedder（共用權重）+ 距離分類頭。
      輸出：每個配對的相似度分數 [0,1]（>0.5 表示同類）
      """
      def __init__(self, n_bands: int = 10, embed_dim: int = 128):
          super().__init__()
          self.embedder = SpectralEmbedder(n_bands, embed_dim)
          self.classifier = nn.Sequential(
              nn.Linear(embed_dim, 64),
              nn.BatchNorm1d(64),
              nn.ReLU(),
              nn.Dropout(0.3),
              nn.Linear(64, 1),
              nn.Sigmoid(),
          )

      def forward(self, x1: torch.Tensor, x2: torch.Tensor) -> torch.Tensor:
          e1 = self.embedder(x1)
          e2 = self.embedder(x2)
          diff = torch.abs(e1 - e2)  # Euclidean 差向量
          return self.classifier(diff).squeeze(1)
  ```

- [ ] **Step 4: 執行測試**

  ```bash
  python3 -m pytest siamese_bean/tests/test_net.py -v
  ```
  預期：4 PASSED

- [ ] **Step 5: Commit**

  ```bash
  git add siamese_bean/model/net.py siamese_bean/tests/test_net.py
  git commit -m "feat: add SiameseMLP architecture (SpectralEmbedder + distance classifier)"
  ```

---

### Task 7: 訓練腳本（Mac Mini MPS）

**說明：** Mac Mini Apple Silicon 支援 MPS（Metal Performance Shaders）加速，自動偵測。預計訓練時間：CPU ~3分鐘，MPS ~30秒。

**Files:**
- Create: `siamese_bean/model/train.py`

- [ ] **Step 1: 安裝依賴（Mac Mini 上執行）**

  ```bash
  pip3 install torch torchvision scikit-learn
  ```
  確認 MPS 可用：
  ```bash
  python3 -c "import torch; print(torch.backends.mps.is_available())"
  # 預期：True（Apple Silicon Mac Mini）
  ```

- [ ] **Step 2: 撰寫 train.py**

  ```python
  # siamese_bean/model/train.py
  """
  用法（Mac Mini）：
    python3 -m siamese_bean.model.train \
      --pairs data/pairs/ \
      --stats data/stats.json \
      --out   models/siamese_v1.pt \
      --epochs 50 --batch 64 --lr 5e-4
  """
  import argparse
  import json
  from pathlib import Path

  import torch
  import torch.nn as nn
  from torch.utils.data import DataLoader
  from sklearn.metrics import accuracy_score, recall_score, f1_score

  from siamese_bean.data.dataset import BeanPairDataset
  from siamese_bean.model.net import SiameseMLP

  def get_device() -> torch.device:
      if torch.backends.mps.is_available():
          return torch.device("mps")
      if torch.cuda.is_available():
          return torch.device("cuda")
      return torch.device("cpu")

  def evaluate(model, loader, device) -> dict:
      model.eval()
      all_labels, all_preds = [], []
      with torch.no_grad():
          for x1, x2, y in loader:
              x1, x2 = x1.to(device), x2.to(device)
              scores = model(x1, x2).cpu()
              preds = (scores >= 0.5).float()
              all_labels.extend(y.tolist())
              all_preds.extend(preds.tolist())
      return {
          "accuracy": accuracy_score(all_labels, all_preds),
          "recall":   recall_score(all_labels, all_preds, zero_division=0),
          "f1":       f1_score(all_labels, all_preds, zero_division=0),
      }

  def train(pairs_dir: str, stats_path: str, out_path: str,
            epochs: int = 50, batch_size: int = 64, lr: float = 5e-4,
            n_bands: int = 10):

      device = get_device()
      print(f"[train] device={device}")

      train_ds = BeanPairDataset(f"{pairs_dir}/train_pairs.csv", stats_path)
      val_ds   = BeanPairDataset(f"{pairs_dir}/val_pairs.csv",   stats_path)
      train_dl = DataLoader(train_ds, batch_size=batch_size, shuffle=True,  num_workers=0)
      val_dl   = DataLoader(val_ds,   batch_size=batch_size, shuffle=False, num_workers=0)

      model = SiameseMLP(n_bands=n_bands).to(device)
      optimizer = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=1e-4)
      scheduler = torch.optim.lr_scheduler.StepLR(optimizer, step_size=5, gamma=0.5)
      criterion = nn.BCELoss()

      best_f1, best_state = 0.0, None

      for epoch in range(1, epochs + 1):
          model.train()
          total_loss = 0.0
          for x1, x2, y in train_dl:
              x1, x2, y = x1.to(device), x2.to(device), y.to(device)
              optimizer.zero_grad()
              scores = model(x1, x2)
              loss = criterion(scores, y)
              loss.backward()
              optimizer.step()
              total_loss += loss.item()
          scheduler.step()

          if epoch % 5 == 0 or epoch == epochs:
              metrics = evaluate(model, val_dl, device)
              print(f"[epoch {epoch:3d}] loss={total_loss/len(train_dl):.4f} "
                    f"val_acc={metrics['accuracy']:.4f} "
                    f"val_recall={metrics['recall']:.4f} "
                    f"val_f1={metrics['f1']:.4f}")
              if metrics["f1"] > best_f1:
                  best_f1 = metrics["f1"]
                  best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}

      Path(out_path).parent.mkdir(parents=True, exist_ok=True)
      torch.save({
          "model_state": best_state,
          "n_bands": n_bands,
          "best_val_f1": best_f1,
      }, out_path)
      print(f"[train] Saved best model (val_f1={best_f1:.4f}) → {out_path}")

  if __name__ == "__main__":
      parser = argparse.ArgumentParser()
      parser.add_argument("--pairs",  default="data/pairs/")
      parser.add_argument("--stats",  default="data/stats.json")
      parser.add_argument("--out",    default="models/siamese_v1.pt")
      parser.add_argument("--epochs", type=int, default=50)
      parser.add_argument("--batch",  type=int, default=64)
      parser.add_argument("--lr",     type=float, default=5e-4)
      parser.add_argument("--bands",  type=int, default=10)
      args = parser.parse_args()
      train(args.pairs, args.stats, args.out, args.epochs, args.batch, args.lr, args.bands)
  ```

- [ ] **Step 3: 訓練前先執行 feature extraction 和 pair generation（Mac Mini）**

  ```bash
  # 對每個類別執行特徵提取
  python3 -m siamese_bean.data.extract --raw-dir data/raw/normal --out data/features/normal.csv
  python3 -m siamese_bean.data.extract --raw-dir data/raw/mold   --out data/features/mold.csv

  # 計算並儲存標準化統計（只用訓練集）
  python3 -c "
  from siamese_bean.data.normalize import compute_stats, save_stats
  stats = compute_stats(['data/features/normal.csv', 'data/features/mold.csv'])
  save_stats(stats, 'data/stats.json')
  "

  # 生成配對
  python3 -c "
  from siamese_bean.data.pairs import build_pairs
  build_pairs('data/features/', 'data/pairs/', n_train=10000)
  "
  ```

- [ ] **Step 4: 執行訓練**

  ```bash
  cd /home/kyle/KyleClaude  # 或 Mac Mini 上的對應路徑
  python3 -m siamese_bean.model.train \
    --pairs data/pairs/ --stats data/stats.json \
    --out models/siamese_v1.pt --epochs 50
  ```

  預期輸出（每 5 epochs）：
  ```
  [train] device=mps
  [epoch   5] loss=0.4821 val_acc=0.7200 val_recall=0.7800 val_f1=0.7234
  [epoch  10] loss=0.3156 val_acc=0.8600 val_recall=0.9100 val_f1=0.8734
  ...
  [epoch  50] loss=0.1204 val_acc=0.9400 val_recall=0.9600 val_f1=0.9380
  [train] Saved best model (val_f1=0.9380) → models/siamese_v1.pt
  ```
  目標：val_f1 > 0.90（如果 < 0.85 表示資料量不足，繼續收集豆子）

- [ ] **Step 5: Commit**

  ```bash
  git add siamese_bean/model/train.py models/
  git commit -m "feat: add Siamese MLP training script with MPS/CUDA/CPU auto-detect"
  ```

---

## Phase 4 — 推理模組

### Task 8: 即時推理器

**說明：** 載入訓練好的模型和每個類別的「參考向量集」（訓練集 embedding 的 mean），對新豆子的光譜向量計算與每個類別的相似度，輸出預測類別和信心分數。

**Files:**
- Create: `siamese_bean/inference/predict.py`
- Test: `siamese_bean/tests/test_predict.py`

- [ ] **Step 1: 撰寫測試**

  ```python
  # siamese_bean/tests/test_predict.py
  import numpy as np
  import torch
  from siamese_bean.inference.predict import Predictor

  def make_fake_model_file(tmp_path):
      from siamese_bean.model.net import SiameseMLP
      model = SiameseMLP(n_bands=10, embed_dim=128)
      pt_path = tmp_path / "model.pt"
      torch.save({"model_state": model.state_dict(), "n_bands": 10, "best_val_f1": 0.9}, str(pt_path))
      return str(pt_path)

  def make_fake_stats(tmp_path):
      import json
      stats = {"mean": [0.5] * 10, "std": [0.1] * 10}
      p = tmp_path / "stats.json"
      p.write_text(json.dumps(stats))
      return str(p)

  def test_predictor_returns_class(tmp_path):
      model_path = make_fake_model_file(tmp_path)
      stats_path = make_fake_stats(tmp_path)
      ref = {"normal": np.random.rand(5, 10), "mold": np.random.rand(5, 10)}
      predictor = Predictor(model_path, stats_path, ref)
      vec = np.random.rand(10)
      result = predictor.predict(vec)
      assert "class" in result and "confidence" in result
      assert result["class"] in ["normal", "mold"]
      assert 0.0 <= result["confidence"] <= 1.0
  ```

- [ ] **Step 2: 撰寫 predict.py**

  ```python
  # siamese_bean/inference/predict.py
  """
  用法：
    from siamese_bean.inference.predict import Predictor, build_reference_set
    ref = build_reference_set("data/features/", "data/stats.json", train_bean_max=40)
    predictor = Predictor("models/siamese_v1.pt", "data/stats.json", ref)
    result = predictor.predict(vec_10dim)
    # → {"class": "normal", "confidence": 0.92, "scores": {"normal": 0.92, "mold": 0.08}}
  """
  import csv
  import numpy as np
  import torch
  from pathlib import Path
  from siamese_bean.model.net import SiameseMLP
  from siamese_bean.data.normalize import load_stats, apply_stats

  def build_reference_set(features_dir: str, stats_path: str, train_bean_max: int = 40) -> dict:
      """
      從訓練集 feature CSV 建立每個類別的參考向量集。
      回傳 {class_name: np.ndarray shape=(N, n_bands)}
      """
      stats = load_stats(stats_path)
      ref = {}
      for csv_path in sorted(Path(features_dir).glob("*.csv")):
          class_name = csv_path.stem
          vecs = []
          with open(csv_path) as f:
              for row in csv.DictReader(f):
                  if int(row["bean_id"]) > train_bean_max:
                      continue
                  n_bands = sum(1 for k in row if k.startswith("band_"))
                  vec = np.array([float(row[f"band_{i}"]) for i in range(n_bands)])
                  vecs.append(apply_stats(vec, stats))
          ref[class_name] = np.array(vecs)
      return ref

  class Predictor:
      def __init__(self, model_path: str, stats_path: str, reference_set: dict):
          checkpoint = torch.load(model_path, map_location="cpu")
          n_bands = checkpoint["n_bands"]
          self.model = SiameseMLP(n_bands=n_bands)
          self.model.load_state_dict(checkpoint["model_state"])
          self.model.eval()
          self.stats = load_stats(stats_path)
          # 預計算每個類別的平均 embedding
          self.class_embeddings = {}
          with torch.no_grad():
              for cls, vecs in reference_set.items():
                  t = torch.tensor(vecs, dtype=torch.float32)
                  embs = self.model.embedder(t)
                  self.class_embeddings[cls] = embs.mean(dim=0)  # shape: (embed_dim,)

      def predict(self, vec: np.ndarray) -> dict:
          """
          vec: 原始 10-band 光譜向量（未標準化）
          回傳: {"class": str, "confidence": float, "scores": {cls: float}}
          """
          normalized = apply_stats(vec, self.stats)
          t = torch.tensor(normalized, dtype=torch.float32).unsqueeze(0)

          with torch.no_grad():
              query_emb = self.model.embedder(t).squeeze(0)

          scores = {}
          for cls, ref_emb in self.class_embeddings.items():
              diff = torch.abs(query_emb - ref_emb).unsqueeze(0)
              score = self.model.classifier(diff).item()
              scores[cls] = score

          best_class = max(scores, key=scores.get)
          return {
              "class":      best_class,
              "confidence": scores[best_class],
              "scores":     scores,
          }
  ```

- [ ] **Step 3: 執行測試**

  ```bash
  python3 -m pytest siamese_bean/tests/test_predict.py -v
  ```
  預期：1 PASSED

- [ ] **Step 4: 端對端整合測試（有真實模型時執行）**

  ```bash
  python3 -c "
  import numpy as np
  from siamese_bean.inference.predict import Predictor, build_reference_set

  ref = build_reference_set('data/features/', 'data/stats.json')
  predictor = Predictor('models/siamese_v1.pt', 'data/stats.json', ref)

  # 用一筆測試集資料
  import csv
  with open('data/features/normal.csv') as f:
      row = [r for r in csv.DictReader(f) if int(r['bean_id']) > 45][0]
  vec = np.array([float(row[f'band_{i}']) for i in range(10)])
  result = predictor.predict(vec)
  print('Input: normal bean')
  print(f'Predicted: {result[\"class\"]} (confidence={result[\"confidence\"]:.3f})')
  print(f'All scores: {result[\"scores\"]}')
  "
  ```
  預期：Predicted: normal (confidence > 0.85)

- [ ] **Step 5: Final commit**

  ```bash
  git add siamese_bean/inference/predict.py siamese_bean/tests/test_predict.py
  git commit -m "feat: add Siamese inference with reference-set class prediction"
  ```

---

## 完成標準

實作完成後，以下應全部成立：

- [ ] `python3 -m pytest siamese_bean/tests/ -v` 全部 PASSED（無 skip）
- [ ] `models/siamese_v1.pt` 存在，val_f1 > 0.90
- [ ] `python3 -m siamese_bean.model.train --epochs 1` 在 Mac Mini 能執行無報錯
- [ ] `predictor.predict(vec)` 對測試集正常豆的 recall > 0.90
- [ ] 採集流程：`session_watcher.py` 能正確把新 session 搬到 `data/raw/{class}/`

## 下一步（本 Plan 範圍外）

- **GPIO 即時觸發**：RPi5 IR 感測器觸發採集，取代現在的手動 S 鍵（需修改 C++ binary 或加 trigger file 機制）
- **整合進分豆機**：`predict()` 輸出接 GPIO 氣閥控制（`project_optic_bean_sorter.md` 的 B 方案）
- **增加類別**：目前設計支援任意 N 類，新增類別只需採集並重新 train
- **多光譜視覺化**：將錯誤案例的光譜向量畫出來，找出 floating bean 難以區分的原因
