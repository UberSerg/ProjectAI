"""Symbol identity for external history: exact matching only.

Historical ticker renames (for example a delisted symbol later reused, or a
re-domiciliation that changed the listed code) are NOT inferred here. Guessing an
alias would silently rewrite instrument identity, so unmatched symbols stay
UNKNOWN_HISTORICAL_SYMBOL until a human curates them.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infrastructure.market.models import Instrument
from app.modules.market.universe import INSTRUMENTS
from app.modules.market_history.domain.types import (
    INDEX_SYMBOLS,
    MatchStatus,
)

EXACT_MATCH_CONFIDENCE = 1.0
NO_MATCH_CONFIDENCE = 0.0


@dataclass(frozen=True, slots=True)
class SymbolClassification:
    source_symbol: str
    match_status: MatchStatus
    mapping_confidence: float
    project_symbol: str | None


def current_cohort_symbols(session: Session | None = None) -> dict[str, str]:
    """Active MOEX cohort: symbol -> asset_class. Falls back to universe.py."""
    if session is not None:
        rows = session.execute(
            select(Instrument.symbol, Instrument.asset_class).where(
                Instrument.exchange == "MOEX", Instrument.is_active.is_(True)
            )
        ).all()
        if rows:
            return {str(symbol).upper(): str(asset_class) for symbol, asset_class in rows}
    return {definition.symbol.upper(): definition.asset_class for definition in INSTRUMENTS}


def classify_symbol(source_symbol: str, cohort: dict[str, str]) -> SymbolClassification:
    """Classify one external symbol against the current cohort.

    AMBIGUOUS and POSSIBLE_ALIAS exist in the vocabulary for curated overrides;
    this function never assigns them automatically.
    """
    symbol = source_symbol.strip().upper()
    asset_class = cohort.get(symbol)

    if symbol in INDEX_SYMBOLS or (asset_class is not None and asset_class != "equity"):
        return SymbolClassification(
            source_symbol=symbol,
            match_status=MatchStatus.INDEX_OR_NON_EQUITY,
            mapping_confidence=EXACT_MATCH_CONFIDENCE if asset_class else NO_MATCH_CONFIDENCE,
            project_symbol=symbol if asset_class else None,
        )

    if asset_class is not None:
        return SymbolClassification(
            source_symbol=symbol,
            match_status=MatchStatus.EXACT_CURRENT_MATCH,
            mapping_confidence=EXACT_MATCH_CONFIDENCE,
            project_symbol=symbol,
        )

    return SymbolClassification(
        source_symbol=symbol,
        match_status=MatchStatus.UNKNOWN_HISTORICAL_SYMBOL,
        mapping_confidence=NO_MATCH_CONFIDENCE,
        project_symbol=None,
    )


def classify_symbols(
    source_symbols: list[str], cohort: dict[str, str]
) -> dict[str, SymbolClassification]:
    return {symbol: classify_symbol(symbol, cohort) for symbol in source_symbols}
