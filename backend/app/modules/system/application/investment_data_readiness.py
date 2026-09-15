"""Investment Data Readiness V1 — cross-domain gate for Dataset V3 planning.

Deterministic measurement only. Does not mutate Dataset V2, Prediction, Candidate,
Policy, Risk, Shadow, or research_fi_v1.

Statuses are READY / PARTIAL / NOT_READY / UNKNOWN — no fake percentage scores.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


class ReadinessStatus(StrEnum):
    READY = "READY"
    PARTIAL = "PARTIAL"
    NOT_READY = "NOT_READY"
    UNKNOWN = "UNKNOWN"


def _domain(
    *,
    code: str,
    title_ru: str,
    status: ReadinessStatus,
    coverage_ru: str,
    pit_ru: str,
    limitation_ru: str,
    dataset_v3: str,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "code": code,
        "title_ru": title_ru,
        "status": status.value,
        "coverage_ru": coverage_ru,
        "pit_ru": pit_ru,
        "limitation_ru": limitation_ru,
        "dataset_v3": dataset_v3,
        "evidence": evidence or {},
    }


def build_investment_data_readiness(session: Session) -> dict[str, Any]:
    """Aggregate stored evidence into a human/research readiness table."""
    domains: list[dict[str, Any]] = []

    # --- Market EOD ---
    candle_n = _safe_scalar(
        session,
        "SELECT COUNT(*) FROM market.candles WHERE timeframe = '1d'",
    )
    domains.append(
        _domain(
            code="market_eod",
            title_ru="Market EOD prices",
            status=ReadinessStatus.READY if candle_n > 0 else ReadinessStatus.NOT_READY,
            coverage_ru=f"{candle_n} daily candles in store",
            pit_ru="Exchange session dates; raw OHLCV immutable",
            limitation_ru="Survivorship-free historical universe not reconstructed",
            dataset_v3="optional_core",
            evidence={"daily_candles": candle_n},
        )
    )

    # --- Technical ---
    tech_n = _safe_scalar(session, "SELECT COUNT(*) FROM technical.signals_daily")
    domains.append(
        _domain(
            code="technical",
            title_ru="Technical signals",
            status=ReadinessStatus.READY if tech_n > 0 else ReadinessStatus.PARTIAL,
            coverage_ru=f"{tech_n} signal rows" if tech_n else "no signals counted",
            pit_ru="Computed from candles known at as_of",
            limitation_ru="Depends on EOD completeness per instrument",
            dataset_v3="optional_core",
            evidence={"technical_signals_daily": tech_n},
        )
    )

    # --- Relations ---
    rel_n = _safe_scalar(session, "SELECT COUNT(*) FROM analytics.relation_snapshots")
    domains.append(
        _domain(
            code="relations",
            title_ru="Relations (return correlation)",
            status=ReadinessStatus.READY if rel_n > 0 else ReadinessStatus.PARTIAL,
            coverage_ru=f"{rel_n} relation snapshots",
            pit_ru="Snapshots carry as_of_date; portfolio matrix uses latest persisted",
            limitation_ru="FI often missing from Relations universe",
            dataset_v3="optional",
            evidence={"relation_snapshots": rel_n},
        )
    )

    # --- Fundamentals RAS ---
    fund = _fundamentals_domain(session)
    domains.append(fund)

    # --- Banks ---
    domains.append(
        _domain(
            code="fundamentals_banks",
            title_ru="Bank / FI fundamentals",
            status=ReadinessStatus.NOT_READY,
            coverage_ru="FNS industrial RAS hard-denies banks (SBER/VTBR/…)",
            pit_ru="N/A — model not implemented",
            limitation_ru="Industrial ratios must not be applied to banks; CBR/XBRL future track",
            dataset_v3="blocker_if_required",
            evidence={"fns_support": "NOT_SUPPORTED_BY_FNS_RAS_V1"},
        )
    )

    # --- Dividends ---
    div_n = _safe_scalar(session, "SELECT COUNT(*) FROM fundamentals.dividend_events")
    from app.modules.fundamentals.application.dividend_known_at import (
        dividend_known_at_quality_report,
    )
    from app.modules.fundamentals.application.dividend_provider import get_dividend_provider

    div_ready = get_dividend_provider().readiness()
    try:
        known_at_report = dividend_known_at_quality_report(session)
    except Exception as exc:  # noqa: BLE001
        known_at_report = {"error": str(exc)[:200]}
    div_status = ReadinessStatus.NOT_READY
    if div_n > 0:
        div_status = ReadinessStatus.PARTIAL
    elif bool(div_ready.get("accepted")):
        div_status = ReadinessStatus.PARTIAL
    domains.append(
        _domain(
            code="dividends",
            title_ru="Dividends",
            status=div_status,
            coverage_ru=(
                f"{div_n} events; exact={known_at_report.get('exact_publication_datetime', 0)}, "
                f"official_date={known_at_report.get('official_publication_date', 0)}, "
                f"meeting_proxy={known_at_report.get('meeting_proxy', 0)}, "
                f"record_proxy={known_at_report.get('record_date_proxy', 0)}"
            ),
            pit_ru=(
                "known_at quality tracked; exact disclosure timestamps still unavailable "
                "from lawful free sources"
            ),
            limitation_ru=(
                "Bounded IR XLSX (MGNT+LKOH). e-disclosure 403. MOEX sitenews cannot filter "
                "issuer dividend disclosures. No LLM extraction."
            ),
            dataset_v3="blocker" if div_status == ReadinessStatus.NOT_READY else "partial",
            evidence={
                "dividend_events": div_n,
                "provider": div_ready,
                "known_at_quality": known_at_report,
                "entitlement": _entitlement_evidence(),
            },
        )
    )

    # --- Total return ---
    tr_status = ReadinessStatus.NOT_READY
    tr_limit = "Splits mechanical path exists separately; dividends/entitlement incomplete"
    if div_n > 0:
        tr_status = ReadinessStatus.PARTIAL
        tr_limit = (
            "Gross TR research: APPROVED events + entitlement calendar (PARTIAL); "
            "strict PIT mode excludes approximate known_at; Dataset V2 unchanged"
        )
    domains.append(
        _domain(
            code="total_return",
            title_ru="Gross Total Return labels",
            status=tr_status,
            coverage_ru=(
                "Blocked without dividend lifecycle + entitlement"
                if div_n == 0
                else f"Research preview eligible where events={div_n}"
            ),
            pit_ru="Requires known_at of dividend events and ex/record convention",
            limitation_ru=tr_limit,
            dataset_v3="blocker" if tr_status == ReadinessStatus.NOT_READY else "partial",
            evidence={"depends_on": ["dividends", "corporate_actions_splits"], "dividend_events": div_n},
        )
    )

    # --- Corporate actions ---
    ca_n = _safe_scalar(
        session,
        "SELECT COUNT(*) FROM market.corporate_actions",
    )
    domains.append(
        _domain(
            code="corporate_actions",
            title_ru="Corporate actions (splits)",
            status=ReadinessStatus.PARTIAL if ca_n > 0 else ReadinessStatus.NOT_READY,
            coverage_ru=f"{ca_n} corporate_actions rows",
            pit_ru="known_at / effective_date separation required",
            limitation_ru="Mechanical splits ≠ dividends; incomplete event taxonomy",
            dataset_v3="partial",
            evidence={"corporate_actions": ca_n},
        )
    )

    # --- Fixed income ---
    from app.modules.investment.application.enrichment_service import fi_coverage_report

    fi = fi_coverage_report(session)
    domains.append(
        _domain(
            code="fixed_income",
            title_ru="Fixed Income cashflows",
            status=ReadinessStatus.PARTIAL,
            coverage_ru=(
                f"terms={fi.get('bond_terms')} cashflows={fi.get('instruments_with_cashflows')}"
            ),
            pit_ru="CURRENT_STATE_ONLY historical reconstruction — not full PIT schedules",
            limitation_ru="research_fi_v1 pin unchanged; historical schedule PIT PARTIAL by design",
            dataset_v3="partial",
            evidence=dict(fi) if isinstance(fi, dict) else {"raw": str(fi)},
        )
    )

    # --- Credit ---
    from app.modules.investment.application.credit_rating_provider import credit_coverage_v1

    credit = credit_coverage_v1(session)
    credit_verdict = str(credit.get("verdict") or credit.get("status") or "NOT_READY")
    domains.append(
        _domain(
            code="credit",
            title_ru="Corporate credit ratings",
            status=ReadinessStatus.NOT_READY
            if "NOT_READY" in credit_verdict.upper()
            else ReadinessStatus.PARTIAL,
            coverage_ru=str(credit.get("coverage") or credit.get("message") or credit_verdict),
            pit_ru="No production public rating provider with known_at",
            limitation_ru="Credit Intelligence stores NOT_READY provider state by design",
            dataset_v3="blocker_optional",
            evidence=dict(credit) if isinstance(credit, dict) else {},
        )
    )

    # --- Macro / CBR ---
    domains.append(
        _domain(
            code="macro_cbr",
            title_ru="CBR hurdle / macro",
            status=ReadinessStatus.PARTIAL,
            coverage_ru="CBR key rate used in research UI where wired",
            pit_ru="Must use rate known at decision time",
            limitation_ru="Not a full macro feature pack for Dataset V3",
            dataset_v3="optional",
            evidence={},
        )
    )

    # --- Survivorship ---
    from app.modules.market.application.historical_universe import (
        HISTORICAL_EQUITY_UNIVERSE_V3,
        summarize_historical_universe_v3,
    )

    try:
        univ = summarize_historical_universe_v3(session)
    except Exception as exc:  # noqa: BLE001
        univ = {"error": str(exc)[:200], "members": 0}
    univ_n = int(univ.get("members") or 0)
    hist_n = int(univ.get("historical_inventory_members") or 0)
    delisted_n = int(univ.get("delisted_or_inactive") or 0)
    auth_n = int(univ.get("authoritative_from_boundaries") or 0)
    proxy_n = int(univ.get("proxy_from_boundaries") or 0)
    domains.append(
        _domain(
            code="survivorship",
            title_ru="Survivorship-free universe",
            status=ReadinessStatus.PARTIAL if univ_n > 0 else ReadinessStatus.NOT_READY,
            coverage_ru=(
                f"{HISTORICAL_EQUITY_UNIVERSE_V3}: {univ_n} members "
                f"(research={univ.get('research_cohort_members')}, "
                f"historical_inventory={hist_n}, delisted/inactive={delisted_n}); "
                f"authoritative_from={auth_n}, proxy_from={proxy_n}"
                if univ_n
                else "contract missing / empty"
            ),
            pit_ru="universe_as_of_v3(T) by SECID; research cohort ≠ historical inventory",
            limitation_ru=(
                "V3 adds seeded delisted inventory (e.g. URKA) beyond current 40 research names; "
                "still not a full MOEX survivorship-free dump."
            ),
            dataset_v3="partial" if univ_n > 0 else "blocker",
            evidence=dict(univ) if isinstance(univ, dict) else {"raw": str(univ)},
        )
    )

    gate = _build_dataset_v3_summary(session, domains)
    return {
        "version": "INVESTMENT_DATA_READINESS_V1",
        "domains": domains,
        "dataset_v3": gate,
        "dataset_v2_unchanged": True,
        "note_ru": (
            "Readiness is measurement only. READY ≠ automatic inclusion in Dataset V3. "
            "Null/missing never coerced to zero."
        ),
    }


def _build_dataset_v3_summary(session: Session, domains: list[dict[str, Any]]) -> dict[str, Any]:
    from app.modules.fundamentals.application.dataset_v3_gate import (
        build_dataset_v3_readiness_gate,
    )

    fund_gate = build_dataset_v3_readiness_gate(session)
    blockers = [
        d["title_ru"]
        for d in domains
        if d["dataset_v3"] in {"blocker", "partial"}
        and d["code"] in {"dividends", "total_return", "survivorship"}
        and d["status"] in {"NOT_READY", "PARTIAL", "UNKNOWN"}
    ]
    # Also include hard blockers from other domains
    blockers += [
        d["title_ru"]
        for d in domains
        if d["dataset_v3"] == "blocker"
        and d["status"] in {"NOT_READY", "PARTIAL", "UNKNOWN"}
        and d["title_ru"] not in blockers
    ]
    available = [
        d["title_ru"]
        for d in domains
        if d["status"] == "READY" and d["dataset_v3"] in {"optional_core", "optional", "partial"}
    ]
    partial = [d["title_ru"] for d in domains if d["status"] == "PARTIAL"]

    overall = "NOT_READY"
    fund_status = str(fund_gate.get("gate") or "NOT_READY")
    # Never overall READY while critical PARTIAL domains remain.
    if fund_status == "READY_FOR_BUILD" and not blockers:
        overall = "READY"
    elif fund_status in {"READY_FOR_DATASET_DESIGN", "READY_FOR_BUILD"}:
        overall = "PARTIAL"
    if blockers and overall == "READY":
        overall = "PARTIAL"

    recommended_start, start_evidence = _recommended_feature_start(session, fund_gate)

    return {
        "overall_status": overall,
        "fundamentals_gate": fund_status,
        "blocking_domains": blockers,
        "available_domains": available,
        "partial_domains": partial,
        "recommended_start_date": recommended_start,
        "recommended_start_evidence": start_evidence,
        "reasons_ru": list(fund_gate.get("blockers") or [])
        + list(fund_gate.get("design_notes") or [])[:4],
        "human_summary_ru": fund_gate.get("human_summary")
        or "Dataset V3 не готов: дивиденды / total return / survivorship блокируют READY_FOR_BUILD.",
        "dataset_spec_mutated": False,
        "to_become_ready_ru": [
            "Production dividend lifecycle with known_at (no LLM critical extraction)",
            "Entitlement / ex-date semantics for Gross Total Return",
            "Survivorship-aware historical universe design",
            "Bank fundamentals track (separate from industrial RAS)",
            "Broader FNS issuer mapping (ROSN/GMKN/… gaps)",
        ],
    }


def _recommended_feature_start(
    session: Session, fund_gate: dict[str, Any]
) -> tuple[str | None, str]:
    """Prefer earliest stored RAS known_at; fall back to fundamentals gate evidence."""
    try:
        row = session.execute(
            text(
                """
                SELECT MIN(known_at::date)::text AS earliest,
                       MAX(known_at::date)::text AS latest,
                       COUNT(*)::int AS n
                FROM fundamentals.financial_reports
                WHERE reporting_standard = 'RAS' AND known_at IS NOT NULL
                """
            )
        ).mappings().first()
    except Exception:  # noqa: BLE001
        row = None

    if row and row.get("earliest") and int(row.get("n") or 0) > 0:
        return (
            str(row["earliest"]),
            (
                f"MIN(known_at) over {row['n']} RAS reports in store "
                f"(latest={row.get('latest')}). Prices/technical may start earlier; "
                "fundamentals features should not claim history before this date."
            ),
        )

    return (
        fund_gate.get("candidate_start_date"),
        str(
            fund_gate.get("candidate_start_evidence")
            or "No RAS known_at in store yet — use gate default when reports appear."
        ),
    )


def _fundamentals_domain(session: Session) -> dict[str, Any]:
    try:
        from app.modules.fundamentals.application.coverage_service import (
            FundamentalCoverageService,
        )
        from app.modules.fundamentals.infrastructure.models import fundamentals_schema_ready

        if not fundamentals_schema_ready(session):
            return _domain(
                code="fundamentals_ras",
                title_ru="Fundamentals RAS (FNS)",
                status=ReadinessStatus.NOT_READY,
                coverage_ru="schema missing",
                pit_ru="N/A",
                limitation_ru="Apply fundamentals migrations",
                dataset_v3="blocker",
            )
        cohort = FundamentalCoverageService(session).cohort_table()
        n = int(cohort.get("industrial_with_reports") or 0)
        status = ReadinessStatus.PARTIAL if n > 0 else ReadinessStatus.NOT_READY
        if n >= 8:
            status = ReadinessStatus.PARTIAL  # designable but not full cohort
        return _domain(
            code="fundamentals_ras",
            title_ru="Fundamentals RAS (FNS GIR BO)",
            status=status,
            coverage_ru=(
                f"industrial_with_reports={n}; mapped={cohort.get('industrial_mapped')}; "
                f"unmapped={cohort.get('unmapped')}; banks={cohort.get('bank_unsupported')}"
            ),
            pit_ru="known_at from datePresent/actualBfoDate — never period_end",
            limitation_ru=(
                "Online FNS ~2021–2025; revisions latest-only (history incomplete); "
                "many cohort names still UNMAPPED"
            ),
            dataset_v3="partial_core",
            evidence={
                "industrial_with_reports": n,
                "reporting_standard": "RAS",
                "provider": "FNS_GIR_BO",
            },
        )
    except Exception as exc:  # noqa: BLE001 — readiness must not crash coverage page
        return _domain(
            code="fundamentals_ras",
            title_ru="Fundamentals RAS (FNS)",
            status=ReadinessStatus.UNKNOWN,
            coverage_ru="error collecting evidence",
            pit_ru="unknown",
            limitation_ru=str(exc)[:200],
            dataset_v3="unknown",
        )


def _entitlement_evidence() -> dict[str, Any]:
    try:
        from app.modules.fundamentals.application.entitlement import entitlement_readiness

        return entitlement_readiness()
    except Exception as exc:  # noqa: BLE001
        return {"status": "UNKNOWN", "error": str(exc)[:200]}


def _safe_scalar(session: Session, sql: str) -> int:
    try:
        return int(session.execute(text(sql)).scalar_one() or 0)
    except Exception:  # noqa: BLE001
        return 0
