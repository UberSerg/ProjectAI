# ADR 0013: Credit separate from valuation and strategy eligibility

## Status

Accepted — 2026-09-08

## Context

Accounting support (can we price / project cashflows) is independent of credit quality.
Strategy eligibility (`research_fi_v1`, Candidate / Opportunity) must not grow when catalog
enrichment or credit tables expand.

## Decision

1. **Credit** is its own domain (`investment.credit_*`, `CreditRatingProvider`).
2. **Valuation / FI enrichment** may succeed while credit remains `SOURCE_NOT_READY`.
3. **Strategy universe** (`research_fi_v1`) stays pinned; credit/catalog coverage ≠ Candidate membership.
4. OFZ uses `GOVERNMENT_RUSSIAN_FEDERAL` — not a fabricated CRA rating and not “credit unknown corporate”.
5. Portfolio credit section is advisory; no auto execution from ratings.

## Consequences

- InstrumentCapabilities may expose `can_issuer_credit` / `can_issue_credit` from stored status only.
- Investment eligibility still requires explicit CURRENT rating for silent real-portfolio promotion.
- Live rating ingest waits on commercial access — structure ships first.
