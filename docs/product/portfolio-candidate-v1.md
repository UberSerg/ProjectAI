# Portfolio Candidate V1

## Что это

**Кандидат портфеля Kraken** — единый исследовательский ответ на вопрос:

> Что Kraken предложил бы сделать с капиталом (по умолчанию 100 000 ₽) прямо сейчас?

Это **не** рекомендация к покупке и **не** real-money portfolio.

См. также: `docs/product/concrete-portfolio-composition-v1.md` —
конкретный тикерный состав поверх sleeves.

## Source of truth

Orchestration поверх существующих сервисов:

- Investment Decision / Opportunity / Confidence
- CBR Hurdle
- Asset Allocation
- Portfolio Risk Gate
- Realistic integer-lot allocator

Новых инвестиционных правил нет.

## Статусы

- `READY_FOR_RESEARCH`
- `PARTIAL`
- `INSUFFICIENT_DATA`
- `BLOCKED_BY_RISK`
- `STALE`

Статуса `READY_FOR_REAL_MONEY` нет.

## Target vs actual

Целевые веса могут отличаться от фактических из-за целых лотов.

Cash разделён на:

- strategic cash (осознанный);
- lot remainder (округление).

## Risk Gate

- `BLOCKED` / `INSUFFICIENT_DATA` → исключаются, вес уходит в Cash
- `RESEARCH_ONLY` → может быть в кандидате, но не executable
- нет fake Fixed Income fallback

## Snapshots

Таблица `investment.portfolio_candidates` хранит immutable JSON payload.
Новая логика → новый candidate_id.

## UI

- Route: `/portfolio/candidate`
- Hub: `/portfolio`
- Dashboard widget → CTA «Открыть портфель»

## Limitations

- no broker
- no real trading
- taxes not modeled
- equity calibration / corporate credit may remain UNKNOWN
