# Shadow Portfolio Realism V3 — Sell Economics

## Purpose

New forward Shadow experiment that keeps lot-aware V2 execution realism and adds an
**economically justified sell/review gate** plus bounded **candidate decision traces**.

V2 history (`SHADOW_PORTFOLIO_REALISM_V2`) stays frozen and untouched.

## Experiment identity

| | Value |
|--|--|
| Experiment group | `SHADOW_PORTFOLIO_REALISM_V3` |
| Portfolio A | `SHADOW_HYSTERESIS_V3` (baseline risk) |
| Portfolio B | `SHADOW_HYSTERESIS_DD_V3` (Drawdown Guard) |
| Execution version | `LOT_AWARE_SELL_ECONOMICS_V3` |
| Fee profile | `SBER_INVESTMENT` (builtin СберИнвестиции / Инвестиционный) |
| `min_net_rotation_edge_bps` | `0` (explicit, tunable) |

Init:

```bash
python -m app.modules.shadow.cli init --group realism-v3
# or POST /api/v1/shadow/init?group=realism-v3
```

Daily Research Cycle advances V1 + V2 + V3 operational groups.

## Core principle

Rank hysteresis exit-band breach is a **REVIEW TRIGGER**, not an automatic SELL.

Structured actions:

- `HOLD` — still selected by policy
- `REVIEW_HOLD` — reviewed; switch not justified after costs
- `ROTATE` — net expected edge covers sell fee + buy fee + sell/buy slippage + margin
- `EXIT_TO_CASH` — explicit cash exit reason
- `RISK_REDUCE` / `RISK_EXIT` — risk forced (no replacement required)
- `DATA_HOLD` — cannot compare (non-`EXPECTED_RETURN`, stale, missing fee/price)

## Rotation rule

Only when prediction semantics are comparable `EXPECTED_RETURN`:

```text
expected_B - expected_A
  > sell_fee_A/notional + buy_fee_B/notional
    + 2 * slippage_bps/10000
    + min_net_rotation_edge_bps/10000
```

- Broker fee from portfolio-domain `FeeEngine` (`sber_investment_builtin_rules` for this experiment).
- Slippage is **separate** from broker fee (Shadow `slippage_bps`).
- Do not invent economic % from ranks.

## Target construction

Sell gate runs **after** policy/risk and **before** the lot-aware planner.

- Retained names remain in final targets (planner cannot secretly sell them).
- Retained A capital cannot fund B buys; only free capacity / approved ROTATE proceeds.
- ROTATE: sell proceeds (after fees) may fund buy; long-only; no capital creation; no short.
- Planner remains the existing lot-aware `build_lot_order_plan`.

## Candidate traces

`ShadowDecision.metadata_["candidate_traces"]` stores bounded structured facts
(instrument, ranks, fees, net edge, reason/limitation codes) — **no chain-of-thought**.

## V2 vs V3

| | V2 | V3 |
|--|--|--|
| Lots | yes | yes |
| Exit-band drop → SELL | yes (planner) | no (review gate) |
| FeeProfile / FeeEngine | legacy `commission_bps` | `SBER_INVESTMENT` v1 via FeeEngine for gate + lot-plan + fill (not flat 30 bps) |
| Candidate traces | no | yes |

Instrument-specific FeeEngine overrides (e.g. SBFR temporary zero) apply in the **sell gate**;
lot-plan/fills use the flat Sber 0.3% `commission_bps` until per-fill FeeEngine wiring.

Do not compare V2 vs V3 NAV without noting the execution-policy change.
