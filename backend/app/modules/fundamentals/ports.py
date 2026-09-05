"""Replaceable provider contracts for fundamentals and events.

No implementation exists today for reports or dividends: the live source audit rejected
every free candidate. The protocols exist so a future adapter plugs in without touching
the PIT rules, and so the ingest adapters can honestly report DEFERRED meanwhile.
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
