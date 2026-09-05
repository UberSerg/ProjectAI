"""Domain vocabulary for Fundamental & Event Intelligence V1.

Pure constants, enums and records: no DB, no HTTP, no pandas. Every knowledge-bearing
record carries ``known_at`` — the date the information became available — separately
from its economic date (``period_end`` / ``record_date`` / ``effective_date``).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Any

FUNDAMENTALS_VERSION = "FUNDAMENTAL_EVENT_DATA_V1"
SOURCE_AUDIT_KIND = "FUNDAMENTAL_SOURCE_AUDIT_V1"

# Provider / source codes written into `source` columns.
SOURCE_MOEX_ISS = "MOEX_ISS"
SOURCE_MARKET_CORPORATE_ACTIONS = "MARKET_CORPORATE_ACTIONS"

# Feature set identities. Nothing is materialised into a shared feature table in V1;
# these codes name the in-memory contracts so a later stage can pin them.
FUNDAMENTAL_FEATURE_SET_CODE = "fundamental_daily"
FUNDAMENTAL_FEATURE_SET_VERSION = 1
EVENT_FEATURE_SET_CODE = "event_daily"
EVENT_FEATURE_SET_VERSION = 1

# A report older than this is still visible, but `has_recent_report` turns 0.
RECENT_REPORT_MAX_AGE_DAYS = 180
# Split history window used by the event feature contract.
SPLIT_LOOKBACK_DAYS = 365

# Research targets this data foundation is meant to eventually serve. Metadata only:
# no DatasetSpec is created, changed or pinned by this module.
TARGET_RESEARCH_SPECS: tuple[str, ...] = (
    "ABSOLUTE_RETURN_20D",
    "EXCESS_VS_CASH_20D",
    "TOP20_20D",
    "EXCESS_VS_IMOEX_20D",
)


class ReportingStandard(StrEnum):
    IFRS = "IFRS"
    RAS = "RAS"
    OTHER = "OTHER"


class PeriodType(StrEnum):
    Q1 = "Q1"
    Q2 = "Q2"
    Q3 = "Q3"
    Q4 = "Q4"
    H1 = "H1"
    H2 = "H2"
    NINE_MONTHS = "9M"
    FY = "FY"
    LTM = "LTM"
    OTHER = "OTHER"


class KnownAtPrecision(StrEnum):
    DATE = "DATE"
    TIMESTAMP = "TIMESTAMP"


class ReportStatus(StrEnum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    REJECTED = "REJECTED"


class NormalizationStatus(StrEnum):
    NORMALIZED = "NORMALIZED"
    SOURCE_ONLY = "SOURCE_ONLY"
    AMBIGUOUS = "AMBIGUOUS"
    UNSUPPORTED = "UNSUPPORTED"


class QualityStatus(StrEnum):
    OK = "OK"
    SUSPECT = "SUSPECT"
    INVALID = "INVALID"
    UNKNOWN = "UNKNOWN"


class MetricStatus(StrEnum):
    SUPPORTED = "SUPPORTED"
    AMBIGUOUS = "AMBIGUOUS"
    UNSUPPORTED = "UNSUPPORTED"


class MappingStatus(StrEnum):
    MAPPED = "MAPPED"
    AMBIGUOUS = "AMBIGUOUS"
    UNMAPPED = "UNMAPPED"


class DividendStatus(StrEnum):
    PROPOSED = "PROPOSED"
    RECOMMENDED = "RECOMMENDED"
    APPROVED = "APPROVED"
    PAID = "PAID"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"


class CorporateEventType(StrEnum):
    SPLIT = "SPLIT"
    REVERSE_SPLIT = "REVERSE_SPLIT"


class IngestionStatus(StrEnum):
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    NO_CHANGES = "NO_CHANGES"
    PARTIAL = "PARTIAL"
    DEFERRED = "DEFERRED"
    FAILED = "FAILED"


class DeferralReason(StrEnum):
    NO_PROVIDER_CONFIGURED = "NO_PROVIDER_CONFIGURED"
    SOURCE_REJECTED_BY_AUDIT = "SOURCE_REJECTED_BY_AUDIT"
    MISSING_KNOWN_AT = "MISSING_KNOWN_AT"
    UNMAPPED_ISSUER = "UNMAPPED_ISSUER"


class ReadinessStatus(StrEnum):
    READY = "READY"
    PARTIAL = "PARTIAL"
    NOT_READY = "NOT_READY"


class SourceVerdict(StrEnum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    DEFERRED = "DEFERRED"


@dataclass(frozen=True, slots=True)
class MetricDefinition:
    """One normalised metric. ``applies_to_banks`` is deliberately conservative."""

    code: str
    title_ru: str
    title_en: str
    description: str
    applies_to_banks: bool
    status: MetricStatus


# Conservative seed, mirrored by migration 20260905_0018. EBITDA is AMBIGUOUS because
# it is not an IFRS/RAS line item and its definition varies by issuer.
METRIC_REGISTRY_SEED: tuple[MetricDefinition, ...] = (
    MetricDefinition(
        "REVENUE",
        "Выручка",
        "Revenue",
        "Выручка / процентные и прочие доходы отчётного периода.",
        applies_to_banks=False,
        status=MetricStatus.SUPPORTED,
    ),
    MetricDefinition(
        "OPERATING_INCOME",
        "Операционная прибыль",
        "Operating income",
        "Операционная прибыль. У банков операционного результата в этом смысле нет.",
        applies_to_banks=False,
        status=MetricStatus.SUPPORTED,
    ),
    MetricDefinition(
        "NET_INCOME",
        "Чистая прибыль",
        "Net income",
        "Чистая прибыль периода, относящаяся к акционерам.",
        applies_to_banks=True,
        status=MetricStatus.SUPPORTED,
    ),
    MetricDefinition(
        "TOTAL_ASSETS",
        "Итого активы",
        "Total assets",
        "Итого активы на конец периода.",
        applies_to_banks=True,
        status=MetricStatus.SUPPORTED,
    ),
    MetricDefinition(
        "TOTAL_EQUITY",
        "Итого капитал",
        "Total equity",
        "Итого капитал на конец периода.",
        applies_to_banks=True,
        status=MetricStatus.SUPPORTED,
    ),
    MetricDefinition(
        "TOTAL_DEBT",
        "Итого долг",
        "Total debt",
        "Процентный долг. Для банков привлечённые средства не являются долгом в этом смысле.",
        applies_to_banks=False,
        status=MetricStatus.SUPPORTED,
    ),
    MetricDefinition(
        "CASH_AND_EQUIVALENTS",
        "Денежные средства и эквиваленты",
        "Cash and equivalents",
        "Денежные средства и эквиваленты на конец периода.",
        applies_to_banks=True,
        status=MetricStatus.SUPPORTED,
    ),
    MetricDefinition(
        "OPERATING_CASH_FLOW",
        "Операционный денежный поток",
        "Operating cash flow",
        "Чистый денежный поток от операционной деятельности.",
        applies_to_banks=True,
        status=MetricStatus.SUPPORTED,
    ),
    MetricDefinition(
        "EBITDA",
        "EBITDA",
        "EBITDA",
        "Не является строкой отчётности: определение зависит от эмитента. "
        "Использовать только как раскрытый эмитентом показатель.",
        applies_to_banks=False,
        status=MetricStatus.AMBIGUOUS,
    ),
)

METRIC_CODES: frozenset[str] = frozenset(m.code for m in METRIC_REGISTRY_SEED)


@dataclass(frozen=True, slots=True)
class IssuerRef:
    """Identity of a legal issuer. ``issuer_id`` is None before persistence."""

    title: str
    issuer_id: int | None = None
    moex_emitent_id: int | None = None
    inn: str | None = None
    okpo: str | None = None
    title_en: str | None = None


@dataclass(frozen=True, slots=True)
class IssuerIdentity:
    """One provider observation for a single SECID. Never a guess: status is explicit."""

    secid: str
    mapping_status: MappingStatus
    moex_emitent_id: int | None = None
    title: str | None = None
    title_en: str | None = None
    inn: str | None = None
    okpo: str | None = None
    isin: str | None = None
    security_type: str | None = None
    reason: str | None = None
    raw: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ReportRef:
    """A financial report as knowledge: visible only when ``known_at <= as_of``."""

    issuer_id: int
    reporting_standard: ReportingStandard
    period_type: PeriodType
    period_end: date
    known_at: date
    report_id: int | None = None
    period_start: date | None = None
    report_version: int = 1
    is_restatement: bool = False
    source: str = SOURCE_MOEX_ISS
    status: ReportStatus = ReportStatus.ACTIVE
    currency: str | None = None
    unit_scale: str | None = None
    published_at_known: bool = False

    @property
    def period_key(self) -> tuple[str, str, date]:
        return (str(self.reporting_standard), str(self.period_type), self.period_end)


@dataclass(frozen=True, slots=True)
class FactRef:
    metric_code: str
    value: float | None
    normalization_status: NormalizationStatus = NormalizationStatus.SOURCE_ONLY
    quality_status: QualityStatus = QualityStatus.UNKNOWN
    currency: str | None = None
    unit_scale: str | None = None
    source_metric_name: str = ""
    report_id: int | None = None


@dataclass(frozen=True, slots=True)
class DividendEventRef:
    """One dividend disclosure version. Later versions supersede earlier ones."""

    known_at: date
    status: DividendStatus
    source: str
    event_id: int | None = None
    issuer_id: int | None = None
    instrument_id: int | None = None
    announcement_date: date | None = None
    board_recommendation_date: date | None = None
    shareholder_approval_date: date | None = None
    record_date: date | None = None
    ex_date: date | None = None
    payment_date: date | None = None
    amount_per_share: float | None = None
    currency: str | None = None
    version: int = 1
    supersedes_id: int | None = None

    @property
    def series_key(self) -> tuple[int, int, date | None]:
        """Groups the versions of one payout. Keyed on the economic record/ex date."""
        anchor = self.record_date or self.ex_date or self.payment_date
        return (self.issuer_id or 0, self.instrument_id or 0, anchor)


@dataclass(frozen=True, slots=True)
class DividendState:
    """Point-in-time answer for one payout series. ``is_known`` is False when nothing
    was disclosed on or before ``as_of``."""

    as_of: date
    is_known: bool
    status: DividendStatus = DividendStatus.UNKNOWN
    event_id: int | None = None
    known_at: date | None = None
    version: int | None = None
    amount_per_share: float | None = None
    currency: str | None = None
    announcement_date: date | None = None
    record_date: date | None = None
    ex_date: date | None = None
    payment_date: date | None = None

    @property
    def record_date_is_future(self) -> bool:
        return self.record_date is not None and self.record_date > self.as_of


@dataclass(frozen=True, slots=True)
class CorporateEventRef:
    event_type: CorporateEventType
    event_date: date
    known_at: date
    source: str
    event_id: int | None = None
    issuer_id: int | None = None
    instrument_id: int | None = None
    effective_date: date | None = None
    external_id: str | None = None


@dataclass(frozen=True, slots=True)
class PitQuery:
    """Decision-time coordinates. Only information with ``known_at <= as_of`` is allowed."""

    as_of: date
    issuer_id: int | None = None
    instrument_id: int | None = None
    reporting_standard: ReportingStandard | None = None


@dataclass(frozen=True, slots=True)
class FundamentalsState:
    """Everything known about an issuer's reporting at ``as_of``."""

    as_of: date
    issuer_id: int | None
    latest_report: ReportRef | None = None
    facts: tuple[FactRef, ...] = ()
    visible_reports: int = 0

    @property
    def has_report(self) -> bool:
        return self.latest_report is not None
