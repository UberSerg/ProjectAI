"""InstrumentCapabilities resolver — catalog presence ≠ predict."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.infrastructure.market.models import Candle, Instrument, InstrumentSource
from app.modules.investment.application.equity_lot_size import resolve_equity_lot_sizes
from app.modules.investment.infrastructure.models import BondCashflow, BondTerm
from app.modules.market.application.instrument_classification import (
    CATALOG_ONLY,
    INACTIVE,
    OFZ_GOV,
    CORPORATE_BOND,
    MUNICIPAL_BOND,
    FUND,
)
from app.modules.market.application.research_universe import is_research_member
from app.modules.fundamentals.infrastructure.models import SecurityIssuerMapping


@dataclass(frozen=True, slots=True)
class InstrumentCapabilities:
    can_live_quote: bool
    can_portfolio_value: bool
    can_predict: bool
    can_fundamental: bool
    can_fixed_income_analyze: bool
    can_rebalance: bool
    can_cashflow_project: bool
    reasons: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        return payload


def resolve_instrument_capabilities(
    session: Session,
    instrument: Instrument,
    *,
    research_member: bool | None = None,
) -> InstrumentCapabilities:
    iid = int(instrument.id)
    member = (
        bool(research_member)
        if research_member is not None
        else is_research_member(session, iid)
    )
    support = (instrument.support_level or "").upper()
    subtype = (instrument.instrument_subtype or "").lower()
    asset = (instrument.asset_class or "").lower()
    reasons: dict[str, str] = {}

    sources = list(
        session.scalars(
            select(InstrumentSource).where(
                InstrumentSource.instrument_id == iid,
                InstrumentSource.valid_to.is_(None),
            )
        )
    )
    has_moex = any(s.source in {"MOEX", "MOEX_ISS"} for s in sources)
    active = bool(instrument.is_active) and support != INACTIVE

    can_live_quote = active and has_moex and support != CATALOG_ONLY
    if not can_live_quote:
        reasons["can_live_quote"] = "inactive_or_no_moex_or_catalog_only"

    # Prediction ONLY for research membership / existing model universe.
    can_predict = member and asset == "equity" and active
    if not can_predict:
        reasons["can_predict"] = (
            "not_research_member"
            if not member
            else "inactive_or_non_equity"
        )

    has_candle = (
        session.scalar(
            select(func.count())
            .select_from(Candle)
            .where(Candle.instrument_id == iid, Candle.timeframe == "1d")
        )
        or 0
    ) > 0

    bond_term = session.scalar(select(BondTerm).where(BondTerm.instrument_id == iid))
    is_bond = asset == "bond" or subtype in {OFZ_GOV, CORPORATE_BOND, MUNICIPAL_BOND}

    can_portfolio_value = False
    if asset == "equity" or subtype in {"equity_common", "equity_preferred", FUND}:
        can_portfolio_value = active and (has_candle or can_live_quote)
        if not can_portfolio_value:
            reasons["can_portfolio_value"] = "no_price_source"
    elif is_bond:
        can_portfolio_value = active and bond_term is not None and bond_term.nominal is not None
        if not can_portfolio_value:
            reasons["can_portfolio_value"] = "missing_bond_terms"
    else:
        reasons["can_portfolio_value"] = "unsupported_asset_class"

    issuer_mapped = (
        session.scalar(
            select(func.count())
            .select_from(SecurityIssuerMapping)
            .where(
                SecurityIssuerMapping.instrument_id == iid,
                SecurityIssuerMapping.issuer_id.is_not(None),
            )
        )
        or 0
    ) > 0
    can_fundamental = asset == "equity" and issuer_mapped
    if not can_fundamental:
        reasons["can_fundamental"] = "no_issuer_mapping_or_non_equity"

    can_fixed_income_analyze = is_bond and bond_term is not None
    if not can_fixed_income_analyze:
        reasons["can_fixed_income_analyze"] = "not_bond_or_missing_terms"

    lot_ok = False
    if asset == "equity":
        lots = resolve_equity_lot_sizes(session, [instrument], fetch_missing=False)
        lot_ok = lots.get(iid) is not None and lots[iid].lot_size is not None
    elif is_bond and bond_term is not None:
        lot_ok = bond_term.lot_size is not None and int(bond_term.lot_size) > 0

    can_rebalance = can_portfolio_value and lot_ok
    if not can_rebalance:
        reasons["can_rebalance"] = "missing_lot_or_valuation"

    cf_count = (
        session.scalar(
            select(func.count()).select_from(BondCashflow).where(BondCashflow.instrument_id == iid)
        )
        or 0
    )
    can_cashflow_project = is_bond and cf_count > 0
    if not can_cashflow_project:
        reasons["can_cashflow_project"] = "no_bond_cashflows"

    return InstrumentCapabilities(
        can_live_quote=can_live_quote,
        can_portfolio_value=can_portfolio_value,
        can_predict=can_predict,
        can_fundamental=can_fundamental,
        can_fixed_income_analyze=can_fixed_income_analyze,
        can_rebalance=can_rebalance,
        can_cashflow_project=can_cashflow_project,
        reasons=reasons,
    )


def coverage_matrix(capabilities: InstrumentCapabilities) -> dict[str, bool]:
    return {
        "live_quote": capabilities.can_live_quote,
        "portfolio_value": capabilities.can_portfolio_value,
        "predict": capabilities.can_predict,
        "fundamental": capabilities.can_fundamental,
        "fixed_income": capabilities.can_fixed_income_analyze,
        "rebalance": capabilities.can_rebalance,
        "cashflow": capabilities.can_cashflow_project,
    }
