"""Research signal verdict (qualitative; not forced PROMISING)."""

from __future__ import annotations

from typing import Any


def decide_research_verdict(
    *,
    development: dict[str, Any],
    holdout: dict[str, Any],
    fold_ics: list[float],
) -> tuple[str, str]:
    """Return (verdict, reason)."""
    dev_ic = (development.get("rank_ic") or {}).get("mean_ic")
    hold_ic = (holdout.get("rank_ic") or {}).get("mean_ic")
    baseline_zero_ic = ((development.get("baselines") or {}).get("zero") or {}).get("rank_ic", {}).get(
        "mean_ic"
    )
    baseline_mean_ic = ((development.get("baselines") or {}).get("train_mean") or {}).get(
        "rank_ic", {}
    ).get("mean_ic")
    valid_fold_ics = [x for x in fold_ics if x == x]  # drop NaN
    positive_folds = sum(1 for x in valid_fold_ics if x > 0)
    majority_positive = bool(valid_fold_ics) and positive_folds >= (len(valid_fold_ics) / 2.0)

    beats_baselines = False
    if dev_ic == dev_ic:  # not NaN
        refs = [x for x in (baseline_zero_ic, baseline_mean_ic) if x == x]
        if refs:
            beats_baselines = all(dev_ic > r for r in refs)
        else:
            beats_baselines = dev_ic > 0

    holdout_ok = hold_ic == hold_ic and hold_ic > 0
    holdout_collapse = hold_ic == hold_ic and hold_ic < -0.02

    if (
        dev_ic == dev_ic
        and dev_ic > 0
        and beats_baselines
        and majority_positive
        and holdout_ok
        and not holdout_collapse
    ):
        return (
            "PROMISING",
            "Positive development IC, beats naive baselines on ranking, "
            "majority of folds positive IC, holdout remains positive.",
        )
    if (
        (dev_ic == dev_ic and dev_ic > 0)
        or (hold_ic == hold_ic and hold_ic > 0)
        or (majority_positive and beats_baselines)
    ):
        return (
            "MIXED",
            "Some ranking signal present but unstable across folds and/or holdout.",
        )
    return (
        "NO_EDGE",
        "CatBoost ranking signal absent, negative, or not better than naive baselines.",
    )
