"""Coverage matrix and earliest honest known_at for Intelligence Research V1.

When history is insufficient, produce coverage + eligibility instead of a giant OOS.
News with known_at ≈ first observation (often today) is PROSPECTIVE_ONLY.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any

from app.modules.intelligence.research.constants import (
    CBR_MACRO_EARLIEST_HONEST_KNOWN_AT,
    DOMAIN_BASE,
    DOMAIN_EVENT,
    DOMAIN_INTRADAY,
    DOMAIN_MACRO,
    DOMAIN_NEWS,
    DOMAIN_RICH_FUNDAMENTAL,
    EVALUATION_MODES,
    FEATURE_PACKS,
    FNS_EARLIEST_HONEST_KNOWN_AT,
    MIN_HISTORICAL_YEARS_FOR_OOS,
    MIN_ROWS_FOR_OOS,
    MODE_HISTORICAL_EVALUABLE,
    MODE_INSUFFICIENT_HISTORY,
    MODE_NOT_ELIGIBLE,
    MODE_PROSPECTIVE_ONLY,
    PACK_BASE,
    SPLIT_EVENT_EARLIEST_HONEST_KNOWN_AT,
)
from app.modules.intelligence.research.packs import build_feature_pack


def _as_date(value: date | datetime | str | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


@dataclass(frozen=True, slots=True)
class DomainEvidence:
    """Observed or declared coverage for one intelligence domain."""

    domain: str
    earliest_honest_known_at: date | None
    latest_known_at: date | None = None
    row_count: int = 0
    known_at_quality: str = "UNKNOWN"
    # HONEST_HISTORICAL | OBSERVED_TODAY | PROXY | UNKNOWN | MISSING
    status: str = "UNKNOWN"  # READY | PARTIAL | NOT_READY | UNKNOWN
    limitations: tuple[str, ...] = ()
    evidence: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "earliest_honest_known_at", _as_date(self.earliest_honest_known_at))
        object.__setattr__(self, "latest_known_at", _as_date(self.latest_known_at))

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key in ("earliest_honest_known_at", "latest_known_at"):
            value = payload.get(key)
            if isinstance(value, date):
                payload[key] = value.isoformat()
        payload["limitations"] = list(self.limitations)
        return payload


@dataclass(frozen=True, slots=True)
class PackCoverageRow:
    pack: str
    evaluation_mode: str
    earliest_honest_known_at: date | None
    historical_eligible: bool
    prospective_only: bool
    domains: tuple[str, ...]
    feature_count: int
    blockers: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.evaluation_mode not in EVALUATION_MODES:
            raise ValueError(f"unsupported evaluation_mode: {self.evaluation_mode}")
        object.__setattr__(self, "earliest_honest_known_at", _as_date(self.earliest_honest_known_at))

    def to_dict(self) -> dict[str, Any]:
        return {
            "pack": self.pack,
            "evaluation_mode": self.evaluation_mode,
            "earliest_honest_known_at": (
                self.earliest_honest_known_at.isoformat()
                if self.earliest_honest_known_at
                else None
            ),
            "historical_eligible": self.historical_eligible,
            "prospective_only": self.prospective_only,
            "domains": list(self.domains),
            "feature_count": self.feature_count,
            "blockers": list(self.blockers),
            "notes": list(self.notes),
        }


def architectural_prior_evidence(*, as_of: date | None = None) -> dict[str, DomainEvidence]:
    """Honest priors when store probes are unavailable (no fabricated backdates)."""
    today = as_of or date.today()
    return {
        DOMAIN_BASE: DomainEvidence(
            domain=DOMAIN_BASE,
            earliest_honest_known_at=date(2014, 1, 1),
            latest_known_at=today,
            row_count=10_000,
            known_at_quality="HONEST_HISTORICAL",
            status="READY",
            limitations=("survivorship_free_universe_not_claimed",),
            evidence={"source": "architectural_prior", "basis": "MOEX_EOD_ANALYTICS_TECHNICAL"},
        ),
        DOMAIN_INTRADAY: DomainEvidence(
            domain=DOMAIN_INTRADAY,
            earliest_honest_known_at=None,
            latest_known_at=None,
            row_count=0,
            known_at_quality="MISSING",
            status="NOT_READY",
            limitations=(
                "60m_history_not_assumed_without_store_evidence",
                "no_fabricated_intraday_backfill",
            ),
            evidence={"source": "architectural_prior"},
        ),
        DOMAIN_RICH_FUNDAMENTAL: DomainEvidence(
            domain=DOMAIN_RICH_FUNDAMENTAL,
            earliest_honest_known_at=FNS_EARLIEST_HONEST_KNOWN_AT,
            latest_known_at=today,
            row_count=0,
            known_at_quality="HONEST_HISTORICAL",
            status="PARTIAL",
            limitations=(
                "fns_ras_industrial_only",
                "bank_fi_excluded",
                "online_depth_approx_2021_2025",
            ),
            evidence={
                "source": "architectural_prior",
                "basis": "FNS_GIR_BO",
                "canonical_window_start": FNS_EARLIEST_HONEST_KNOWN_AT.isoformat(),
            },
        ),
        DOMAIN_EVENT: DomainEvidence(
            domain=DOMAIN_EVENT,
            earliest_honest_known_at=SPLIT_EVENT_EARLIEST_HONEST_KNOWN_AT,
            latest_known_at=today,
            row_count=0,
            known_at_quality="PROXY",
            status="PARTIAL",
            limitations=(
                "splits_mechanical_ready",
                "dividend_pit_partial",
                "missing_dividend_is_not_zero",
            ),
            evidence={"source": "architectural_prior"},
        ),
        DOMAIN_MACRO: DomainEvidence(
            domain=DOMAIN_MACRO,
            earliest_honest_known_at=CBR_MACRO_EARLIEST_HONEST_KNOWN_AT,
            latest_known_at=today,
            row_count=0,
            known_at_quality="HONEST_HISTORICAL",
            status="PARTIAL",
            limitations=("ruonia_conditional", "relations_already_embed_key_rate_fx_in_BASE"),
            evidence={"source": "architectural_prior", "basis": "CBR_SERIES"},
        ),
        DOMAIN_NEWS: DomainEvidence(
            domain=DOMAIN_NEWS,
            earliest_honest_known_at=today,
            latest_known_at=today,
            row_count=0,
            known_at_quality="OBSERVED_TODAY",
            status="NOT_READY",
            limitations=(
                "do_not_backdate_known_at_to_publisher_claim_alone",
                "first_observation_often_today",
                "prospective_only_until_honest_history_accumulates",
            ),
            evidence={"source": "architectural_prior", "policy": "MAX_PUBLISHED_OBSERVED"},
        ),
    }


def merge_domain_evidence(
    priors: dict[str, DomainEvidence],
    overrides: dict[str, DomainEvidence] | None,
) -> dict[str, DomainEvidence]:
    if not overrides:
        return dict(priors)
    out = dict(priors)
    for key, value in overrides.items():
        out[key] = value
    return out


def _years_between(start: date, end: date) -> float:
    return (end - start).days / 365.25


def classify_domain(
    evidence: DomainEvidence,
    *,
    as_of: date,
    min_years: float = float(MIN_HISTORICAL_YEARS_FOR_OOS),
) -> str:
    """Classify a single domain into evaluation mode."""
    if evidence.domain == DOMAIN_NEWS:
        quality = evidence.known_at_quality
        if quality in {"OBSERVED_TODAY", "MISSING"} or evidence.status == "NOT_READY":
            return MODE_PROSPECTIVE_ONLY
        earliest = evidence.earliest_honest_known_at
        if earliest is None:
            return MODE_PROSPECTIVE_ONLY
        if _years_between(earliest, as_of) < min_years:
            return MODE_INSUFFICIENT_HISTORY
        return MODE_HISTORICAL_EVALUABLE

    if evidence.status == "NOT_READY" or evidence.known_at_quality == "MISSING":
        return MODE_NOT_ELIGIBLE
    earliest = evidence.earliest_honest_known_at
    if earliest is None:
        return MODE_INSUFFICIENT_HISTORY
    if earliest > as_of:
        return MODE_NOT_ELIGIBLE
    span = _years_between(earliest, as_of)
    if span < min_years and evidence.row_count < MIN_ROWS_FOR_OOS:
        return MODE_INSUFFICIENT_HISTORY
    if span < min_years:
        return MODE_INSUFFICIENT_HISTORY
    return MODE_HISTORICAL_EVALUABLE


def _max_earliest(dates: list[date | None]) -> date | None:
    present = [d for d in dates if d is not None]
    if not present:
        return None
    return max(present)


def classify_pack(
    pack_name: str,
    domains: dict[str, DomainEvidence],
    *,
    as_of: date | None = None,
) -> PackCoverageRow:
    as_of_d = as_of or date.today()
    pack = build_feature_pack(pack_name)
    domain_keys = (DOMAIN_BASE,) + tuple(pack.additive_domains)
    modes: list[str] = []
    blockers: list[str] = []
    notes: list[str] = []
    earliest_candidates: list[date | None] = []

    for key in domain_keys:
        evidence = domains.get(key)
        if evidence is None:
            modes.append(MODE_NOT_ELIGIBLE)
            blockers.append(f"missing_domain_evidence:{key}")
            continue
        mode = classify_domain(evidence, as_of=as_of_d)
        modes.append(mode)
        earliest_candidates.append(evidence.earliest_honest_known_at)
        if mode == MODE_PROSPECTIVE_ONLY:
            blockers.append(f"prospective_only:{key}")
        elif mode == MODE_INSUFFICIENT_HISTORY:
            blockers.append(f"insufficient_history:{key}")
        elif mode == MODE_NOT_ELIGIBLE:
            blockers.append(f"not_eligible:{key}")

    # Pack mode is conservative: worst concrete class wins.
    if MODE_NOT_ELIGIBLE in modes:
        pack_mode = MODE_NOT_ELIGIBLE
    elif MODE_PROSPECTIVE_ONLY in modes:
        pack_mode = MODE_PROSPECTIVE_ONLY
    elif MODE_INSUFFICIENT_HISTORY in modes:
        pack_mode = MODE_INSUFFICIENT_HISTORY
    else:
        pack_mode = MODE_HISTORICAL_EVALUABLE

    # INTELLIGENCE_FULL: drop domains that are not historical-evaluable rather than
    # forcing the whole pack prospective — but only when at least BASE is historical.
    if pack_name != PACK_BASE and pack_mode != MODE_HISTORICAL_EVALUABLE:
        notes.append(
            "pack_requires_all_included_domains_historically_honest; "
            "prefer coverage matrix over giant OOS"
        )

    # Combined pack start is the most restrictive domain earliest. If any included
    # domain lacks an honest earliest, do not invent one from sibling domains.
    if any(value is None for value in earliest_candidates):
        earliest = None if pack_mode != MODE_HISTORICAL_EVALUABLE else _max_earliest(
            earliest_candidates
        )
    else:
        earliest = _max_earliest(earliest_candidates)
    historical = pack_mode == MODE_HISTORICAL_EVALUABLE
    prospective = pack_mode == MODE_PROSPECTIVE_ONLY
    return PackCoverageRow(
        pack=pack_name,
        evaluation_mode=pack_mode,
        earliest_honest_known_at=earliest,
        historical_eligible=historical,
        prospective_only=prospective,
        domains=domain_keys,
        feature_count=len(pack.feature_names),
        blockers=tuple(blockers),
        notes=tuple(notes),
    )


def build_coverage_matrix(
    *,
    as_of: date | None = None,
    domain_overrides: dict[str, DomainEvidence] | None = None,
    packs: tuple[str, ...] = FEATURE_PACKS,
) -> dict[str, Any]:
    """Coverage matrix + earliest honest known_at per pack / domain."""
    as_of_d = as_of or date.today()
    domains = merge_domain_evidence(
        architectural_prior_evidence(as_of=as_of_d),
        domain_overrides,
    )
    domain_modes = {
        key: classify_domain(ev, as_of=as_of_d) for key, ev in domains.items()
    }
    rows = [classify_pack(name, domains, as_of=as_of_d) for name in packs]
    historical_packs = [r.pack for r in rows if r.historical_eligible]
    prospective_domains = [
        key for key, mode in domain_modes.items() if mode == MODE_PROSPECTIVE_ONLY
    ]
    insufficient = [
        r.pack for r in rows if r.evaluation_mode == MODE_INSUFFICIENT_HISTORY
    ]
    return {
        "schema": "IntelligenceResearchCoverageMatrixV1",
        "experiment_name": "Intelligence Research V1",
        "is_dataset_v5": False,
        "as_of": as_of_d.isoformat(),
        "min_historical_years_for_oos": MIN_HISTORICAL_YEARS_FOR_OOS,
        "min_rows_for_oos": MIN_ROWS_FOR_OOS,
        "domains": {key: ev.to_dict() for key, ev in domains.items()},
        "domain_evaluation_modes": domain_modes,
        "packs": [r.to_dict() for r in rows],
        "historical_evaluable_packs": historical_packs,
        "prospective_only_domains": prospective_domains,
        "insufficient_history_packs": insufficient,
        "news_policy": (
            "If documents were only first observed today, do not backdate known_at; "
            "treat news features as prospective-only until honest history accumulates."
        ),
        "recommendation": (
            "Run chronological OOS only for historical_evaluable_packs with a real frame; "
            "otherwise stop at this coverage matrix."
        ),
    }


def recommended_oos_window(
    pack_row: PackCoverageRow,
    *,
    as_of: date | None = None,
) -> dict[str, Any] | None:
    """Earliest honest window for a historically eligible pack (no outcome tuning)."""
    if not pack_row.historical_eligible or pack_row.earliest_honest_known_at is None:
        return None
    as_of_d = as_of or date.today()
    start = pack_row.earliest_honest_known_at
    # Leave room for expanding walk-forward; do not shrink by outcome peeking.
    return {
        "pack": pack_row.pack,
        "date_from": start.isoformat(),
        "date_to": as_of_d.isoformat(),
        "span_years": round(_years_between(start, as_of_d), 3),
        "policy": "earliest_honest_known_at_no_after_result_tuning",
    }

