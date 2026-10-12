"""Bank-specific metric vocabulary (candidate codes only).

These codes are *not* industrial RAS ratios. Values may be populated only when
a bank-capable provider supplies them with provenance. Missing ≠ zero.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BankMetricDefinition:
    code: str
    title_en: str
    description: str
    # PARTIAL only for metrics a free programmatic source can actually supply.
    availability: str  # PARTIAL | NOT_AVAILABLE


# Industrial FNS metric codes that must never be treated as bank semantics.
INDUSTRIAL_RATIO_CODES: frozenset[str] = frozenset(
    {
        "REVENUE",
        "OPERATING_INCOME",
        "TOTAL_DEBT",
        "EBITDA",
        "OPERATING_CASH_FLOW",
    }
)

BANK_METRIC_DEFINITIONS: tuple[BankMetricDefinition, ...] = (
    BankMetricDefinition(
        "NET_INTEREST_INCOME",
        "Net interest income",
        "Interest income minus interest expense for the reporting period.",
        "NOT_AVAILABLE",
    ),
    BankMetricDefinition(
        "NET_FEE_INCOME",
        "Net fee and commission income",
        "Fee and commission income net of related expenses.",
        "NOT_AVAILABLE",
    ),
    BankMetricDefinition(
        "NET_PROFIT",
        "Net profit",
        "RAS form 0409102 symbol 61101, profit after tax, thousand RUB. Not IFRS.",
        "PARTIAL",
    ),
    BankMetricDefinition(
        "EQUITY",
        "Equity / own funds",
        "Form 0409123 line 000 regulatory own funds (capital), thousand RUB. Not IFRS equity.",
        "PARTIAL",
    ),
    BankMetricDefinition(
        "TOTAL_ASSETS",
        "Total assets",
        "Balance-sheet total assets. CBR form 101 SOAP data methods did not return a unique total.",
        "NOT_AVAILABLE",
    ),
    BankMetricDefinition(
        "LOAN_BOOK",
        "Loan book",
        "Gross or net loans to customers, depending on source definition.",
        "NOT_AVAILABLE",
    ),
    BankMetricDefinition(
        "DEPOSITS",
        "Customer deposits",
        "Customer deposit liabilities.",
        "NOT_AVAILABLE",
    ),
    BankMetricDefinition(
        "NIM",
        "Net interest margin",
        "Net interest income / interest-earning assets (definition source-bound).",
        "NOT_AVAILABLE",
    ),
    BankMetricDefinition(
        "ROE",
        "Return on equity",
        "Net profit / average equity (definition source-bound).",
        "NOT_AVAILABLE",
    ),
    BankMetricDefinition(
        "COST_INCOME",
        "Cost / income",
        "Operating expenses / operating income (bank definition).",
        "NOT_AVAILABLE",
    ),
    BankMetricDefinition(
        "CAPITAL_ADEQUACY",
        "Capital adequacy",
        "Form 0409135 section 3 ratio N1.0, percent. Not an industrial RAS ratio.",
        "PARTIAL",
    ),
    BankMetricDefinition(
        "NPL_RATIO",
        "Asset quality / NPL",
        "Non-performing loans ratio when disclosed with stable definition.",
        "NOT_AVAILABLE",
    ),
)

BANK_METRIC_CODES: tuple[str, ...] = tuple(m.code for m in BANK_METRIC_DEFINITIONS)


def is_industrial_ratio_code(code: str) -> bool:
    return code.strip().upper() in INDUSTRIAL_RATIO_CODES
