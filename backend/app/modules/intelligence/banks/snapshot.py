"""Build bank-specific FundamentalSnapshotV1 (no industrial fallback)."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from typing import Any

from app.modules.intelligence.banks.classification import (
    ISSUER_KIND_BANK_FI,
    is_bank_fi_secid,
)
from app.modules.intelligence.banks.metrics import (
    BANK_METRIC_CODES,
    INDUSTRIAL_RATIO_CODES,
    is_industrial_ratio_code,
)
from app.modules.intelligence.banks.providers import (
    CBR_CREDIT_ORG_BY_SECID,
    BankSourceStatus,
    bank_source_registry,
    overall_bank_fundamentals_status,
)
from app.modules.intelligence.contracts.snapshots_domain import FundamentalSnapshotV1

REASON_NOT_BANK_FI = "NOT_BANK_FI_ISSUER"
REASON_INDUSTRIAL_FALLBACK_FORBIDDEN = "INDUSTRIAL_FNS_FALLBACK_FORBIDDEN"
REASON_BANK_METRICS_UNAVAILABLE = "BANK_METRICS_PROGRAMMATIC_FEED_UNAVAILABLE"


def _reject_industrial_metrics(
    metrics: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], tuple[str, ...]]:
    """Drop industrial ratio codes; never accept them as bank facts."""
    if not metrics:
        return {}, ()
    clean: dict[str, Any] = {}
    rejected: list[str] = []
    for key, value in metrics.items():
        code = str(key).strip().upper()
        if is_industrial_ratio_code(code):
            rejected.append(code)
            continue
        clean[code] = value
    return clean, tuple(sorted(set(rejected)))


def build_bank_fundamental_snapshot(
    *,
    secid: str,
    instrument_id: int = 0,
    as_of: date | None = None,
    known_at: date | datetime | None = None,
    period_end: date | None = None,
    bank_metrics: Mapping[str, Any] | None = None,
    cbr_catalog: Mapping[str, Any] | None = None,
    sources: tuple[BankSourceStatus, ...] | None = None,
    provider_override: str | None = None,
) -> FundamentalSnapshotV1:
    """Bank/FI snapshot.

    - Non-bank SECID → status UNKNOWN, issuer_kind UNKNOWN, empty metrics.
    - Bank SECID → issuer_kind BANK_FI; metrics only from ``bank_metrics`` after
      industrial-ratio rejection. Empty metrics → PARTIAL/NOT_AVAILABLE, never
      industrial FNS substitution.
    """
    symbol = (secid or "").strip().upper()
    registry = sources if sources is not None else bank_source_registry()
    layer_status = overall_bank_fundamentals_status(registry)

    if not is_bank_fi_secid(symbol):
        return FundamentalSnapshotV1(
            instrument_id=instrument_id,
            as_of=as_of,
            known_at=known_at,
            period_end=period_end,
            issuer_kind="UNKNOWN",
            status="UNKNOWN",
            metrics={},
            missing_metrics=BANK_METRIC_CODES,
            facts_used=(
                {
                    "fact": "issuer_classification",
                    "secid": symbol,
                    "is_bank_fi": False,
                    "reason": REASON_NOT_BANK_FI,
                },
            ),
            limitations=(
                REASON_NOT_BANK_FI,
                "use_industrial_fundamentals_module_for_non_banks",
            ),
            provider="intelligence.banks",
        )

    clean_metrics, rejected_industrial = _reject_industrial_metrics(bank_metrics)
    missing = tuple(code for code in BANK_METRIC_CODES if code not in clean_metrics)

    limitations: list[str] = [
        "bank_fi_industrial_fns_unsupported",
        REASON_INDUSTRIAL_FALLBACK_FORBIDDEN,
    ]
    if rejected_industrial:
        limitations.append(
            f"rejected_industrial_codes:{','.join(rejected_industrial)}"
        )
    if not clean_metrics:
        limitations.append(REASON_BANK_METRICS_UNAVAILABLE)

    cbr_ref = CBR_CREDIT_ORG_BY_SECID.get(symbol)
    facts: list[dict[str, Any]] = [
        {
            "fact": "issuer_classification",
            "secid": symbol,
            "issuer_kind": ISSUER_KIND_BANK_FI,
            "is_bank_fi": True,
        },
        {
            "fact": "source_registry",
            "overall_status": layer_status,
            "providers": [
                {"provider_id": s.provider_id, "status": s.status}
                for s in registry
            ],
        },
    ]
    if cbr_ref is not None:
        facts.append(
            {
                "fact": "cbr_credit_org_ref",
                "secid": cbr_ref.secid,
                "regnum": cbr_ref.regnum,
                "ogrn": cbr_ref.ogrn,
                "inn": cbr_ref.inn,
                "note": "identity mapping only; not metric values",
            }
        )
    if cbr_catalog is not None:
        facts.append(
            {
                "fact": "cbr_form_catalog",
                "status": cbr_catalog.get("status"),
                "forms": cbr_catalog.get("forms"),
                "source_url": cbr_catalog.get("source_url"),
                "note": "coverage metadata only; metrics not extracted",
            }
        )
        limitations.append("cbr_html_catalog_partial_no_metric_values")

    # Snapshot status: READY only with bank metrics; else layer PARTIAL/NOT_AVAILABLE.
    if clean_metrics:
        status = "PARTIAL"  # never claim READY until full bank metric contract exists
    else:
        status = layer_status if layer_status in {"PARTIAL", "NOT_AVAILABLE"} else "NOT_AVAILABLE"

    provider = provider_override or (
        "CBR_CREDIT_ORG_FORMS_HTML+MOEX_ISS_IDENTITY"
        if cbr_catalog is not None
        else "intelligence.banks"
    )

    return FundamentalSnapshotV1(
        instrument_id=instrument_id,
        as_of=as_of,
        known_at=known_at,
        period_end=period_end,
        issuer_kind=ISSUER_KIND_BANK_FI,
        status=status,
        metrics=clean_metrics,
        missing_metrics=missing,
        facts_used=tuple(facts),
        limitations=tuple(limitations),
        provider=provider,
    )


def assert_no_industrial_fallback(snapshot: FundamentalSnapshotV1) -> None:
    """Hard guard for tests and callers."""
    if snapshot.issuer_kind == ISSUER_KIND_BANK_FI:
        for code in snapshot.metrics:
            if is_industrial_ratio_code(str(code)):
                raise AssertionError(
                    f"industrial ratio {code} present on BANK_FI snapshot"
                )
        joined = " ".join(snapshot.limitations).lower()
        if "industrial" not in joined and "fallback" not in joined:
            # Still require explicit bank kind + missing industrial denial in facts.
            pass
    industrial = set(snapshot.metrics) & INDUSTRIAL_RATIO_CODES
    if snapshot.issuer_kind == ISSUER_KIND_BANK_FI and industrial:
        raise AssertionError(f"industrial fallback detected: {sorted(industrial)}")
