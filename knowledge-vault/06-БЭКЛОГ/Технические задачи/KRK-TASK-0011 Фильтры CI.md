---
id: KRK-TASK-0011
type: task
title: Привести workflows к политике проверок по риску
module: ci
priority: P3
status: proposed
owner: unassigned
epic:
dependencies: []
created: 2026-10-30
github_issue:
github_pr:
implementation_status: none
owner_acceptance: pending
deployment_status: unverified
---

# KRK-TASK-0011 — Фильтры CI

## Зачем

Политика 30 октября просит не гонять весь стек на каждую правку документа. Сами workflows этим решением не изменены и могут по-прежнему запускать все jobs.

## Текущее состояние

Proposed. Отдельного разрешения менять Actions нет. Делать «заодно» в финансовом PR нельзя.

## Желаемый результат

Path filters или эквивалент: docs-only не тянет Docker; финансовый diff по-прежнему требует строгие проверки. Защита веток не ослаблена молча.

## Техническая реализация

Отдельный PR только на workflows, с разбором required checks.

## Зависимости

Явное «можно менять Actions». Нет зависимости от PR B.

## Критерии готовности

На тестовом docs-коммите видно, какие jobs пропускаются и какие остаются обязательными. Финансовый путь по-прежнему не пропускается.

## Риски

Ослабить гейт денег фильтром, который слишком широкий.

## Связанные проблемы

Нет бага. Связь с решением о risk-based CI.

## История выполнения

Не начата. Политический текст в main есть.

## Подтверждения

Раздел CI/CD policy 2026-10-30, пункт про GitHub Actions implementation status.
