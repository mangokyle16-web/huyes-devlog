"""生成假資料測試 pipeline，不需要相機。"""
import csv
import random
from pathlib import Path

random.seed(42)
CLASSES = ["good", "black", "sour", "broken"]
BANDS = 10

out = Path(__file__).parent.parent / "data/raw/beans_dummy.csv"
out.parent.mkdir(parents=True, exist_ok=True)

rows = []
for cls_idx, cls in enumerate(CLASSES):
    for bean_id in range(1, 51):   # 每類各自 bean_id 1-50
        base = [0.5 + cls_idx * 0.1 + i * 0.02 for i in range(BANDS)]
        for pass_num in range(1, 11):  # 10 pass/顆
            bands = {f"b{i}": base[i] + random.gauss(0, 0.05) for i in range(BANDS)}
            rows.append({"bean_id": bean_id, "class": cls,
                          "pass": pass_num, **bands})

with open(out, "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=["bean_id","class","pass"] + [f"b{i}" for i in range(BANDS)])
    writer.writeheader()
    writer.writerows(rows)

print(f"Wrote {len(rows)} rows → {out}")
