"""
Siamese MLP training on 10-band multispectral bean data.
Usage:
  python train.py --data ../siamese/data/raw/beans.csv
  python train.py --data ../siamese/data/raw/beans.csv --epochs 100 --embed_dim 64
"""

import argparse
import json
from pathlib import Path

import numpy as np
import torch
import torch.optim as optim
from torch.utils.data import DataLoader

from dataset import (
    TRAIN_IDS, VAL_IDS, TEST_IDS,
    EmbeddingDataset, SiamesePairDataset,
    load_csv, normalize,
)
from evaluate import knn_f1
from model import ContrastiveLoss, SiameseNet


DEVICE = torch.device("mps" if torch.backends.mps.is_available() else "cpu")


def train_epoch(model, loader, optimizer, criterion):
    model.train()
    total_loss = 0.0
    for x1, x2, label in loader:
        x1, x2, label = x1.to(DEVICE), x2.to(DEVICE), label.to(DEVICE)
        optimizer.zero_grad()
        e1, e2 = model(x1, x2)
        loss = criterion(e1, e2, label)
        loss.backward()
        optimizer.step()
        total_loss += loss.item()
    return total_loss / len(loader)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True, help="Path to beans CSV")
    parser.add_argument("--epochs", type=int, default=50)
    parser.add_argument("--embed_dim", type=int, default=64)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--batch_size", type=int, default=256)
    parser.add_argument("--n_pairs", type=int, default=4000)
    parser.add_argument("--margin", type=float, default=1.0)
    parser.add_argument("--out_dir", default="../siamese/models")
    args = parser.parse_args()

    print(f"Device: {DEVICE}")

    df = load_csv(Path(args.data))
    df, norm_stats = normalize(df)

    train_ds = SiamesePairDataset(df, TRAIN_IDS, n_pairs=args.n_pairs)
    train_loader = DataLoader(train_ds, batch_size=args.batch_size, shuffle=True, num_workers=0)

    val_flat = EmbeddingDataset(df, VAL_IDS)
    train_flat = EmbeddingDataset(df, TRAIN_IDS)

    model = SiameseNet(input_dim=10, embed_dim=args.embed_dim).to(DEVICE)
    optimizer = optim.Adam(model.parameters(), lr=args.lr, weight_decay=1e-4)
    scheduler = optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=args.epochs)
    criterion = ContrastiveLoss(margin=args.margin)

    best_f1 = 0.0
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    for epoch in range(1, args.epochs + 1):
        loss = train_epoch(model, train_loader, optimizer, criterion)
        scheduler.step()

        val_f1 = knn_f1(model, train_flat, val_flat, DEVICE, k=5)
        marker = " ★" if val_f1 > best_f1 else ""
        print(f"Epoch {epoch:3d}/{args.epochs} | loss={loss:.4f} | val_f1={val_f1:.4f}{marker}")

        if val_f1 > best_f1:
            best_f1 = val_f1
            torch.save(model.state_dict(), out_dir / "best_model.pt")

    # Final test evaluation
    test_flat = EmbeddingDataset(df, TEST_IDS)
    model.load_state_dict(torch.load(out_dir / "best_model.pt", weights_only=True))
    test_f1 = knn_f1(model, train_flat, test_flat, DEVICE, k=5)
    print(f"\nBest val_f1={best_f1:.4f}  |  test_f1={test_f1:.4f}")

    # Save norm stats for Pi5 inference
    with open(out_dir / "norm_stats.json", "w") as f:
        json.dump({k: list(v) for k, v in norm_stats.items()}, f, indent=2)

    print(f"Model saved → {out_dir}/best_model.pt")
    print(f"Norm stats  → {out_dir}/norm_stats.json")


if __name__ == "__main__":
    main()
