import torch
import torch.nn as nn
import torch.nn.functional as F


class SpectralMLP(nn.Module):
    """Shared backbone: 10-band spectral vector → embedding."""

    def __init__(self, input_dim: int = 10, embed_dim: int = 64):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(input_dim, 64),
            nn.BatchNorm1d(64),
            nn.ReLU(),
            nn.Linear(64, 128),
            nn.BatchNorm1d(128),
            nn.ReLU(),
            nn.Dropout(0.3),
            nn.Linear(128, embed_dim),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)


class SiameseNet(nn.Module):
    """Siamese network with shared SpectralMLP backbone."""

    def __init__(self, input_dim: int = 10, embed_dim: int = 64):
        super().__init__()
        self.backbone = SpectralMLP(input_dim, embed_dim)

    def forward_one(self, x: torch.Tensor) -> torch.Tensor:
        return self.backbone(x)

    def forward(self, x1: torch.Tensor, x2: torch.Tensor):
        e1 = self.forward_one(x1)
        e2 = self.forward_one(x2)
        return e1, e2


class ContrastiveLoss(nn.Module):
    """
    Contrastive loss: same-class pairs → close, different-class → margin apart.
    label=1 means same class, label=0 means different.
    """

    def __init__(self, margin: float = 1.0):
        super().__init__()
        self.margin = margin

    def forward(self, e1: torch.Tensor, e2: torch.Tensor, label: torch.Tensor) -> torch.Tensor:
        dist = F.pairwise_distance(e1, e2)
        loss = label * dist.pow(2) + (1 - label) * F.relu(self.margin - dist).pow(2)
        return loss.mean()
