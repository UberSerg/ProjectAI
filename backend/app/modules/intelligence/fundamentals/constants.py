"""Industrial fundamental snapshot vocabulary (Intelligence Stack V1)."""

from __future__ import annotations

PROVIDER = "FNS_GIR_BO"
SNAPSHOT_BUILDER = "IndustrialFundamentalProfileV1"

ISSUER_KIND_INDUSTRIAL = "INDUSTRIAL"
ISSUER_KIND_BANK_FI = "BANK_FI"
ISSUER_KIND_UNKNOWN = "UNKNOWN"

STATUS_READY = "READY"
STATUS_PARTIAL = "PARTIAL"
STATUS_NOT_AVAILABLE = "NOT_AVAILABLE"
STATUS_UNKNOWN = "UNKNOWN"

# Source fact codes expected from FNS RAS industrial normalisation.
FACT_CODES: tuple[str, ...] = (
    "REVENUE",
    "OPERATING_INCOME",
    "NET_INCOME",
    "TOTAL_ASSETS",
    "TOTAL_EQUITY",
    "TOTAL_DEBT",
    "CASH_AND_EQUIVALENTS",
    "OPERATING_CASH_FLOW",
    "CURRENT_ASSETS",
    "CURRENT_LIABILITIES",
)

# Derived keys that may be listed in missing_metrics when not computable.
DERIVED_CODES: tuple[str, ...] = (
    "net_margin",
    "operating_margin",
    "roa",
    "roe",
    "leverage_assets_to_equity",
    "equity_to_assets",
    "cash_to_assets",
    "debt_to_equity",
    "debt_to_assets",
    "total_liabilities_proxy",
    "current_ratio",
    "asset_turnover",
    "accrual_proxy",
    "revenue_yoy",
    "net_income_yoy",
    "net_margin_delta",
    "roe_delta",
)

DEBT_SEMANTICS = "RAS_BORROWINGS_1410_PLUS_1510"
LIABILITIES_PROXY_SEMANTICS = "TOTAL_ASSETS_MINUS_TOTAL_EQUITY"
ACCRUAL_PROXY_SEMANTICS = "NET_INCOME_MINUS_OCF_OVER_TOTAL_ASSETS"

# Minimum facts for READY (industrial path).
READY_REQUIRED_FACTS: frozenset[str] = frozenset(
    {"REVENUE", "NET_INCOME", "TOTAL_ASSETS", "TOTAL_EQUITY"}
)

RECENT_REPORT_MAX_AGE_DAYS = 180

LIMITATION_BANK_FI = (
    "BANK_FI industrial RAS ratios unsupported; bank path owned by Agent C "
    "(intelligence/banks)"
)
LIMITATION_CURRENT_LINES = (
    "CURRENT_ASSETS/CURRENT_LIABILITIES not in FNS RAS V1 normalised metric set; "
    "current_ratio UNKNOWN until additive line mapping (RAS 1200/1500)"
)
LIMITATION_DEBT_PROXY = (
    "TOTAL_DEBT is RAS borrowings proxy (1410+1510), not full interest-bearing debt"
)
LIMITATION_LIABILITIES_PROXY = (
    "total_liabilities_proxy uses TOTAL_ASSETS − TOTAL_EQUITY; not a separate RAS line"
)
