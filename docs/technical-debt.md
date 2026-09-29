# Technical Debt Backlog

Permanent backlog for non-blocking issues discovered during product work.

## Policy

**Do not block a product PR for technical debt / nice-to-have.**

Block a PR only if the issue:

1. can corrupt real data;
2. can produce a materially wrong financial calculation;
3. breaks the main user scenario;
4. creates a serious architectural hole that makes the current feature unreliable;
5. breaks CI / build / release;
6. creates a security or data-loss problem.

Everything else: record here with priority, then continue the product task.

This file is **not** a product roadmap. Large features (Dataset V3, dedicated bond accounting, Daily Decision history, broker execution, etc.) stay out of this backlog.

## Entry format

| Field | Meaning |
|---|---|
| ID | Stable id (`TD-NNN`) |
| category | `BUG` / `TECH-DEBT` / `NICE-TO-HAVE` |
| priority | `P1` / `P2` / `P3` |
| area | Module / surface |
| description | What is wrong or incomplete |
| impact | User / maintainer impact |
| why deferred | Why it does not block the current PR |
| suggested fix | Bounded next step |
| status | `OPEN` / `DONE` |

---

## Open items

### TD-001

- **category:** TECH-DEBT
- **priority:** P3
- **area:** Personal Portfolio / journal cutover
- **description:** Cutover timestamps use server UTC with microseconds; UI `datetime-local` is second-precision. A same-second post-activation create can still hit `OPERATION_BEFORE_JOURNAL_CUTOVER` if the user submits the floored second of cutover.
- **impact:** Rare UX friction immediately after activation; no double-count when rejected.
- **why deferred:** Real risk is low after second-precision fix; not a financial correctness hole.
- **suggested fix:** Document second-floor semantics more explicitly in UI copy, or refresh default occurred_at on submit when unchanged.
- **status:** OPEN

### TD-002

- **category:** TECH-DEBT
- **priority:** P3
- **area:** Personal Portfolio / activate-journal
- **description:** Concurrent `activate-journal` IntegrityError recovery is covered by a monkeypatched race path, not a true multi-connection deterministic race test.
- **impact:** Slightly weaker confidence in concurrency coverage; runtime handler exists.
- **why deferred:** Idempotent keys + IntegrityError recovery already prevent duplicates/500 in practice.
- **suggested fix:** Add two-session race test with controlled commit order when CI DB isolation allows it.
- **status:** OPEN

### TD-003

- **category:** TECH-DEBT
- **priority:** P3
- **area:** Personal analytics / cashflows / rebalance
- **description:** Cashflows and rebalance previously re-scanned `ManualPosition` after resolving the Personal book.
- **impact:** Boundary cleanup; projection remains derived journal state when ACTIVE.
- **why deferred:** n/a — narrowed in Brain Foundation V2.
- **suggested fix:** Done for cashflows + advisory rebalance: both use `load_personal_snapshot` / `snap.positions` only.
- **status:** DONE

### TD-004

- **category:** NICE-TO-HAVE
- **priority:** P3
- **area:** API naming
- **description:** Legacy names (`analyze_manual_portfolio`, `manual_weight`, `ManualPortfolioAnalysis`, `/manual-portfolios/...`) still describe Personal analytics.
- **impact:** Developer confusion; no user-facing financial error.
- **why deferred:** Functional after PR #63/#64; rename is a compatibility-sensitive cleanup.
- **suggested fix:** Alias endpoints/types to Personal naming; deprecate old names gradually.
- **status:** OPEN

### TD-005

- **category:** TECH-DEBT
- **priority:** P2
- **area:** Fundamentals / portfolio-coverage
- **description:** `GET /fundamentals/fns/portfolio-coverage` covers a research cohort, not Personal holdings.
- **impact:** UI that implies “your portfolio coverage” can mislead if not labeled carefully.
- **why deferred:** Changing semantics would mix Research and Personal books; label/copy or a Personal-specific coverage endpoint is a separate product choice.
- **suggested fix:** Either relabel as research cohort or add Personal-holdings coverage endpoint.
- **status:** OPEN

### TD-006

- **category:** BUG
- **priority:** P3
- **area:** CI / market corporate actions
- **description:** CI may occasionally log PostgreSQL duplicate-key noise for `uq_market_corporate_actions_identity` while the job remains green.
- **impact:** Log noise / flaky-looking CI output; not a failing gate when green.
- **why deferred:** Needs reproducibility check; does not fail release currently.
- **suggested fix:** Harden upsert/idempotency in the offending test or ingestion path after capturing a failing log sample.
- **status:** OPEN

### TD-007

- **category:** BUG
- **priority:** P1
- **area:** research_cycle
- **description:** Failure recovery tests expected `FAILED` while a stale DB `RUNNING` row (without Redis lock) made runtime report `BLOCKED`.
- **impact:** Local full-suite noise outside Personal Portfolio path.
- **why deferred:** n/a — fixed in Brain Foundation V2.
- **suggested fix:** Canonical semantics: `BLOCKED` only when Redis lock not acquired; if lock acquired but a prior `RUNNING` row remains, finalize it as `FAILED` (`STALE_RUNNING`) and continue. Mid-cycle exceptions remain `FAILED`.
- **status:** DONE

### TD-008

- **category:** TECH-DEBT
- **priority:** P2
- **area:** market / historical universe / Dataset V3
- **description:** `historical_equity_universe_v2` delisted MOEX coverage is incomplete; many boundaries still candle-proxy (`DERIVED_FROM_*`) or `UNKNOWN` open windows. Not a full market-wide survivorship-free catalog.
- **impact:** Dataset V3 Core reduces survivorship bias only where board/candle evidence exists; year-coverage and inactive representation may understate true historical MOEX universe.
- **why deferred:** Contract correctly marks `universe_quality=PARTIAL` and does not claim bias eliminated; full delisted archaeology is a data ingestion program, not a Dataset builder bug.
- **suggested fix:** Expand MOEX board history / delisted security ingest; re-measure authoritative vs proxy boundary ratios. Brain Foundation V2 improved measurement (boundary counts, inactive examples, research_quality grade, V2↔V3 compare artifact) but does **not** close archaeology.
- **evidence (Brain Foundation V2):** existing SUCCESS V3 runs 249/251 (bounded filtered window) show authoritative `eligible_from=MOEX_BOARD_LISTED_FROM` with `eligible_to=UNKNOWN` open windows; inactive representation requires broader unfiltered windows.
- **status:** OPEN
