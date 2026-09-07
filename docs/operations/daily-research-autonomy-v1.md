# Daily Research Autonomy V1

## Proven live incident (2026-09-07)

| Fact | Value |
|------|--------|
| Market open (assumed) | 10:00 MSK / 07:00 UTC |
| V2 activated_at | 13:38 UTC (16:38 MSK) — **after** open |
| Pending orders created_at | same as activation |
| min_execution_date | 2026-09-08 |
| Verdict | **Correct prospective guard** — do not use today's OPEN |

Separately:

| Watermark | Date |
|-----------|------|
| Complete EOD / raw market | 2026-09-04 |
| Analytics V2 | 2026-09-03 |
| Technical V2 | 2026-09-03 |
| Forward as_of | 2026-09-03 |
| `DAILY_RESEARCH_CYCLE_ENABLED` | **false** |
| Blocker | `WAITING_FOR_ANALYTICS` |

Root cause of analytics lag: automation off + no startup catch-up after market advanced to 2026-09-04 while last successful cycle finished covering 2026-09-03 Forward.

## Target lifecycle

```text
EOD T complete → Market → Analytics → Technical → Relations
→ Forward T → Shadow lot plan → READY_FOR_NEXT_SESSION
→ OPEN T+1 fill → intraday LAST marks
```

Mid-session experiment bootstrap:

```text
activated AFTER session open → orders for NEXT session only
```

## Configuration

```text
RESEARCH_LIVE_MODE=true   # enables daily cycle + EOD readiness retry + intraday
# or individually:
DAILY_RESEARCH_CYCLE_ENABLED=true
EOD_READINESS_RETRY_ENABLED=true
INTRADAY_MARKET_ENABLED=true
```

When an active Shadow experiment exists and automation is OFF, UI/API must show explicit warning (never silent).

## Troubleshooting

| Symptom | Check |
|---------|--------|
| Waiting tomorrow after mid-day init | Compare `activated_at` vs session open — expected |
| WAITING_FOR_ANALYTICS | Compare watermarks; enable RESEARCH_LIVE_MODE; run catch-up |
| Scheduler stale | last `DAILY_RESEARCH_CYCLE_V0` workflow finished_at |
| Duplicate Forward | Forward immutable by (candidate, as_of) |

## Catch-up

On API startup / readiness beat: if automation enabled (`RESEARCH_LIVE_MODE` or `EOD_READINESS_RETRY_ENABLED`) and a complete EOD exists while analytics/technical/forward lag (or last cycle does not cover that EOD) → trigger Daily Research Cycle **once** (Redis lock + `ALREADY_CURRENT` / `CYCLE_RUNNING`).

Stage codes: `SUCCESS` | `ALREADY_CURRENT` | `WAITING_INPUT` | `FAILED` | `DISABLED`.

Catch-up builds the decision for completed EOD T; it never backfills fills for orders created after an already-known OPEN.

## API

`GET /api/v1/shadow/daily-operations` includes:

- `pipeline.watermarks` — market / analytics / technical / relations / forward / shadow_plan
- `current_session_status` vs `next_session_preparation_status`
- `mid_session_activation`, `today_summary`, `next_session_summary` (Russian-ready codes)
- `automation.research_live_mode` + warning when Shadow is active but automation is off
