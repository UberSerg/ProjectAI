"""Peer-relative ranks using only same-as_of historically available observations."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def percentile_rank(value: float, peers: Sequence[float]) -> float | None:
    """Fraction of peer values strictly below ``value`` (0..1). Needs ≥1 peer."""
    if not peers:
        return None
    below = sum(1 for peer in peers if peer < value)
    return below / float(len(peers))


def compute_peer_ranks(
    subject_derived: Mapping[str, float],
    peer_derived: Sequence[Mapping[str, float]],
    *,
    keys: Sequence[str] = (
        "net_margin",
        "roe",
        "roa",
        "equity_to_assets",
        "debt_to_equity",
        "asset_turnover",
    ),
) -> dict[str, Any]:
    """Rank subject vs peers that already expose the metric at the same as_of.

    Peers without the metric are excluded for that key (not treated as 0).
    """
    ranks: dict[str, Any] = {}
    for key in keys:
        subject = subject_derived.get(key)
        if subject is None:
            continue
        peer_values = [
            float(peer[key]) for peer in peer_derived if peer.get(key) is not None
        ]
        if not peer_values:
            continue
        ranks[key] = {
            "value": float(subject),
            "percentile_rank": percentile_rank(float(subject), peer_values),
            "peer_count": len(peer_values),
        }
    return {
        "basis": "SAME_AS_OF_VISIBLE_OBSERVATIONS",
        "ranks": ranks,
    }
