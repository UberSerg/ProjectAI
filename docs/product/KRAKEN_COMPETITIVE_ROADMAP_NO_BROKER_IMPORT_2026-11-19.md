# KRAKEN — Competitive Product Roadmap (Snowball parity without brokerage import)

**Owner decision:** 2026-11-19. **Status:** proposed phased development strategy; no implementation or PR merge authorization implied by this document alone.

## Objective and explicit exclusions

Bring KRAKEN's **everyday investor UX and core portfolio functionality** at least to the practical level of Snowball Income for the selected target user segment, while differentiating through Company Intelligence, Daily Decision, Decision Memory, and the Shadow evidence/decision/execution feedback loop.

**No integration to broker accounts, broker reports, holdings/operation synchronization via brokerage API, automated trade submission, or brokerage CSV-report import.** Use fast **manual** portfolio accounting. An isolated read-only market-data provider is a different capability and may be evaluated later, with no access to account information or trading. Data export/backup of KRAKEN's own records is allowed; it must not become broker import by another name.

Target market for first competitive release: Russian equities/bonds/funds with existing evidence-backed prices and corporate actions. Global markets, crypto, banks/deposits/property, public sharing/community are later separate decisions, not prerequisites for a focused first competitive release. Product parity is to be tested by user journeys, not claimed by similar feature labels.

## Source-grounded comparative baseline (read on 2026-11-19)

Snowball Income's [site](https://snowball-income.com/) and [pricing/features matrix](https://snowball-income.com/pricing) advertise manual holdings, transactions, dividend/coupon calendar, fees, taxes, complete P&L, annualized XIRR, benchmark comparisons, allocation and rebalancing, multiple portfolios, performance breakdown, event calendar, and custom assets, among others. Their [overview](https://ru.help.snowball-income.com/) describes investment goals, performance and payments. UI parity still requires actual browser evaluation; marketing claims are not independently certified.

KRAKEN source-level starting facts: personal portfolio screen currently has holdings/history/decision/analysis/payments/compare/rebalance tabs; Portfolio Hub has full/partial valuation distinctions; Dashboard has portfolio NAV/cash/P&L and quality states; Market MOEX, Fundamentals/FNS/issuer sources, Shadow and Decision Journal exist. This does not establish complete parity or polished visual acceptance.

## Prioritized development waves

### Gate 0 — Product reliability and usable investor baseline (P0)
- Browser audit of all primary investor screens on 1440, 390, 320 px in light/dark; resolve stale Docker frontend/worktree mounting and verify actual served source before comparing screenshots.
- One coherent navigation and five primary destinations: Overview, Portfolio, Income, Decisions, Market. OWNER advanced tools behind secondary navigation.
- Product design system and consistent terms, currency/percent/date formatting, status chips, empty/loading/partial/unknown states; avoid showing missing as zero.
- Clean DEMO portfolio scenario with manual cash deposit, buy, sell, dividend and verification that recorded transactions survive refresh/restart.
- Finish PR B Personal Operations Integrity before treating manually entered units/fees/dates as a trusted finance ledger.

**Acceptance:** an unfamiliar user can create a portfolio, manually enter transaction, see holdings and understand valuation quality without technical IDs; no hidden source/worktree mismatch; keyboard and mobile accessible.

### Gate 1 — Trustworthy manual finance accounting (P0; foundational)
- Fast manual BUY, SELL, cash deposits/withdrawals, dividends, coupons, commissions, tax withheld, amortization and corporate-action adjustments where legally sourced. Quantity in units vs lots explicitly visible; repeat transaction templates and minimal taps.
- Lot-aware cost basis for partial sells, splits, commissions and transaction date; add idempotency and editing/correction audit history; never silently rewrite ledger facts.
- Defined metrics: cost basis, market value, realized P&L, unrealized P&L, income, fees, taxes, cashflow-adjusted money-weighted XIRR where computable; time-weighted return only with reliable, timed valuations; distinguish these clearly.
- Historical series and daily quality state, currency conversion with PIT FX rates when in scope; avoid mixing cash flows with investment returns.
- Controlled CSV **export** and backup/restore of KRAKEN's own data only; no broker import.

**Acceptance:** reference finance fixtures with deposit→buy→dividend→partial sell→commission/tax→remaining position and edge cases; mathematically reconciled totals; date/quote/as-of provenance; unavailable when cost basis/prices incomplete.

### Gate 2 — Income product: dividends, coupons, cashflow calendar (P1)
- Human-friendly upcoming / declared / estimated / received payments calendar, distinct event types and ex/record/pay dates; no imaginary dividend events.
- Full dividend and bond coupon accounting, net after withholding, expected vs actual, dividend yield on cost and market price, 30d/90d/12m horizons and monthly passive-income summary.
- Clear provider coverage map; retain authorized issuer disclosures, FNS, MOEX and optional read-only T-Invest market/asset enrichment after source/legal review. No account connection.
- Taxes and currency conversion for income only as supported by correct domain model and verified histories.

