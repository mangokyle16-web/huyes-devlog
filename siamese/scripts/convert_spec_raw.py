#!/usr/bin/env python3
"""
把 Pi5 pipeline 輸出的 spec_raw.csv 轉換成 Siamese 訓練 CSV 格式。

Pi5 格式（spec_raw.csv）：
  rows = wavelength_nm (350~930nm, 30 bands)
  cols = bean_1, bean_2, ..., bean_N

輸出格式（Siamese CSV）：
  bean_id, class, pass, b0, b1, ..., b9

用法（Pi5 上）：
  python3 convert_spec_raw.py \
    --session /home/kyle/Desktop/Report/LuxVisions_xxx \
    --class good \
    --bean_id_start 1 \
    --out /home/kyle/KyleClaude/siamese/data/raw/beans.csv

  # 多個 session 合併
  python3 convert_spec_raw.py --session session1 --class good --bean_id_start 1  --out beans.csv
  python3 convert_spec_raw.py --session session2 --class black --bean_id_start 51 --out beans.csv --append
"""
import argparse, csv
from pathlib import Path
import numpy as np

# 從 30 個波段中選 10 個代表性波段（nm）
# 涵蓋 UV（黴菌）、可見光（烘焙色）、NIR（Agtron 850/930nm）
SELECTED_NM = [350, 410, 470, 530, 590, 650, 710, 790, 850, 930]
BAND_COLS   = [f"b{i}" for i in range(10)]


def convert(session_dir: Path, class_name: str, bean_id_start: int,
            out_path: Path, append: bool = False):
    spec_csv = session_dir / "spec_raw.csv"
    if not spec_csv.exists():
        print(f"  [跳過] 找不到 spec_raw.csv：{session_dir}")
        return 0

    # 讀取 spec_raw.csv
    with open(spec_csv) as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    wavelengths = [int(r["wavelength_nm"]) for r in rows]
    bean_cols   = [k for k in rows[0].keys() if k.startswith("bean_")]

    # 建立 wavelength → row index 映射
    wl_idx = {wl: i for i, wl in enumerate(wavelengths)}

    # 選出 10 個波段的 index（找最近的）
    band_indices = []
    for nm in SELECTED_NM:
        closest = min(wl_idx.keys(), key=lambda w: abs(w - nm))
        band_indices.append(wl_idx[closest])

    # 轉換：每顆豆 → 一行
    out_rows = []
    for col_idx, col_name in enumerate(bean_cols):
        bean_id = bean_id_start + col_idx
        bands   = [float(rows[bi][col_name]) for bi in band_indices]
        out_rows.append({
            "bean_id": bean_id,
            "class":   class_name,
            "pass":    1,  # spec_raw 是單次拍攝
            **{f"b{i}": bands[i] for i in range(10)},
        })

    mode = "a" if append else "w"
    with open(out_path, mode, newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["bean_id", "class", "pass"] + BAND_COLS)
        if not append:
            writer.writeheader()
        writer.writerows(out_rows)

    print(f"  ✓ {class_name}: {len(out_rows)} 顆 → {out_path}")
    return len(out_rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--session",      required=True, help="Session 目錄路徑")
    parser.add_argument("--class",        dest="cls", required=True, help="豆子類別（good/black/sour/...）")
    parser.add_argument("--bean_id_start",type=int, default=1)
    parser.add_argument("--out",          required=True)
    parser.add_argument("--append",       action="store_true")
    args = parser.parse_args()

    n = convert(
        session_dir   = Path(args.session).expanduser(),
        class_name    = args.cls,
        bean_id_start = args.bean_id_start,
        out_path      = Path(args.out).expanduser(),
        append        = args.append,
    )
    print(f"完成：{n} 筆")


if __name__ == "__main__":
    main()
