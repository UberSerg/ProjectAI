"""Pure Model Diagnostics V0 metrics — no DB, no look-ahead, no HOLDOUT selection."""

from __future__ import annotations

from typing import Any

import numpy as np


def average_ranks(values: list[float] | np.ndarray) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    order = np.argsort(arr, kind="stable")
    ranks = np.empty(len(arr), dtype=float)
    i = 0
    while i < len(arr):
        j = i
        while j + 1 < len(arr) and arr[order[j + 1]] == arr[order[i]]:
            j += 1
        avg = 0.5 * (i + j) + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def spearman_ic(scores: list[float], realized: list[float]) -> float | None:
    if len(scores) < 2 or len(scores) != len(realized):
        return None
    ra = average_ranks(scores)
    rb = average_ranks(realized)
    ra = ra - ra.mean()
    rb = rb - rb.mean()
    denom = float(np.sqrt((ra * ra).sum() * (rb * rb).sum()))
    if denom <= 0:
        return None
    return float((ra * rb).sum() / denom)


def top_k_count(n: int, share: float) -> int:
    """Deterministic Top-K size from a share of the cross-section."""
    if n <= 0:
        return 0
    return max(1, int(np.ceil(n * share)))


def top_k_indices(scores: list[float], k: int) -> set[int]:
    order = sorted(range(len(scores)), key=lambda i: (-scores[i], i))
    return set(order[:k])


def top_k_precision_recall(
    pred_scores: list[float],
    realized: list[float],
    *,
    share: float = 0.20,
) -> dict[str, float | int]:
    """Precision/recall of predicted Top-K vs realized Top-K (same K).

    Precision = |pred ∩ realized| / |pred|
    Recall = |pred ∩ realized| / |realized|
    Jaccard = |pred ∩ realized| / |pred ∪ realized|
    """
    n = len(pred_scores)
    k = top_k_count(n, share)
    pred = top_k_indices(pred_scores, k)
    real = top_k_indices(realized, k)
    inter = pred & real
    union = pred | real
    return {
        "n": n,
        "k": k,
        "precision": len(inter) / k if k else 0.0,
        "recall": len(inter) / k if k else 0.0,
        "jaccard": len(inter) / len(union) if union else 0.0,
        "overlap": len(inter),
    }


def top_k_mean_realized(
    pred_scores: list[float],
    realized: list[float],
    *,
    share: float,
) -> float | None:
    n = len(pred_scores)
    k = top_k_count(n, share)
    if k == 0:
        return None
    pred = top_k_indices(pred_scores, k)
    return float(np.mean([realized[i] for i in pred]))


def bottom_contamination(
    pred_scores: list[float],
    realized: list[float],
    *,
    top_share: float = 0.20,
    bottom_share: float = 0.20,
) -> float | None:
    """Share of predicted Top-K that landed in realized bottom quantile."""
    n = len(pred_scores)
    k_top = top_k_count(n, top_share)
    k_bot = top_k_count(n, bottom_share)
    if k_top == 0:
        return None
    pred_top = top_k_indices(pred_scores, k_top)
    # bottom = lowest realized
    order = sorted(range(n), key=lambda i: (realized[i], i))
    real_bot = set(order[:k_bot])
    return len(pred_top & real_bot) / k_top


def top_bottom_spread(
    pred_scores: list[float],
    realized: list[float],
    *,
    share: float = 0.20,
) -> float | None:
    n = len(pred_scores)
    k = top_k_count(n, share)
    if k == 0:
        return None
    order = sorted(range(n), key=lambda i: (-pred_scores[i], i))
    top = [realized[i] for i in order[:k]]
    bot = [realized[i] for i in order[-k:]]
    return float(np.mean(top) - np.mean(bot))


def persistence(prev_set: set[Any], curr_set: set[Any]) -> float | None:
    if not prev_set:
        return None
    return len(prev_set & curr_set) / len(prev_set)


def entry_exit_churn(prev_set: set[Any], curr_set: set[Any]) -> dict[str, float | int]:
    entered = curr_set - prev_set
    exited = prev_set - curr_set
    denom = max(len(prev_set), 1)
    return {
        "entered": len(entered),
        "exited": len(exited),
        "entry_churn": len(entered) / denom,
        "exit_churn": len(exited) / denom,
    }


def sample_maturity_label(mature_dates: int) -> str:
    if mature_dates <= 0:
        return "TOO_EARLY"
    if mature_dates <= 4:
        return "VERY_FEW"
    if mature_dates <= 19:
        return "PRELIMINARY"
    if mature_dates <= 49:
        return "ACCUMULATING"
    return "SUBSTANTIAL"


SAMPLE_MATURITY_RU: dict[str, str] = {
    "TOO_EARLY": "Слишком рано для оценки",
    "VERY_FEW": "Очень мало наблюдений",
    "PRELIMINARY": "Предварительные данные",
    "ACCUMULATING": "История начинает накапливаться",
    "SUBSTANTIAL": "Накоплена более содержательная выборка",
}
