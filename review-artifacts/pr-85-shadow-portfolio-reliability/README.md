# Review artifacts — PR #85

## Feature
Shadow & Portfolio Reliability V1

## Commit
`6e5b5ccad1e7a9935cc7b81548d8b0514e8e40fb` on `feature/shadow-portfolio-reliability-v1`

## Artifacts

| File | What it shows |
|---|---|
| `01-portfolio-hub-cash-format.png` | Portfolio hub: DEMO 500 000 ₽ and portfolio «1» cash `3,34 ₽` (not inflated) |
| `02-shadow-ops-recovery.png` | Shadow ops: catch-up lag UI, watermarks, no false −751k when coverage FULL |
| `03-instrument-lkoh-overview.png` | Instrument LKOH overview with DQ summary |
| `04-instrument-lkoh-dq-filtered.png` | DQ tab filtered to LKOH-only issues |

## Notes
- Verify RUB formatting and that portfolio «1» shows ~3.34 not 3340.
- Verify Shadow does not present incomplete NAV as full P&L vs initial capital when coverage is partial (API: `nav_is_complete` / `valuation_status`).
- Verify DQ issues on instrument page are only for that instrument_id.
