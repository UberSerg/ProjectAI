# KRAKEN UX Audit — Screen Passports (Agent 00)

**Date:** 2026-10-29  
**Base:** `origin/main` `d211da0943518eaeea11dd7739902c60538cca6f`  
**Evidence class:** source-code + prior swarm audit (`KRAKEN_UX_SWARM_AUDIT_2026-10-29.md`). Browser baselines = Wave 0/9 (not yet complete).  
**Approved UX direction:** Decision Journal **Variant 4** (Owner).

## Verified prerequisites

| Check | Result |
|---|---|
| PR #85 on main | Yes (`a1c165b…`) |
| PR #91 on main | Yes (`512628b…`) |
| Open UX feature PRs | None at kickoff (only #83, #58 unrelated) |
| Finance engine / network | Out of scope |

## Five investor questions (IA lens)

1. Что у меня есть? → Dashboard, Portfolio Hub, Personal Portfolio  
2. Что происходит? → Dashboard, Shadow, History  
3. Что предлагает Kraken? → Investment Decision, Portfolio Candidate, Shadow decisions  
4. Почему? → Decision Journal V4, instrument “Why”, decision traces  
5. Что произошло после? → Journal Order→Fill, personal ops history  

Rule: **answer → explanation → evidence → technical**.

---

## Screen passports

### Dashboard `/`

| Field | Content |
|---|---|
| Зачем | Быстро понять состояние капитала и следующий шаг |
| Главный ответ | Общая стоимость, результат, cash/активы, предложение Kraken, CTA |
| Текущая проблема | ~724 LOC; health/diagnostics конкурируют с investor answer (source) |
| Новая структура | Hero money → proposal → recent changes → quieter data quality → CTA |
| Primary CTA | Открыть решение / портфель (по контексту) |
| Empty/Loading/Partial | Skeleton money; Partial NAV never as full; Missing≠0 |
| Mobile | Single column; no sidebar dominance |
| Agent | **05** |
| Acceptance | USER видит NAV/качество без объяснений разработчика |

### Portfolio Hub `/portfolio`

| Field | Content |
|---|---|
| Зачем | Выбрать портфель; увидеть стоимость |
| Главный ответ | Карточки с total NAV (fail-closed) после #91 |
| Проблема | Partial UI screenshot was forced overlay historically — need real partial API proof in QA |
| Agent | Hub already shipped; polish via **04**/**05** if copy/nav only |
| Acceptance | Cash-only `3,34 ₽`; partial ≠ full |

### Personal Portfolio `/portfolio/:id` · `/portfolio/mine`

| Field | Content |
|---|---|
| Зачем | Личный кабинет: состав, операции, рекомендации |
| Главный ответ | Total / cash / assets / P&L if valid; composition table; ops history |
| Проблема | ~1300 LOC, 7 tabs; `prompt`/`confirm` dialogs; dense technical history (source) |
| Новая структура | Money hero → composition → history → «Что делать» separate from journal |
| Agent | **04** |
| Acceptance | Deep links/tabs intact; no PR B finance semantics changes |

### Investment Decision `/investment-decision`

| Field | Content |
|---|---|
| Зачем | Что Kraken предлагает сейчас |
| Главный ответ | Действия по тикерам + confidence + constraints |
| Agent | **05** (labels/nav) + content polish coordinated; major layout if needed with orchestrator |
| Acceptance | Recommendation ≠ Order ≠ Fill |

### Portfolio Candidate / Risk

| Field | Content |
|---|---|
| Зачем | Кандидат модели / проверка риска |
| Agent | **05** copy/nav; deeper UX later |
| Note | Formulas untouched |

### Shadow `/shadow` (OWNER)

| Field | Content |
|---|---|
| Зачем | Что делает живой эксперимент сейчас |
| Главный ответ | State / last session / virtual NAV integrity / last decisions / why idle |
| Проблема | ~1220 LOC dump; `liveNav ?? nav ?? cash` and `?? 0` presentation risks (source) |
| Новая структура | NOW → DECISION → EXECUTION → RISK → TECHNICAL |
| Agent | **03** (excludes DecisionJournalPanel) |
| Acceptance | RECOVERING only with proof; Missing≠0; LIVE≠counterfactual |

### Decision Journal (inside Shadow)

| Field | Content |
|---|---|
| Зачем | История: почему решил / что исполнил |
| Главный ответ | Compact day card → expandable WHY with Decision→Order→Fill |
| Проблема | Dense `<details>` summary; wide raw tables; human reasons mostly REVIEW/ROTATE; abort race risk (source) |
| Новая структура | Variant 4 closed card + A/B/C/D expand blocks |
| Agent | **02** only |
| Acceptance | No fabricated rationale; no NAV-delta P&L; keyboard accordion; stale request fence |

### Market / Quotes / Instruments / Bonds / Company Intelligence

| Field | Content |
|---|---|
| Зачем | Понять актив как финансовый объект |
| Главный ответ | Price + as-of + change (if valid) + chart + Why Kraken |
| Проблема | Dense filters/DQ; technical IDs early (source) |
| Agent | **06** |
| Note | PR C loading races: document, don’t silently mix |

### Research Hub / Lab / Evidence / Calibration / Simulator

| Field | Content |
|---|---|
| Зачем | Что проверяли → результат → доверие → ограничения |
| Проблема | Config-first density (source) |
| Agent | **07** |
| Acceptance | Never claim “profitability” without evidence |

### System / Workflows (OWNER)

| Field | Content |
|---|---|
| Зачем | Блокирует ли что-то систему; что делать |
| Agent | **08** |
| Acceptance | No fake green; raw JSON last |

---

## Issue inventory (code-grounded; browser TBD)

| ID | Severity | Finding | Owner |
|---|---|---|---|
| UX-01 | P0 | Journal closed state not Variant 4 | 02 |
| UX-02 | P0 | Journal stale response fence incomplete | 02 |
| UX-03 | P0 | Shadow presentation fallbacks can conflate missing/zero | 03 |
| UX-04 | P1 | Triple CSS layer / token drift | 01 |
| UX-05 | P1 | Personal portfolio density + native dialogs | 04 |
| UX-06 | P1 | Dashboard health vs investor hierarchy | 05 |
| UX-07 | P1 | USER nav vs IA v2 groupings incomplete | 05 |
| UX-08 | P1 | Instrument pages technical-first | 06 |
| UX-09 | P2 | Research/simulator outcome buried | 07 |
| UX-10 | P2 | System raw diagnostics first | 08 |
| UX-11 | P1 | E2E narrow; visual baselines missing | 09 |

**Unconfirmed until browser:** mobile overflow, focus traps, contrast AA.

## Out of scope (report only)

- PR B Personal Operations Integrity  
- PR C Frontend Data Loading (except documenting races)  
- Live Shadow catch-up ops  
- Network/Docker/auth  
- Model/policy/risk formulas  
- VERSION bump  
