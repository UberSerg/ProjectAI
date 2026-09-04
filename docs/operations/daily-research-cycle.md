# Daily Research Cycle V0

## Purpose

Prospective end-to-end research loop:

Market / CBR / CA → Analytics V2 → Technical V2 → Relations V2 (bounded) →
Forward Signal V0 → Shadow advance → Forward Outcome Evaluator → finalize.

Does **not** backfill Forward or Shadow history. Does **not** retrain models.
Does **not** use dividends / total return. Does **not** place broker orders.

## Canonical CLI

```bash
python -m app.modules.research_cycle.cli_daily_research run
python -m app.modules.research_cycle.cli_daily_research status
```

Celery task: `projectai.daily_research_cycle`

## Step order

1. SOURCE_DISCOVERY
2. MARKET_UPDATE
3. CBR_UPDATE
4. CORPORATE_ACTION_UPDATE
5. ANALYTICS_V2 (`basic_daily` v2 pin)
6. TECHNICAL_V2 (`rules` v2 pin)
7. RELATIONS_V2 (latest only; `SKIPPED_NOT_DUE` when snapshot age ≤ 8 calendar days)
8. FORWARD_SIGNAL (at most one new immutable batch for latest eligible as_of)
9. SHADOW_ADVANCE
10. FORWARD_OUTCOME_EVALUATION (20 future trading observations)
11. FINALIZE

## Status meanings

| Status | Meaning |
|---|---|
| `NO_CHANGES` | Second run / no new market data; no duplicates created |
| `WAITING_FOR_MARKET` | Downstream current enough; waiting for a newer complete market day |
| `LAGGING` | Raw market ahead of Analytics/Technical/Forward |
| `BLOCKED` / `ALREADY_RUNNING` | Lock held or required step failed |
| `SKIPPED_NOT_DUE` | Relations latest snapshot still acceptable for Forward max age |

## Schedule

Disabled by default.

```env
DAILY_RESEARCH_CYCLE_ENABLED=false
DAILY_RESEARCH_CYCLE_HOUR=18
DAILY_RESEARCH_CYCLE_MINUTE=30
DAILY_RESEARCH_CYCLE_TIMEZONE=UTC
```

Enable only after several successful manual cycles.

## Forward outcomes

Predictions are immutable facts. Outcomes are separate evaluation rows.
A prediction matures only after **20 future trading observations** (not calendar days).
Mechanical SPLIT / REVERSE_SPLIT use Dataset PIT V2 / H4A semantics.
No dividend adjustment.

## Shadow chronology

Old pending orders may fill at a later eligible OPEN.
A new order created in the same cycle after day D is ingested must **not** fill at D OPEN.
