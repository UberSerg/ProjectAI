"""Replaceable provider contracts for fundamentals and events.

``FnsGirBoProvider`` implements industrial RAS reports from public FNS GIR BO.
``IssuerIrXlsxDividendProvider`` supplies a bounded IR XLSX dividend path
(MGNT V1, ``PARTIAL_RESEARCH_PRODUCTION_BOUNDED``). Universe-wide dividends
remain deferred (MOEX ISS rejected; e-disclosure 403).
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Protocol, runtime_checkable

from app.modules.fundamentals.domain.types import (
    DividendEventRef,
    FactRef,
    IssuerIdentity,
    ReportRef,
)


@runtime_checkable
class IssuerIdentityProvider(Protocol):
    """Resolves a market SECID to a legal issuer. Must never guess."""

    source: str

    def fetch_issuer(self, secid: str) -> IssuerIdentity: ...


@runtime_checkable
class FundamentalReportProvider(Protocol):
    """Supplies financial reports with a provable ``known_at``.

    A report whose availability date is unknown must be returned with
    ``known_at`` unset so the caller can reject it instead of backdating it.
    """

    source: str

    def fetch_reports(
        self, issuer: int, *, date_from: date | None = None, date_to: date | None = None
    ) -> Sequence[tuple[ReportRef, Sequence[FactRef]]]: ...


@runtime_checkable
class DividendProvider(Protocol):
    """Supplies dividend disclosures with a provable ``known_at``."""

    source: str

    def fetch_dividends(
        self, issuer: int, *, date_from: date | None = None, date_to: date | None = None
    ) -> Sequence[DividendEventRef]: ...
