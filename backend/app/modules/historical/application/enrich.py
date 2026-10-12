"""Deterministic enrichment over parsed historical observations.

Input observations are never mutated. Missing inputs produce no derived row.
A computed zero is emitted only when both inputs exist and the arithmetic
result is zero; it is never used as a placeholder for a missing input.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date

from app.modules.historical.domain.evidence import ParsedObservation, RecordQuality

DERIVED_NOT_SOURCE = "derived_not_source"
YOY_NORMALIZATION_VERSION = "yoy_v1"
INDUSTRIAL_RATIO_NORMALIZATION_VERSION = "industrial_ratio_v1"
VALUATION_NORMALIZATION_VERSION = "valuation_v1"
YOY_MIN_DAYS = 350
YOY_MAX_DAYS = 380
YOY_TARGET_DAYS = 365

INDUSTRIAL_RATIO_CODES: frozenset[str] = frozenset({"EBITDA", "REVENUE", "TOTAL_DEBT"})

_DERIVED_VERSIONS = frozenset(
    {
        YOY_NORMALIZATION_VERSION,
        INDUSTRIAL_RATIO_NORMALIZATION_VERSION,
        VALUATION_NORMALIZATION_VERSION,
    }
)

# (derived metric_id, numerator metric_id, denominator metric_id)
_INDUSTRIAL_RATIOS: tuple[tuple[str, str, str], ...] = (
    ("EBITDA.over.REVENUE", "EBITDA", "REVENUE"),
    ("TOTAL_DEBT.over.EBITDA", "TOTAL_DEBT", "EBITDA"),
    ("TOTAL_DEBT.over.REVENUE", "TOTAL_DEBT", "REVENUE"),
)

# Price-earnings only. Both sides must be strictly positive.
_VALUATION_RATIOS: tuple[tuple[str, str, str], ...] = (
    ("valuation.pe", "MARKET_CAP", "NET_INCOME"),
)

_IdentityKey = tuple[tuple[str, str], ...]
_SeriesKey = tuple[str, _IdentityKey]


def industrial_ratio_allowed(identity: Mapping[str, str]) -> bool:
    """Return False when the issuer is a bank or other financial institution.

    EBITDA, REVENUE, and TOTAL_DEBT are industrial ratios. They are not
    computed for ``issuer_kind == BANK_FI``.
    """
    kind = str(identity.get("issuer_kind", "")).strip().upper()
    return kind != "BANK_FI"


def year_over_year(
    observations: Sequence[ParsedObservation],
) -> tuple[ParsedObservation, ...]:
    """Relative change for the same metric and issuer about one year apart.

    Period ends must be 350 to 380 days apart. Pairs from different issuers
    are not computed. Each later period keeps the prior closest to 365 days.
    """
    series = _series_by_period(observations)
    derived: list[ParsedObservation] = []
    for (metric_id, identity_key), by_period in series.items():
        points = sorted(by_period.items(), key=lambda item: item[0])
        for later_end, later in points:
            prior = _closest_prior(later, points)
            if prior is None:
                continue
            change = _relative_change(later.value, prior.value)
            if change is None:
                continue
            derived.append(
                _derived_observation(
                    metric_id=f"{metric_id}.yoy",
                    normalization_version=YOY_NORMALIZATION_VERSION,
                    value=change,
                    left=prior,
                    right=later,
                    identity_key=identity_key,
                    period_end=later_end,
                )
            )
    return _sorted(derived)


def industrial_ratios(
    observations: Sequence[ParsedObservation],
) -> tuple[ParsedObservation, ...]:
    """EBITDA / REVENUE / TOTAL_DEBT ratios for a shared issuer and period.

    Banks (``BANK_FI``) produce no rows. A missing component or a zero
    denominator produces no row for that ratio.
    """
    return _ratios(
        observations,
        specs=_INDUSTRIAL_RATIOS,
        normalization_version=INDUSTRIAL_RATIO_NORMALIZATION_VERSION,
        require_industrial_permission=True,
        require_positive=False,
    )


def derive_valuation(
    observations: Sequence[ParsedObservation],
) -> tuple[ParsedObservation, ...]:
    """Emit a valuation only when both market cap and net income are usable.

    Insufficient, missing, or non-positive inputs produce an empty result,
    never a zero valuation.
    """
    return _ratios(
        observations,
        specs=_VALUATION_RATIOS,
        normalization_version=VALUATION_NORMALIZATION_VERSION,
        require_industrial_permission=False,
        require_positive=True,
    )


def enrich(
    observations: Sequence[ParsedObservation],
) -> tuple[ParsedObservation, ...]:
    """Derived rows only: year-over-year, industrial ratios, then valuation.

    The input sequence and its observation objects are left unchanged.
    """
    return (
        *year_over_year(observations),
        *industrial_ratios(observations),
        *derive_valuation(observations),
    )


def _ratios(
    observations: Sequence[ParsedObservation],
    *,
    specs: tuple[tuple[str, str, str], ...],
    normalization_version: str,
    require_industrial_permission: bool,
    require_positive: bool,
) -> tuple[ParsedObservation, ...]:
    panels = _panels(observations)
    derived: list[ParsedObservation] = []
    for (identity_key, period_end), metrics in panels.items():
        identity = _identity_from_key(identity_key)
        if require_industrial_permission and not industrial_ratio_allowed(identity):
            continue
        for metric_id, numerator_id, denominator_id in specs:
            numerator = metrics.get(numerator_id)
            denominator = metrics.get(denominator_id)
            if numerator is None or denominator is None:
                continue
            if not _same_measure(numerator, denominator):
                continue
            value = _quotient(
                numerator.value,
                denominator.value,
                require_positive=require_positive,
            )
            if value is None:
                continue
            derived.append(
                _derived_observation(
                    metric_id=metric_id,
                    normalization_version=normalization_version,
                    value=value,
                    left=numerator,
                    right=denominator,
                    identity_key=identity_key,
                    period_end=period_end,
                )
            )
    return _sorted(derived)


def _series_by_period(
    observations: Sequence[ParsedObservation],
) -> dict[_SeriesKey, dict[date, ParsedObservation]]:
    grouped: dict[_SeriesKey, dict[date, list[ParsedObservation]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for observation in observations:
        if not _is_source(observation) or observation.period_end is None:
            continue
        key = (observation.metric_id, _identity_key(observation.issuer_identity))
        grouped[key][observation.period_end].append(observation)
    selected: dict[_SeriesKey, dict[date, ParsedObservation]] = {}
    for key, by_period in grouped.items():
        chosen: dict[date, ParsedObservation] = {}
        for period_end, group in by_period.items():
            picked = _select_unambiguous(group)
            if picked is not None:
                chosen[period_end] = picked
        if chosen:
            selected[key] = chosen
    return selected


def _panels(
    observations: Sequence[ParsedObservation],
) -> dict[tuple[_IdentityKey, date], dict[str, ParsedObservation]]:
    grouped: dict[tuple[_IdentityKey, date], dict[str, list[ParsedObservation]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for observation in observations:
        if not _is_source(observation) or observation.period_end is None:
            continue
        key = (_identity_key(observation.issuer_identity), observation.period_end)
        grouped[key][observation.metric_id].append(observation)
    panels: dict[tuple[_IdentityKey, date], dict[str, ParsedObservation]] = {}
    for key, metrics in grouped.items():
        chosen: dict[str, ParsedObservation] = {}
        for metric_id, group in metrics.items():
            picked = _select_unambiguous(group)
            if picked is not None:
                chosen[metric_id] = picked
        if chosen:
            panels[key] = chosen
    return panels


def _closest_prior(
    later: ParsedObservation,
    points: Sequence[tuple[date, ParsedObservation]],
) -> ParsedObservation | None:
    later_end = later.period_end
    if later_end is None:
        return None
    best: tuple[tuple[int, int, str, str], ParsedObservation] | None = None
    for prior_end, prior in points:
        if prior_end >= later_end:
            continue
        if not _same_measure(prior, later):
            continue
        days = (later_end - prior_end).days
        if days < YOY_MIN_DAYS or days > YOY_MAX_DAYS:
            continue
        if _relative_change(later.value, prior.value) is None:
            continue
        rank = (abs(days - YOY_TARGET_DAYS), days, prior.content_hash, prior.source_id)
        if best is None or rank < best[0]:
            best = (rank, prior)
    if best is None:
        return None
    return best[1]


def _select_unambiguous(
    group: Sequence[ParsedObservation],
) -> ParsedObservation | None:
    valued = [observation for observation in group if observation.value is not None]
    if not valued:
        return None
    if len({observation.value for observation in valued}) != 1:
        return None
    return min(valued, key=lambda observation: (observation.content_hash, observation.source_id))


def _is_source(observation: ParsedObservation) -> bool:
    if observation.normalization_version in _DERIVED_VERSIONS:
        return False
    if DERIVED_NOT_SOURCE in observation.limitations:
        return False
    return not observation.metric_id.endswith(".yoy")


def _same_measure(left: ParsedObservation, right: ParsedObservation) -> bool:
    return (
        left.currency == right.currency
        and left.unit == right.unit
        and left.reporting_standard == right.reporting_standard
    )


def _relative_change(current: float | None, prior: float | None) -> float | None:
    if current is None or prior is None or prior == 0.0:
        return None
    return (float(current) - float(prior)) / abs(float(prior))


def _quotient(
    numerator: float | None,
    denominator: float | None,
    *,
    require_positive: bool,
) -> float | None:
    if numerator is None or denominator is None or denominator == 0.0:
        return None
    if require_positive and (numerator <= 0.0 or denominator <= 0.0):
        return None
    return float(numerator) / float(denominator)


def _identity_key(identity: Mapping[str, str]) -> _IdentityKey:
    return tuple(sorted((str(key), str(value)) for key, value in identity.items()))


def _identity_from_key(identity_key: _IdentityKey) -> dict[str, str]:
    return dict(identity_key)


def _merged_quality(left: RecordQuality, right: RecordQuality) -> RecordQuality:
    if left is RecordQuality.UNRESOLVED or right is RecordQuality.UNRESOLVED:
        return RecordQuality.UNRESOLVED
    if left is RecordQuality.QUARANTINE or right is RecordQuality.QUARANTINE:
        return RecordQuality.QUARANTINE
    return RecordQuality.ACCEPTED


def _derived_observation(
    *,
    metric_id: str,
    normalization_version: str,
    value: float,
    left: ParsedObservation,
    right: ParsedObservation,
    identity_key: _IdentityKey,
    period_end: date,
) -> ParsedObservation:
    """Build one derived row.

    ``input_hashes`` keeps ``left`` then ``right``: the earlier period then the
    later period for year-over-year, and the numerator then the denominator
    for ratios and valuation.
    """
    input_hashes = (left.content_hash, right.content_hash)
    limitations: tuple[str, ...] = (DERIVED_NOT_SOURCE,)
    if value == 0.0:
        limitations = (DERIVED_NOT_SOURCE, "explicit_zero")
    quality = _merged_quality(left.quality_status, right.quality_status)
    identity = _identity_from_key(identity_key)
    payload = "|".join(
        (
            normalization_version,
            metric_id,
            repr(identity_key),
            period_end.isoformat(),
            format(value, ".12g"),
            *input_hashes,
        )
    )
    content_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    same_source = left.source_id == right.source_id
    same_standard = left.reporting_standard == right.reporting_standard
    return ParsedObservation(
        metric_id=metric_id,
        source_id=right.source_id if same_source else "derived",
        content_hash=content_hash,
        normalization_version=normalization_version,
        quality_status=quality,
        value=value,
        unit="ratio",
        currency=None,
        period=right.period,
        period_end=period_end,
        reporting_standard=right.reporting_standard if same_standard else None,
        issuer_identity=identity,
        evidence=f"derived:{normalization_version}:{left.content_hash}:{right.content_hash}",
        limitations=limitations,
        extra={"input_hashes": input_hashes},
    )


def _sorted(rows: Sequence[ParsedObservation]) -> tuple[ParsedObservation, ...]:
    return tuple(
        sorted(
            rows,
            key=lambda row: (
                row.metric_id,
                _identity_key(row.issuer_identity),
                row.period_end or date.min,
                row.content_hash,
            ),
        )
    )


__all__ = [
    "DERIVED_NOT_SOURCE",
    "INDUSTRIAL_RATIO_CODES",
    "INDUSTRIAL_RATIO_NORMALIZATION_VERSION",
    "VALUATION_NORMALIZATION_VERSION",
    "YOY_MAX_DAYS",
    "YOY_MIN_DAYS",
    "YOY_NORMALIZATION_VERSION",
    "derive_valuation",
    "enrich",
    "industrial_ratio_allowed",
    "industrial_ratios",
    "year_over_year",
]
