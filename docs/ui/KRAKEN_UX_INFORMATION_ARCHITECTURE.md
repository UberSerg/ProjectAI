# KRAKEN UX Information Architecture (Agent 00)

**Base:** `origin/main` `d211da0…`  
**Extends:** `docs/ui/kraken-information-architecture-v2.md`  
**Presentation modes:** USER (investor) / OWNER (research+ops) — soft gate, not IAM.

## Hierarchy principle

```text
Понятный ответ
  → объяснение (почему)
    → исходные факты / traces
      → технические сведения (OWNER / disclosure)
```

## USER journey map

```text
Обзор (/)
  ├─ Портфель (/portfolio → /portfolio/:id)
  │    ├─ Состав
  │    ├─ История операций
  │    └─ Что делать (рекомендации ≠ сделки)
  ├─ Решения (/investment-decision)
  └─ История (deep link personal history)
```

USER must answer the five investor questions without OWNER tools.

## OWNER additions

Everything USER sees, plus:

```text
Рынок → Котировки / Инструменты / Компании / CI / Облигации
Исследования → Hub / Calibration / Simulator / Shadow / Lab / Evidence
Система → Workflows / System
Shadow → Decision Journal V4 (showcase)
```

## Shadow information layers

1. **NOW** — experiment state, last confirmed session, trusted virtual value  
2. **DECISION** — latest actions + Journal entry point  
3. **EXECUTION** — orders/fills/pending (not promises)  
4. **RISK / DATA** — constraints, freshness, completeness  
5. **TECHNICAL** — watermarks, pipeline, IDs, provenance drill-down  

## Decision Journal V4 card contract

**Closed:** date · mode · tickers · BUY/SELL/HOLD/REVIEW counts · orders/fills · NAV/cash/DD only if trustworthy · valuation freshness · CTA «Детали решения»

**Open blocks:**

| Block | Content | Forbidden |
|---|---|---|
| A What Kraken knew | dates, context name, freshness, provenance | invented prices |
| B What decided | ticker · action · human why · plan fields if real | fake plan qty |
| C Why | traces / policy / risk reasons | LLM post-hoc |
| D What happened | Decision → Order → Fill chain by IDs | ticker coincidence = link |

## Glossary (canonical UI copy)

| Technical | USER label |
|---|---|
| NAV | Общая стоимость портфеля |
| Cash | Свободные деньги |
| Market value | Стоимость активов |
| Drawdown | Просадка |
| Decision | Решение Kraken |
| Order | Ордер / заявка |
| Fill | Исполнение |
| Pending | Ожидает исполнения |
| Stale | Данные требуют обновления |
| Counterfactual replay | Историческая реконструкция |

Do not equate: NAV≠P&L≠DD; gross exposure≠asset value; Missing≠0; Partial≠Full; LIVE≠Replay.

## Shared labels ownership

- **Agent 05** owns `frontend/src/utils/labels.ts` mutations.  
- Other agents propose strings via handoff; orchestrator merges conflicts.

## Navigation constraints

- Preserve deep links and route semantics in `App.tsx`.  
- Soft-hide placeholders that imply finished product; do not break URLs.  
- System group OWNER-only in primary nav (already mostly true).  
- Align USER primary items with investor tasks, not expert dumps.

## Data quality & provenance badges (contract for Agent 01)

Required semantic tones (not decorative):

- FRESH / STALE / PARTIAL / UNAVAILABLE  
- LIVE / COUNTERFACTUAL  
- BUY / SELL / HOLD / REVIEW  

## Demo path (acceptance narrative)

USER: open → portfolio value quality → composition → instrument → proposal → why → history → distinguish recommendation vs fill → return → see unknowns.

OWNER: Shadow → state → Journal day expand → Decision→Order→Fill → provenance → data limits.
