# ADR 0008 — Lot-aware Shadow portfolio and daily readiness

## Status

Accepted (Shadow Portfolio Realism V2)

## Context

Shadow V1 proved next-session OPEN execution and live marks, but sized orders as fractional shares. Live acceptance produced non-lot quantities and avoidable `INSUFFICIENT_CASH` when the sum of ideal notionals exceeded cash after fees. EOD automation existed as a clocked Daily Research Cycle without an explicit next-session readiness model.

## Decision

1. **Integer lots only** for new Shadow Realism V2 portfolios; MOEX LOTSIZE required; never invent `lot_size=1`.
2. **Cash-safe whole order plan** validated before persisting orders (sells then buys, fees included).
3. **New experiment** `SHADOW_PORTFOLIO_REALISM_V2` with the same Prediction/Policy as operational V1; V1 history remains immutable.
4. **EOD decides; intraday only executes and marks** — official session OPEN for fills, LAST for live NAV.
5. **Readiness before next session** is a first-class operational status (`READY_*` / blocker codes); missed readiness is not repaired with backdated fills.
6. Historical Simulator economics stay fractional until a separate Simulator Realism task.

## Consequences

- Candidate preview and Shadow share lot math primitives but not snapshot vs dynamic semantics.
- Research comparability: V1 fractional Shadow ≠ V2 lot-aware Shadow ≠ default Historical Simulator.
- Ops UI must surface readiness, skip reasons, lots×lot_size, and cash remainder.
