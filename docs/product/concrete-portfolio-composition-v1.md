# Concrete Portfolio Composition V1

## Что это

Развёртка Equity / Fixed Income **sleeves** в конкретный исследовательский состав:

- реальные тикеры / SECID;
- целые лоты;
- dirty price для облигаций;
- per-instrument Risk Gate;
- final validation после округления лотов.

Версии политик:

- `EQUITY_COMPOSITION_V1`
- `FIXED_INCOME_COMPOSITION_V1`
- `CONCRETE_PORTFOLIO_CANDIDATE_V1`

## Source of truth

Не новая инвестиционная система. Orchestration поверх:

Opportunity → Sleeve Allocation → Concrete Selection → Risk Gate → Lots → Candidate

## Правила

- Нет synthetic `EQUITY_SLEEVE` / `FI_SLEEVE` в итоговых позициях.
- Equal weight внутри sleeve.
- Не выбираем облигации по max YTM.
- `RESEARCH_ONLY` не становится executable silently.
- Нереализованный вес sleeve → Cash.
- Concentration после лотов перепроверяется.

## Limitations

Research only. Нет брокера, налогов, real-money readiness.
