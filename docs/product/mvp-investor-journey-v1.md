# MVP Investor Journey V1

Status: Sprint 1 — investor journey UX + DEMO bootstrap. Product VERSION not bumped.

Base: `origin/main` `76877439351559e25d7ed35f2cdecedd25c1bb97`.

## Scope

Connect existing Multi-Portfolio, Daily Decision V2, Decision Memory, and Company
Intelligence into one UI path. No new prediction/policy engines, no broker, no
paid LLM, no Dataset V5, no Historical Data Engine expansion.

## User journey

1. Empty state → «Создать первый портфель» → `/portfolio#new-portfolio`.
2. DRAFT setup guide (cash → instruments → cost → preview → journal when ready).
3. Dashboard / My Portfolio: name, NAV/cash/securities, investment result or
   unavailable reason, freshness from Personal snapshot only.
4. Equity holding → «Проанализировать компанию» (`instrument_id` from position)
   → Company Intelligence → «← Вернуться к портфелю».
5. Tab «Что делать» → hypothetical `100000` RUB → five scenarios → limitations.
6. «Зафиксировать решение» → Decision Memory (recommendation, not a trade).
7. History survives refresh and backend restart. Duplicate capture is idempotent.

## Demo setup

```bash
cd backend
python -m app.modules.portfolio.cli demo-status
# Visible in default UI collection (still DEMO-labeled):
python -m app.modules.portfolio.cli demo-bootstrap --confirm --ui-visible
# Hidden is_test book (API needs ?test=true):
python -m app.modules.portfolio.cli demo-bootstrap --confirm
# Prior MVP seeds without durable source (opt-in reclaim only):
python -m app.modules.portfolio.cli demo-bootstrap --confirm --ui-visible --reclaim-legacy
python -m app.modules.portfolio.cli demo-reset --confirm --delete
```

- Durable identity: `ManualPortfolio.source = DEMO_INVESTOR_JOURNEY_V1` (not name/`is_test` alone)
- Display name: `DEMO — Investor Journey V1`
- Name collision with an ordinary personal book → `DEMO_NAME_COLLISION` (fail closed)
- Symbols: `SBER`, `LKOH`, `MGNT` resolved by ticker (never hardcoded ids)
- Cost basis = latest EOD; missing mark → skip + warning (no fake prices)
- `--confirm` required; idempotent; reversible via `--reset` / `demo-reset`

## Acceptance (executed 2026-10-28)

Docker remounted from `E:\!AI\ProjectAI-wt-mvp-journey`. Backend healthy.

| Step | Result |
|---|---|
| Bootstrap `--ui-visible` | portfolio_id **6798**, cash 500000, SBER/LKOH/MGNT seeded |
| Portfolio overview UI | NAV 508 460.46 ₽, cash 500 000 ₽, securities priced |
| Intelligence from holding | LKOH id=45, advisory CONSIDER INCREASE, gaps ABSTAIN/UNKNOWN honest |
| Return to portfolio | `/portfolio/6798?tab=holdings` |
| New capital 100 000 | Scenarios DO_NOTHING / HOLD_CASH / TARGET_UNDERWEIGHTS(unavailable, stale candidate) / KRAKEN_ALLOCATION(partial) / FIXED_INCOME_ALTERNATIVE(advisory) |
| Journal unchanged | cash still `500000.000000` after calc |
| Memory capture | id 726, `new_cash_rub=100000`, fingerprint synced; UI: «Рекомендация зафиксирована. Это не сделка…» |
| Backend restart | memory count 1, cash 500000, ops 4 |

Screenshots on branch `review-artifacts` (PR #84):
`review-artifacts/pr-84-mvp-investor-journey-v1/`
commit `5675e96ccca3239a1f7ca42a1ea246230d352337`
(01 overview, 02 intelligence LKOH, 03 scenarios, 04 memory).

## Tests

- Frontend focused (Docker): **105 passed** (personal portfolio + dashboard + intelligence + switcher)
- Frontend production build: `tsc -b && vite build` OK
- Backend: `test_mvp_demo_bootstrap` + `test_mvp_reliability_invariants` + `test_daily_personal_decision` → **50 passed**
- Ruff on touched Python: clean

## Sprint 1.1 remediation (PR #84)

- DEMO bootstrap/reset/delete require durable `source=DEMO_INVESTOR_JOURNEY_V1`; ordinary colliding names are refused.
- Decision Memory capture uses an explicit calculated snapshot only (no base `decisionRes` fingerprint fallback).
- Dirty capital / portfolio switch / in-flight calc cannot restore a stale fingerprint.
- Decision Memory async reads/writes are generation-scoped across portfolio A→B.
- Playwright journey: `frontend/e2e/investor-journey.spec.ts` (local reproducible; **not** in GitHub CI yet).
- Requires explicit `E2E_PORTFOLIO_ID` with durable `source=DEMO_INVESTOR_JOURNEY_V1` — no name/list fallback.
- Scope narrowed to decision→memory→refresh (not full empty→create→Intelligence).

```bash
# Local Playwright (stack must already be healthy; fixture must exist)
cd frontend
npm run test:e2e:install
E2E_PORTFOLIO_ID=<demo_id> E2E_BASE_URL=http://127.0.0.1:5173 E2E_API_URL=http://127.0.0.1:8000 npm run test:e2e
# From frontend container:
E2E_PORTFOLIO_ID=<demo_id> E2E_BASE_URL=http://127.0.0.1:5173 E2E_API_URL=http://backend:8000 npm run test:e2e
```

## Limitations

- Stale Portfolio Candidate makes TARGET_UNDERWEIGHTS unavailable and KRAKEN_ALLOCATION partial — shown honestly.
- Default DEMO `is_test=true` is hidden unless `?test=true` or `--ui-visible`.
- Company Intelligence remains advisory; not wired into Daily Decision / Candidate / broker.
- Playwright E2E exists locally; **GitHub CI coverage for browser E2E remains missing** (frontend job runs Vitest + build only).

## Follow-ups

- Wire `?test=true` end-to-end in PortfolioContext for hidden DEMO books.
- Refresh Portfolio Candidate before demo for fuller scenario executability.
- Optional: analyze link from decision action rows when `instrument_id` is present.
- Optional: add Playwright job to GitHub Actions against docker compose.
