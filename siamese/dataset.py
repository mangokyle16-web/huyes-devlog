"""
Dataset for Siamese few-shot spectral bean defect detection.

CSV format (from Pi5 export_dataset.py):
  bean_id, class, pass, b0, b1, b2, b3, b4, b5, b6, b7, b8, b9

bean_id 是每類各自的 1-50，跨類可重複。
Split 以 bean_id 編號切割（每類獨立），防止同顆豆的 10 pass 跨 train/val：
  train: bean_id 1–40（每類）
  val:   bean_id 41–45（每類）
  test:  bean_id 46–50（每類）
"""

import random
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from torch.utils.data import Dataset


BAND_COLS = [f"b{i}" for i in range(10)]
TRAIN_IDS = list(range(1, 41))
VAL_IDS   = list(range(41, 46))
TEST_IDS  = list(range(46, 51))


def load_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df.columns = df.columns.str.strip()
    return df


def normalize(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    stats = {col: (df[col].mean(), df[col].std() + 1e-8) for col in BAND_COLS}
    for col, (mean, std) in stats.items():
        df[col] = (df[col] - mean) / std
    return df, stats


class SiamesePairDataset(Dataset):
    """
    Generates pairs (x1, x2, label) where label=1 same class, label=0 different.
    n_pairs pairs are sampled per epoch from the given bean_id split.
    """

    def __init__(
        self,
        df: pd.DataFrame,
        bean_ids: list[int],
        n_pairs: int = 4000,
        seed: int = 42,
    ):
        sub = df[df["bean_id"].isin(bean_ids)].reset_index(drop=True)
        self.classes = sub["class"].unique().tolist()
        self.class_to_rows: dict[str, list[int]] = {
            c: sub.index[sub["class"] == c].tolist() for c in self.classes
        }
        self.X = sub[BAND_COLS].values.astype(np.float32)
        self.y = sub["class"].values
        self.n_pairs = n_pairs

        rng = random.Random(seed)
        self.pairs = self._sample_pairs(rng)

    def _sample_pairs(self, rng: random.Random) -> list[tuple[int, int, int]]:
        pairs = []
        for _ in range(self.n_pairs // 2):
            # same-class pair
            c = rng.choice(self.classes)
            i, j = rng.sample(self.class_to_rows[c], 2)
            pairs.append((i, j, 1))

            # different-class pair
            c1, c2 = rng.sample(self.classes, 2)
            i = rng.choice(self.class_to_rows[c1])
            j = rng.choice(self.class_to_rows[c2])
            pairs.append((i, j, 0))
        return pairs

    def __len__(self) -> int:
        return len(self.pairs)

    def __getitem__(self, idx: int):
        i, j, label = self.pairs[idx]
        x1 = torch.tensor(self.X[i])
        x2 = torch.tensor(self.X[j])
        return x1, x2, torch.tensor(label, dtype=torch.float32)


class EmbeddingDataset(Dataset):
    """Flat dataset for building support set and evaluating embeddings."""

    def __init__(self, df: pd.DataFrame, bean_ids: list[int]):
        sub = df[df["bean_id"].isin(bean_ids)].reset_index(drop=True)
        self.X = torch.tensor(sub[BAND_COLS].values.astype(np.float32))
        self.labels = sub["class"].values
        self.bean_ids = sub["bean_id"].values

    def __len__(self) -> int:
        return len(self.X)

    def __getitem__(self, idx: int):
        return self.X[idx], self.labels[idx]
