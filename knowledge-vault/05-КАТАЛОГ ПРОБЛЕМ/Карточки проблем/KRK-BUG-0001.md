---
id: KRK-BUG-0001
type: bug
module: frontend / docker
priority: P0
status: open
evidence_level: hypothesized
created: 2026-10-30
owner: unassigned
github_issue:
github_pr:
last_checked: 2026-11-23
---

# KRK-BUG-0001 — Устаревший bind-mount frontend

## Суть

После merge PR #98 и #99 исходники `main` содержат Journal V4 и блок общей стоимости. Скриншоты владельца показывали прежний UI. Вероятная причина: контейнер frontend смонтирован из старого worktree.

## Как проявляется

На `/shadow` нет кнопки «Детали решения». На `/portfolio` нет блока общей стоимости, видны только кэш и число позиций. Git при этом уже на `95f2fd857764448168343d22bacf8e49ed445d29` и раньше.

## Почему опасно

Любая визуальная приёмка, скриншот агента и сравнение со Snowball ложны, пока не доказано, какой каталог отдаёт Vite.

## Причина

`docker-compose.yml` монтирует `./frontend/src:/app/src` относительно каталога Compose. Master Context называет ранее сообщенный worktree `shadow-reliability`. `docker inspect` в разборе 30 октября не был независимым фактом. Эта волна Vault контейнер не смотрела. Поэтому причина — гипотеза, симптом — сообщение Owner.

## Как должно работать

Контейнер `projectai-frontend` монтирует исходники того дерева, которое соответствует проверяемому SHA. В DOM есть маркеры текущего UI. Чужие dirty worktree, тома данных, порты и backend не трогаются.

## Предлагаемое исправление

Осмотреть Mounts и метки Compose, сравнить файл в контейнере с main, переключить только frontend на свежий каталог, снять до и после. Без `down -v`, reset и stash.

## Критерии закрытия

Есть вывод `docker inspect` Mounts, совпадение маркера исходника с заявленным SHA и скриншот Owner, где видны элементы из этого SHA. Пока этого нет, карточка open.

## История

- 2026-10-30: симптом записан в Master Context. Код #98/#99 уже в main.
- 2026-11-23: карточка заведена. Повторной проверки Docker нет.

## Связанные задачи

KRK-TASK-0001. Блокирует честную приёмку KRK-UX-0001 и KRK-UX-0002.

## Подтверждающие источники

Master Context, Current State 2026-10-30, P0 user-visible blocker. Уровень: симптом `REPORTED_BY_OWNER`, причина `hypothesized`, наличие кода в git `GITHUB_VERIFIED`.
