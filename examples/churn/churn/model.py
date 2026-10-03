"""Logistic regression trained with batch gradient descent, plus ROC AUC."""

import math


def sigmoid(z: float) -> float:
    if z >= 0:
        return 1 / (1 + math.exp(-z))
    e = math.exp(z)
    return e / (1 + e)


def fit_scaler(X: list[list[float]]) -> list[tuple[float, float]]:
    """Per-column (mean, std); std of a constant column is treated as 1."""
    n = len(X)
    out = []
    for j in range(len(X[0])):
        col = [x[j] for x in X]
        mean = sum(col) / n
        std = math.sqrt(sum((v - mean) ** 2 for v in col) / n) or 1.0
        out.append((mean, std))
    return out


def scale(x: list[float], scaler: list[tuple[float, float]]) -> list[float]:
    return [(v - m) / s for v, (m, s) in zip(x, scaler)]


def train(X: list[list[float]], y: list[int], epochs: int = 300, lr: float = 0.5) -> dict:
    scaler = fit_scaler(X)
    Xs = [scale(x, scaler) for x in X]
    w = [0.0] * len(X[0])
    b = 0.0
    n = len(Xs)
    for _ in range(epochs):
        gw = [0.0] * len(w)
        gb = 0.0
        for x, t in zip(Xs, y):
            err = sigmoid(sum(wi * xi for wi, xi in zip(w, x)) + b) - t
            for j, xj in enumerate(x):
                gw[j] += err * xj
            gb += err
        w = [wi - lr * g / n for wi, g in zip(w, gw)]
        b -= lr * gb / n
    return {"weights": w, "bias": b, "scaler": scaler}


def predict_proba(model: dict, x: list[float]) -> float:
    return sigmoid(sum(w * v for w, v in zip(model["weights"], x)) + model["bias"])


def auc(scores: list[float], labels: list[int]) -> float:
    """Probability that a random positive outranks a random negative (ties count half)."""
    order = sorted(range(len(scores)), key=lambda i: scores[i])
    ranks = [0.0] * len(scores)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and scores[order[j + 1]] == scores[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        i = j + 1
    pos = sum(labels)
    neg = len(labels) - pos
    rank_sum = sum(r for r, t in zip(ranks, labels) if t)
    return (rank_sum - pos * (pos + 1) / 2) / (pos * neg)
