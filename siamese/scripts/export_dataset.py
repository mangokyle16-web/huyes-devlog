"""
Pi5 執行：把 session_watcher 搬移好的光譜資料整合成 CSV 傳給 Mac Mini。

資料來源：~/KyleClaude/data/beans/<class>/<session>/*.csv
  每個 .csv 含 10 個 band 的強度值（一顆豆一個 pass）

用法：
  python3 export_dataset.py --data_dir ~/KyleClaude/data/beans --out beans.csv
  scp beans.csv kyleckagent1@<mac_ip>:~/KyleClaude/siamese/data/raw/
"""

import argparse
import csv
import re
from pathlib import Path


BAND_COLS = [f"b{i}" for i in range(10)]


def parse_bean_id(filename: str) -> int | None:
    m = re.search(r"bean_(\d+)", filename)
    return int(m.group(1)) if m else None


def read_bands_from_file(path: Path) -> list[float] | None:
    """讀取一個 .csv 檔，回傳 10 個 band 值的 list。
    格式依 multispectral_demo 輸出而定，需根據實際格式調整。
    """
    try:
        with open(path) as f:
            reader = csv.DictReader(f)
            for row in reader:
                bands = [float(row.get(f"band_{i}", row.get(f"b{i}", 0))) for i in range(10)]
                return bands
    except Exception as e:
        print(f"  Warning: {path.name}: {e}")
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data_dir", default="~/KyleClaude/data/beans")
    parser.add_argument("--out", default="beans.csv")
    args = parser.parse_args()

    data_dir = Path(args.data_dir).expanduser()
    rows = []
    skipped = 0

    for class_dir in sorted(data_dir.iterdir()):
        if not class_dir.is_dir():
            continue
        class_name = class_dir.name
        for session_dir in sorted(class_dir.iterdir()):
            if not session_dir.is_dir():
                continue
            for csv_file in sorted(session_dir.glob("*.csv")):
                bean_id = parse_bean_id(csv_file.stem)
                if bean_id is None:
                    skipped += 1
                    continue
                pass_num = int(re.search(r"pass_?(\d+)", csv_file.stem).group(1)) if re.search(r"pass_?(\d+)", csv_file.stem) else 1
                bands = read_bands_from_file(csv_file)
                if bands is None or len(bands) != 10:
                    skipped += 1
                    continue
                rows.append({
                    "bean_id": bean_id,
                    "class": class_name,
                    "pass": pass_num,
                    **{f"b{i}": bands[i] for i in range(10)},
                })

    with open(args.out, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["bean_id", "class", "pass"] + BAND_COLS)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Exported {len(rows)} samples → {args.out}  (skipped {skipped})")
    classes = {r["class"] for r in rows}
    for c in sorted(classes):
        n = sum(1 for r in rows if r["class"] == c)
        bean_ids = {r["bean_id"] for r in rows if r["class"] == c}
        print(f"  {c}: {n} samples, {len(bean_ids)} beans")


if __name__ == "__main__":
    main()
