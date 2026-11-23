---
id: KRK-DEBT-0003
type: debt
module: personal analytics
priority: P3
status: done
evidence_level: verified
created: 2026-11-23
owner: unassigned
github_issue:
github_pr:
last_checked: 2026-11-23
---

# KRK-DEBT-0003 — TD-003 повторное чтение позиций

## Суть

Cashflows и rebalance раньше заново читали `ManualPosition` после того, как личная книга уже была собрана.

## Как проявляется

Больше не проявляется по заявлению файла долга: оба пути используют `load_personal_snapshot` / `snap.positions`.

## Почему опасно

Было риском разойтись с проекцией активного журнала. Сейчас файл помечает это DONE в Brain Foundation V2.

## Причина

Узкий обход снимка. Закрыт.

## Как должно работать

Аналитика активного журнала читает снимок, а не второй проход по старой таблице.

## Предлагаемое исправление

Не требуется.

## Критерии закрытия

Выполнены в тексте TD-003 (`status: DONE`). Эта волна тест не перезапускала. Если код снова читает `ManualPosition` на этих путях, карточку открыть заново.

## История

- DONE в `docs/technical-debt.md` на текущем main.
- 2026-11-23: перенесено в Vault со статусом done.

## Связанные задачи

Нет.

## Подтверждающие источники

`docs/technical-debt.md`, TD-003.
