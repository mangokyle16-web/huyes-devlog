"""Evaluation utilities: KNN classifier on embeddings, confusion matrix."""

import numpy as np
import torch
from sklearn.metrics import classification_report, confusion_matrix, f1_score
from sklearn.neighbors import KNeighborsClassifier

from dataset import EmbeddingDataset


def extract_embeddings(model, dataset: EmbeddingDataset, device: torch.device):
    model.eval()
    loader = torch.utils.data.DataLoader(dataset, batch_size=512, shuffle=False)
    embeddings, labels = [], []
    with torch.no_grad():
        for X, y in loader:
            e = model.forward_one(X.to(device))
            embeddings.append(e.cpu().numpy())
            labels.extend(y)
    return np.vstack(embeddings), np.array(labels)


def knn_f1(model, support_ds: EmbeddingDataset, query_ds: EmbeddingDataset,
           device: torch.device, k: int = 5) -> float:
    e_support, y_support = extract_embeddings(model, support_ds, device)
    e_query, y_query = extract_embeddings(model, query_ds, device)
    knn = KNeighborsClassifier(n_neighbors=min(k, len(e_support)))
    knn.fit(e_support, y_support)
    y_pred = knn.predict(e_query)
    return f1_score(y_query, y_pred, average="macro", zero_division=0)


def full_report(model, support_ds: EmbeddingDataset, query_ds: EmbeddingDataset,
                device: torch.device, k: int = 5) -> str:
    e_support, y_support = extract_embeddings(model, support_ds, device)
    e_query, y_query = extract_embeddings(model, query_ds, device)
    knn = KNeighborsClassifier(n_neighbors=min(k, len(e_support)))
    knn.fit(e_support, y_support)
    y_pred = knn.predict(e_query)
    report = classification_report(y_query, y_pred, zero_division=0)
    cm = confusion_matrix(y_query, y_pred)
    return f"{report}\nConfusion Matrix:\n{cm}"
