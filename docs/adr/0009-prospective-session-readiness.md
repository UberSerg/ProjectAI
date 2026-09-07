# ADR 0009 — Prospective session readiness and mid-session activation

## Status

Accepted

## Context

Shadow V2 was activated after the current session OPEN. Filling at that OPEN would use already-known prices. Separately, EOD market data can be complete while Analytics/Forward lag when the Daily Research Cycle is disabled.

## Decision

1. **Orders created after session open must wait for the next eligible session.** Official OPEN of the current session is not a valid execution reference for those orders (`delayed_observation` does not apply).
2. **EOD decision pipeline must catch up automatically** when research live automation is enabled and downstream watermarks lag a complete market date.
3. **UI separates “Today / current session” from “Next session preparation”.** Mid-session activation is explained in human language, not only `MIN_EXECUTION_DATE_NOT_REACHED`.
4. **Catch-up ≠ retroactive trading.** Preparing yesterday’s Forward after open does not authorize filling new orders at today’s OPEN.

## Consequences

- First day of a mid-session experiment has zero same-day fills by design.
- Operators must enable `RESEARCH_LIVE_MODE` (or equivalent flags) for unattended Shadow.
- Automation failures surface as readiness blockers, not silent green.
