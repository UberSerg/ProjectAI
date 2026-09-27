# Changelog

История официальных релизов **Kraken**.

Формат: Keep a Changelog + SemVer. Версия повышается только при явном release.

---

## [1.0.0] — 2026-09-27 — Kraken V1.0 — First Release

Первый зафиксированный рабочий релиз Kraken — персональной инвестиционно-аналитической системы для российского рынка.

### Portfolio

- Portfolio Builder под заданный капитал
- lot-aware построение позиций
- акции / fixed income / cash
- структура портфеля и концентрация
- rebalance и варианты действий
- recommendation cards
- rationale / explanation из реально доступных данных
- переход «Подробнее» в соответствующий контекст
- portfolio relations / correlations

### Market Data

- MOEX EOD ingest и incremental updates
- multi-day recovery после простоя (expected completed session vs local complete EOD)
- market completeness / readiness diagnostics
- technical analytics и relations data
- Data Coverage / investment data readiness

### Shadow

- Shadow portfolios: decisions, pending, fills, NAV
- prospective history и next-session execution semantics
- multi-day catch-up с day-by-day replay
- PIT / as-of recovery (Forward per session, `max_as_of`)
- idempotency, crash/resume, no duplicate replay
- recovery observability (market vs shadow lag)

### Investment Data

- Instrument Master
- market data foundation
- technical features и relations
- RAS / fundamentals foundation (coverage PARTIAL где не READY)
- dividend foundation и dividend PIT quality tracking (PARTIAL)
- fixed income foundation (PARTIAL)
- historical universe foundation
- CBR / rate context

### Analytics / Decisions

- portfolio analysis, allocation, risk/concentration indicators
- recommendation presentation и rebalance calculations
- available explanations
- decision infrastructure (не доказанная edge)

### User Experience

- dark desktop cockpit
- Portfolio Overview, allocation, risk/health, recommendations
- honest empty / partial states
- USER presentation mode и OWNER presentation mode
- technical USER/OWNER switch (`kraken.presentationRole`)
- OWNER operational diagnostics

Явно: **USER / OWNER V1.0 — presentation-level separation, not production authorization.**

### Reliability / Engineering

- Docker-based environment
- backend / frontend tests и CI
- migrations
- recovery contracts
- worktree-safe development rules
- review-artifacts workflow
- post-merge validation

### What Kraken V1.0 is NOT

Kraken V1.0 пока **не** является:

- автономным брокерским торговым роботом;
- доказанно прибыльной системой;
- production multi-user SaaS;
- системой с полноценным IAM;
- завершённым Dataset V3;
- завершённым Candidate V2;
- Alpha Lab;
- полноценным self-learning Kraken Brain.

Это первый рабочий product baseline.

[1.0.0]: https://github.com/UberSerg/ProjectAI/releases/tag/v1.0.0