**Acceptance:** real position eligibility and payment logic; missing ex-date/amount tagged unknown; issuer events verified and read-only source provenance preserved.

### Gate 3 — Portfolio intelligence and comparative analytics (P1)
- One coherent analytics surface: equity/bonds/cash, sector/issuer concentration, geographic/currency exposure when supported, top contributors, historical NAV and flows, investment P&L, realized/unrealized and income decomposition.
- Comparable portfolio-vs-benchmark time series including dividends/total-return treatment where the benchmark supports it, aligned trading dates/FX, explain missing periods.
- Target weights, cash-aware buy-only or buy/sell rebalance proposals, commissions/lots, risk budget, instrument filtering. Proposed orders stay proposals; do not execute.
- What-if contribution model, monthly savings and capital/income goals with assumptions made explicit; favorites/watchlists and research note links.
- Multi-portfolio consolidated view without mistakenly treating Shadow or model book as personal holdings.

**Acceptance:** three realistic investor journeys validated end-to-end, no silent cashflow bias in return charts, no unverified recommendation passed as executed trade.

### Gate 4 — Kraken differentiation (P1/P2 after accounting foundation)
- Daily Decision in plain Russian: what to do, why, what changed, risks and uncertainty; clear user confirm/capture as memory without broker trading.
- Human-first Decision Journal: signal date versus decision date versus fill date, BUY/SELL/CANCELLED and linked execution history, no fabricated rationale for old traces.
- **Decision-attributed P&L** only after rigorously tested lot/cohort allocation across multiple buys and sales and PIT as-of prices; show realized/unrealized separately; no invented number for missing price or absent matching; never derive from daily NAV delta.
- Score recommendations and Shadow against baselines in honest counterfactual experiments, with time alignment, transaction costs and risk; decision confidence is not guaranteed return.
- Company Intelligence combines fundamentals/quality/sources with explainable risk. Advanced Research remains OWNER-level functionality.

**Acceptance:** open a dated decision and trace reasoning → recommendation → recorded order → actual fill → attributable performance with full provenance; if any link missing the UI explicitly shows its limitation.

### Gate 5 — Mature everyday product polish and extended scope (P2)
- Responsive UI and optional PWA/offline read-only snapshots, fast search, preserved filters, performance budgets, guided first-run, contextual financial help and onboarding.
- Notifications for payment events, stale valuations, allocation drift, decision changes only with user consent and rate limiting; no invented certainty.
- Custom assets (deposits/property/manual alternative assets), more currencies and markets, public shareable read-only views/community **only if** target investors actually request them; separate financial methodology for illiquid marks.
- Accessible charts, exports, backup/restore, account-level trust and data protection review.

**Acceptance:** task-based usability study versus Snowball demos for manual investor workflows, WCAG 2.2 AA target, no serious mobile overflow, comprehensive real-browser evidence.

## Delivery architecture and team lanes

- **Finance integrity:** ledger, cost basis, XIRR/returns, dividend and decision P&L backend. This is sequential, not a cosmetic swarm task.
- **Investor product UX:** Dashboard, Portfolio, payments, analytics, UI primitives, mobile. Work in non-overlapping branches/worktrees.
- **Market/fundamental evidence:** legal provenance, coverage, PIT dating and event sources, without account API.
- **Verification:** reference financial fixtures, safe DEMO-only E2E, comparison browser screenshots and scenario usability.

Order: Gate 0 + Gate 1 prerequisites first; calendar and visual analytics can run partly in parallel on agreed contracts; Decision P&L after cost-basis allocation. Do not block an entire UX sprint on new intelligence models. Separate backend financial PRs from visual PRs.

## Product parity acceptance scorecard

1. Investor adds a personal portfolio and transaction without technical instruction.
2. NAV/cash/valued assets never claims a full price when partial.
3. Deposits and withdrawals do not count as profit; realized vs unrealized and annualized returns are trustworthy.
4. Calendar shows evidence-graded dividends/coupons and actual vs expected cash flows.
5. Comparison against benchmark is time- and currency-aligned.
6. Rebalance plan respects cash, fees, lot sizes and never auto-trades.
7. Daily Decision / Shadow / Journal distinguish advice, real/virtual records and counterfactuals.
8. Same core flows work on narrow phone screens with accessible keyboard navigation.
9. No broker import is present in UI, backlog or API integration.
10. Tests are risk-based: targeted UI/finance tests during work, full relevant CI at integration/merge gate, not on each documentation/cosmetic edit.

## Source references

- https://snowball-income.com/
- https://snowball-income.com/pricing
- https://ru.help.snowball-income.com/
- https://help.snowball-income.com/xirr/
- KRAKEN code at owner-verified main 2026-11-19, plus `docs/product/mvp-investor-journey-v1.md` and `docs/ui/KRAKEN_UX_SWARM_AUDIT_2026-10-29.md`.

This document is a plan and prioritization, not a claim that all features exist already or any future branch has owner merge approval.
