# Kraken Information Architecture V1

UI/UX-only redesign поверх существующей платформы. Backend, модели, Dataset,
Forward и Shadow не меняются.

## Цель

Сделать Kraken понятным инвестиционным помощником:

1. Что происходит?
2. Что предлагает сделать?
3. Почему так решил?
4. Какие риски?
5. Насколько можно доверять?

## Уровни

| Level | Аудитория | Примеры |
|-------|-----------|---------|
| Investor UI | основной пользователь | Обзор, Портфель, Рынок |
| Research UI | эксперт / лаб | Research Lab, Diagnostics |
| System UI | оператор | Процессы, Диагностика |

## Карта навигации

```text
Kraken
├── Обзор                         /
├── Портфель
│   ├── Кандидат портфеля             /portfolio/candidate
│   ├── Обзор портфеля                /portfolio
│   ├── Инвестиционное решение        /investment-decision
│   ├── Проверка риска                /portfolio-risk
│   └── Распределение капитала         /allocation
├── Рынок
│   ├── Котировки                 /market
│   ├── Фундамент                 /fundamentals
│   ├── Облигации                 /bonds
│   └── Макро (CBR)               /bonds#hurdle / overview cards
├── Исследования
│   ├── Аналитика                 /analytics
│   ├── Техсигналы                /technical
│   ├── Связи                     /relations
│   ├── Качество прогнозов        /calibration
│   ├── Исторические симуляции    /simulator
│   ├── Живой эксперимент         /shadow
│   └── Лаборатория               /research
└── Система
    ├── Источники / Система       /system
    └── Процессы                  /workflows
```

## Аудит: оставить / спрятать / объединить / переименовать

| Было | Решение | Пользовательское имя |
|------|---------|----------------------|
| Обзор (health dashboard) | пересобрать decision-first | Обзор |
| /portfolio placeholder | сделать hub Портфель | Портфель |
| Инвестиционное решение | redesign Decision First | Что делать с капиталом? |
| Проверка риска | оставить, polish | Проверка риска |
| Распределение капитала | вторичный пункт под Портфель | Распределение |
| Облигации | redesign «Подходит ли?» | Облигации |
| Качество прогнозов | polish trust framing | Качество прогнозов |
| Симуляции | переименовать | Исторические симуляции |
| Живой эксперимент | оставить в Исследованиях | Живой эксперимент |
| Лаборатория | увести в экспертный блок | Лаборатория исследований |
| Analytics / Relations / Technical | сгруппировать в Исследования | без удаления routes |
| Recommendations / Models / Decision Memory | оставить «Скоро» | — |

## Принцип Decision First

1. Level 1 — человеческий ответ  
2. Level 2 — метрики и причины  
3. Level 3 — technical (version / hash / provenance)

## Design system V1

- Typography: Inter + tabular figures  
- Cards: Hero / Metric / Explanation / Warning / Risk / Data Quality  
- Status: Success / Warning / Risk / Unknown / Research only / Blocked  
- Tables: единые заголовки, mobile fallback  
- Empty / Loading: почему нет данных + skeleton  

## Out of scope

ML, API contract changes, business rules, Forward/Shadow/Simulator calculations.
