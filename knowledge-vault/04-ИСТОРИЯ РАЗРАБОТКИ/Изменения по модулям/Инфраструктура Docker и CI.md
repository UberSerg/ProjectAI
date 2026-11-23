# Изменения по модулю: инфраструктура, Docker и CI

**Дата записи:** 2026-11-23  
**База:** `origin/main` `73c2e25e6aed323174b11dea4514946d5897f54b`

## Линия

- 2026-08-21 Docker foundation, PR #1
- 2026-09-08 docker startup reliability, PR #48 (subject лога)
- 2026-10-28…30 серия зелёных exact-head прогонов, названных в Master Context для #85, #86, #91, #98, #99
- 2026-10-30 политика risk-based CI записана в контекст и **не** меняет файлы workflows

## Как читать «CI green»

Каждая цифра ниже — цитата контекста или манифеста, не новый прогон Agents 02/03.

| Объект | Что записано |
|---|---|
| #86 | frontend 357, backend 1838 passed / 8 skipped, Docker success |
| #85 merge | run `40863675688` |
| #91 merge | run `40864314012` |
| #98 голова до merge | run `40927696166` |
| #99 голова до merge | run `40927914670` |
| 1.05 reviewed head | 1379 passed, 8 skipped в манифесте |

## Открытое

TD-006: шум duplicate-key в логе CI при зелёной job, OPEN.  
Сеть, порты, firewall, auth — DEFERRED с 2026-10-28.  
Сверка, какой worktree смонтирован в `projectai-frontend`, не сделана этой волной.  
Оптимизация GitHub Actions path filters — отдельная задача, не начата политическим коммитом.

## Связи

[[2026-10-30 — Risk-based CI]], KRK-BUG-0001, KRK-RISK-0004, KRK-DEBT-0006
