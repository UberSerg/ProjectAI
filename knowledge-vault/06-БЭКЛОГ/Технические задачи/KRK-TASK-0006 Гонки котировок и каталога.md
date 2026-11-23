---
id: KRK-TASK-0006
type: task
title: Не применять устаревший ответ котировок и каталога
module: frontend
priority: P2
status: approved
owner: unassigned
epic: KRK-EPIC-0008
dependencies: ["KRK-EPIC-0002"]
created: 2026-10-28
github_issue:
github_pr:
implementation_status: none
owner_acceptance: pending
deployment_status: unverified
---

# KRK-TASK-0006 — Гонки котировок и каталога

## Зачем

Быстрый клик по бумаге или фильтру не должен показывать предыдущий ответ как текущий.

## Текущее состояние

#86 этот экран не закрывал. PR C не создан.

## Желаемый результат

Старый ответ свечей и обзора игнорируется. Старый каталог не затирает список. Отменённый sync-status не выглядит как NONE. `clampRange` держит интервал внутри истории на краях и на перевёрнутых датах. Кривые строки дат обрабатываются явно.

## Техническая реализация

QuotesExplorer, range.ts, InstrumentsPage, тесты на порядок и unmount. Семантику цен не менять.

## Зависимости

Старт после merge эпика PR B, по очереди Owner. Технически файлы почти не пересекаются с B.

## Критерии готовности

Тесты пунктов 1–3 раздела PR C. Не входит создание портфеля: это KRK-TASK-0007.

## Риски

KRK-BUG-0004.

## Связанные проблемы

KRK-BUG-0004.

## История выполнения

Не начата.

## Подтверждения

Master Context, PR C.
