---
id: KRK-TASK-0001
type: task
title: Проверить, откуда смонтирован frontend
module: docker
priority: P0
status: ready
owner: unassigned
epic: KRK-EPIC-0001
dependencies: []
created: 2026-10-30
github_issue:
github_pr:
implementation_status: none
owner_acceptance: pending
deployment_status: unverified
---

# KRK-TASK-0001 — Проверка mount

## Зачем

Пока неизвестен каталог Vite, нельзя принимать UI.

## Текущее состояние

Задание сформулировано 30 октября. Эта волна Vault `docker inspect` не делала. Поэтому задача ready, не in_progress и не done.

## Желаемый результат

Записаны Mounts контейнера frontend, метка проекта Compose и совпадение или расхождение файла с SHA main. Если каталог старый — переключён только frontend, без смены портов, backend, томов и чужих dirty-деревьев. Есть скриншот до и после.

## Техническая реализация

`docker inspect` и сравнение маркера исходника. Без `down -v`, reset, clean, stash.

## Зависимости

Нет. Блокирует KRK-TASK-0012 и приёмку журнала.

## Критерии готовности

В отчёте есть путь mount, SHA, который этот путь содержит, и наблюдаемый DOM. Гипотеза «shadow-reliability» либо подтверждена, либо снята.

## Риски

Разрушить данные томом. Переключить не тот контейнер.

## Связанные проблемы

KRK-BUG-0001.

## История выполнения

- 2026-10-30: назначено в Master Context.
- 2026-11-23: подтверждения выполнения нет.

## Подтверждения

Текст P0 blocker в Master Context. `REPORTED_BY_OWNER` для симптома.
