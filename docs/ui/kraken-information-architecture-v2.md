# Kraken Information Architecture V2

UI/IA cleanup поверх существующей платформы. Бизнес-формулы investment / risk /
calibration / simulator / shadow **не меняются**.

## Цель

Сделать навигацию investor-first:

1. Что происходит с капиталом?
2. Где рынок и компании?
3. Где проверить доверие к моделям?
4. Экспертные слои — отдельно, не в primary flat nav.

## Primary navigation

```text
Kraken
├── Обзор                              /
├── Портфель
│   ├── Кандидат портфеля              /portfolio/candidate
│   ├── Инвестиционное решение         /investment-decision
│   └── Проверка риска                 /portfolio-risk
├── Рынок
│   ├── Котировки                      /market
│   ├── Компании                       /fundamentals  (+ alias /companies)
│   └── Облигации                      /bonds
├── Исследования
│   ├── Обзор исследований             /research-hub
│   ├── Качество прогнозов             /calibration
│   ├── Исторические симуляции         /simulator
│   ├── Живой эксперимент              /shadow
│   └── Лаборатория исследований       /research
└── Система
    ├── Процессы                       /workflows
    └── Система                        /system
```

## Hidden from primary (deep links keep working)

| Route | Role |
|-------|------|
| `/allocation` | Подробное распределение; баннер ведёт к кандидату / решению |
| `/portfolio` | Служебный хаб портфеля |
| `/analytics` | Экспертный слой признаков |
| `/technical` | Экспертный слой техсигналов |
| `/relations` | Экспертный слой связей рынка |
| `/research/advanced` | Хаб экспертного слоя |
| `/bonds/:secid` | Drill-down облигации |
| `/companies`, `/companies/:id` | Alias к fundamentals |

## Drill-downs

- Облигации: строка → `/bonds/{SECID}` (карточка: Основное / Деньги / Risk / Cashflows / Why Kraken / Data).
- Компании: «Открыть» → `/companies/{issuerId}` (или `/fundamentals/{id}`).
- Симуляции: строка / «Открыть» → `/simulator/{runId}`.
- Research hub группирует calibration / shadow / simulator / lab / advanced.

## Help

Каждая основная страница имеет `helpPageId` и запись в `HELP_PAGES`:

- `research_hub`, `research_advanced`, `bonds`, `bond_detail`, `portfolio_hub`
- обновлены `fundamentals` (Компании), `prediction_calibration` (human framing)
- `analytics` / `technical` / `relations` помечены как экспертный слой

## Wide layout rules

- Sidebar ~200px (`.sidebar-compact`); grid `200px minmax(0, 1fr)`.
- `.content` / `.content-wide`: **no** artificial max-width — fills remaining main column.
- Root cause of V2 narrow UI: `design-system.css` (imported after `styles.css`) re-applied `max-width: 1180px` on `.content`, overriding the V2 `min(1600px)` attempt.
- `.page-layout-reading` / `.content-reading` (~42rem) only for long text/help article blocks.
- `.page-purpose` and `.subtitle` may keep a soft reading max (~52rem) without capping the page shell.
- `.table-wrap`: `width: 100%`, `overflow-x: auto` only when columns overflow.
- `@media (max-width: 1024px)`: sidebar stacks; main stays full width.

## Out of scope

Изменения формул allocation / risk / calibration / bond accounting, новые backend
контракты сверх уже добавленного `GET /fixed-income/instruments/{symbol}`, ML training.
