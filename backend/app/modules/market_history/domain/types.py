"""Domain vocabulary for External Deep History V0.

Pure constants and enums: no DB, no HTTP, no pandas.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum

SOURCE_CODE = "EXTERNAL_30Y_CSV_V0"
PARSER_VERSION = "external_csv_v0"
AUDIT_REPORT_KIND = "EXTERNAL_DEEP_HISTORY_AUDIT_V0"

# Canonical MOEX observation coordinates used for reconciliation only.
MOEX_CANDLE_SOURCE = "MOEX"
MOEX_CANDLE_TIMEFRAME = "1d"

# Only OHLCV facts are staged. The source file also carries ~79 TA-Lib indicator
# columns; derived indicators are never persisted as source facts.
CSV_PRICE_COLUMNS = ("open", "high", "low", "close")
CSV_USECOLS = ("open", "close", "high", "low", "value", "volume", "begin", "ticker")


class SourceStatus(StrEnum):
    REGISTERED = "REGISTERED"
    AUDITED = "AUDITED"
    INGESTED = "INGESTED"
    RECONCILED = "RECONCILED"
    CURATED = "CURATED"
    FAILED = "FAILED"


class RunType(StrEnum):
    AUDIT = "AUDIT"
    RECONCILE = "RECONCILE"
    INGEST = "INGEST"
    CURATE = "CURATE"


class RunStatus(StrEnum):
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    NO_CHANGES = "NO_CHANGES"


class MatchStatus(StrEnum):
    EXACT_CURRENT_MATCH = "EXACT_CURRENT_MATCH"
    UNKNOWN_HISTORICAL_SYMBOL = "UNKNOWN_HISTORICAL_SYMBOL"
    INDEX_OR_NON_EQUITY = "INDEX_OR_NON_EQUITY"
    AMBIGUOUS = "AMBIGUOUS"
    POSSIBLE_ALIAS = "POSSIBLE_ALIAS"


class QualityStatus(StrEnum):
    OK = "OK"
    SPARSE = "SPARSE"
    DEGRADED = "DEGRADED"
    INVALID = "INVALID"
    UNKNOWN = "UNKNOWN"


class PriceSemantic(StrEnum):
    RAW_COMPATIBLE = "RAW_COMPATIBLE"
    LIKELY_ADJUSTED = "LIKELY_ADJUSTED"
    MIXED = "MIXED"
    INCOMPATIBLE = "INCOMPATIBLE"
    UNKNOWN = "UNKNOWN"


class ReconciliationStatus(StrEnum):
    MATCH = "MATCH"
    SMALL_DIFF = "SMALL_DIFF"
    LARGE_DIFF = "LARGE_DIFF"
    LIKELY_ADJUSTED = "LIKELY_ADJUSTED"
    UNKNOWN = "UNKNOWN"


class CaProbeVerdict(StrEnum):
    RAW = "RAW"
    PRE_ADJUSTED = "PRE_ADJUSTED"
    POST_ADJUSTED = "POST_ADJUSTED"
    UNKNOWN = "UNKNOWN"


class Eligibility(StrEnum):
    ELIGIBLE = "ELIGIBLE"
    EXCLUDED_REJECTED_ROW = "EXCLUDED_REJECTED_ROW"
    EXCLUDED_ADJUSTED_SEMANTIC = "EXCLUDED_ADJUSTED_SEMANTIC"
    EXCLUDED_UNKNOWN_SEMANTIC = "EXCLUDED_UNKNOWN_SEMANTIC"
    EXCLUDED_NON_EQUITY = "EXCLUDED_NON_EQUITY"
    EXCLUDED_QUALITY = "EXCLUDED_QUALITY"


class RejectReason(StrEnum):
    MISSING_FIELD = "MISSING_FIELD"
    NON_NUMERIC = "NON_NUMERIC"
    INVALID_DATE = "INVALID_DATE"
    NON_POSITIVE_PRICE = "NON_POSITIVE_PRICE"
    OHLC_INCONSISTENT = "OHLC_INCONSISTENT"
    NEGATIVE_VOLUME = "NEGATIVE_VOLUME"
    DUPLICATE_DATE = "DUPLICATE_DATE"


class FeatureStackStatus(StrEnum):
    READY = "READY"
    PARTIAL = "PARTIAL"
    INSUFFICIENT = "INSUFFICIENT"
    UNKNOWN = "UNKNOWN"


# Symbols that are indices / non-equity instruments in the MOEX namespace.
# Used for classification only; never auto-mapped into the operational universe.
INDEX_SYMBOLS: frozenset[str] = frozenset(
    {
        "IMOEX",
        "IMOEX2",
        "MOEXBC",
        "MOEXBMI",
        "MCFTR",
        "MCFTRR",
        "RTSI",
        "RTSSTD",
        "RGBI",
        "RGBITR",
        "RUCBITR",
        "RUABITR",
    }
)

# Quality thresholds for per-symbol classification.
MIN_OBSERVATIONS_OK = 250
MIN_OBSERVATIONS_SPARSE = 60
MAX_REJECT_RATE_OK = 0.01
MAX_REJECT_RATE_DEGRADED = 0.10

# A single-session close move beyond this is treated as a jump candidate.
JUMP_RELATIVE_THRESHOLD = 0.35
# Jump candidates whose ratio is close to a round factor look mechanical (split-like).
SPLIT_LIKE_FACTORS = (2.0, 3.0, 4.0, 5.0, 10.0, 100.0, 1000.0, 5000.0)
SPLIT_LIKE_TOLERANCE = 0.08

# Reconciliation thresholds (relative close difference).
RECON_MATCH_MAX_MEDIAN = 1e-6
RECON_SMALL_DIFF_MAX_MEDIAN = 5e-3
RECON_ADJUSTED_MIN_MEDIAN = 5e-2
RECON_MIN_OVERLAP_ROWS = 20

# Corporate-action probe tolerance on the observed close ratio.
CA_PROBE_TOLERANCE = 0.15
# Sessions averaged on each side of the event date.
CA_PROBE_WINDOW = 3

# Rolling windows the PIT feature stack needs before a symbol-year is usable.
FEATURE_WARMUP_OBSERVATIONS = 250
ML_READY_MIN_SYMBOLS = 20
ML_PARTIAL_MIN_SYMBOLS = 5


@dataclass(frozen=True, slots=True)
class CorporateActionProbe:
    """Known mechanical corporate action used to fingerprint price semantics.

    ``new_per_old`` is the number of new shares per old share, so the raw price
    divisor equals ``new_per_old`` (a 1 -> 10 split divides the raw price by 10,
    a 5000 -> 1 reverse split multiplies it by 5000).
    """

    symbol: str
    event_date: date
    new_per_old: float
    label: str

    @property
    def price_divisor(self) -> float:
        return self.new_per_old


KNOWN_CA_PROBES: tuple[CorporateActionProbe, ...] = (
    CorporateActionProbe("PLZL", date(2025, 3, 27), 10.0, "split 1:10"),
    CorporateActionProbe("TRNFP", date(2024, 2, 21), 100.0, "split 1:100"),
    CorporateActionProbe("GMKN", date(2024, 4, 8), 100.0, "split 1:100"),
    CorporateActionProbe("VTBR", date(2024, 7, 15), 1.0 / 5000.0, "reverse split 5000:1"),
    CorporateActionProbe("T", date(2026, 4, 17), 10.0, "split 1:10"),
)
