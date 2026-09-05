# Fundamental & Event Intelligence V1 — Data Foundation

Статус: **реализовано как хранилище и identity-слой**. Отчётности и дивидендов в системе нет
и они не выдуманы. Модели на этих данных не обучаются, Dataset V2 / Forward / Shadow / Policy
не изменены, операционный дневной цикл не зависит от этого модуля.

Migration: `20260905_0018` (схема `fundamentals`). Флаг `FUNDAMENTALS_UPDATE_ENABLED=false`
по умолчанию, beat-расписание не регистрируется.

---

## 1. Source audit (живая проверка 2026-09-05)

Вердикты зафиксированы как данные в `audit.SOURCE_FINDINGS`, доступны через
`GET /api/v1/fundamentals/sources/audit` и CLI `audit` (JSON + артефакт в `.tmp/fundamentals-v1/`).

| Источник | Назначение | Что реально вернул | Вердикт |
| --- | --- | --- | --- |
| MOEX ISS `/iss/securities.json?q={SECID}` | identity эмитента | `emitent_id`, `emitent_title`, `emitent_inn`, `emitent_okpo`, `isin`, `type` | **ACCEPTED** |
| MOEX ISS `/iss/securities/{SECID}/dividends.json` | дивиденды | блок описания бумаги, не таблицу дивидендов | **REJECTED** |
| MOEX ISS `history/.../dividends` | дивиденды | историю свечей | **REJECTED** |
| e-disclosure.ru | отчётность / раскрытие | HTTP 403 для автоматического доступа | **REJECTED** |
| `market.corporate_actions` (ISS splits) | корпоративные события | `SPLIT` / `REVERSE_SPLIT` с датой вступления, без даты объявления | **ACCEPTED** |
| — | финансовая отчётность | бесплатного источника с доказуемой датой публикации не найдено | **DEFERRED** |
| — | дивиденды | принятого фида с датами объявления нет | **DEFERRED** |

Что **не** делалось: скрейпинг, обход 403, подстановка дат публикации, fuzzy-сопоставление
IFRS/RAS-показателей, начисление дивидендов в портфели, обучение моделей.

---

## 2. Семантика `known_at`

`known_at` — дата, с которой информация была доступна. Экономическая дата
(`period_end`, `record_date`, `ex_date`, `effective_date`) — отдельное поле.

Правила (чистые функции в `domain/pit_rules.py`):

1. Запись видна в момент `t` только если `known_at <= t`. Запись без `known_at` не видна никогда.
2. Будущая экономическая дата разрешена: объявленная будущая дата фиксации — это законное
   знание, но только через запись, чей `known_at` уже наступил.
3. Ретроспективная правка (restatement) — новая версия, а не перезапись: в пределах периода
   выигрывает версия с наибольшим `(known_at, report_version)`.
4. Дивидендная серия версионируется так же: `(known_at, version)`; отменённая выплата не
   попадает в «предстоящие».

`known_at` обязателен (NOT NULL) в `financial_reports`, `dividend_events`, `corporate_events`.
В `market.corporate_actions` он nullable, поэтому проекция сплитов подставляет
`known_at = effective_date` и пишет `payload.known_at_basis = EFFECTIVE_DATE_OBSERVABLE`.
Это **позже** реальной даты объявления, то есть консервативно: информацию можно только
скрыть, но не подсмотреть. Если фид начнёт отдавать `known_at`, он записывается как
`SOURCE_KNOWN_AT` и дата уточняется.

---

## 3. Схема `fundamentals`

| Таблица | Назначение |
| --- | --- |
| `issuers` | юридический эмитент; ключ — `moex_emitent_id` |
| `security_issuer_mappings` | инструмент → эмитент; `mapping_status` = MAPPED / AMBIGUOUS / UNMAPPED, `issuer_id` nullable, чтобы честно хранить неразрешённые случаи |
| `financial_reports` | версия раскрытого отчёта; UNIQUE(issuer, standard, period_type, period_end, version, source) |
| `financial_facts` | значение показателя внутри версии отчёта |
| `metric_registry` | словарь нормализованных показателей |
| `dividend_events` | версия дивидендного раскрытия (`version`, `supersedes_id`) |
| `corporate_events` | структурные события с обязательным `known_at` |
| `source_documents` | provenance документа; `published_at` не домысливается |
| `ingestion_runs` | журнал попыток загрузки, включая DEFERRED / FAILED |

---

## 4. Metric registry (консервативный seed)

`REVENUE`, `OPERATING_INCOME`, `NET_INCOME`, `TOTAL_ASSETS`, `TOTAL_EQUITY`, `TOTAL_DEBT`,
`CASH_AND_EQUIVALENTS`, `OPERATING_CASH_FLOW` — `SUPPORTED`.
`EBITDA` — `AMBIGUOUS`: это не строка отчётности, определение зависит от эмитента.

`applies_to_banks` выставлен осторожно: `REVENUE`, `OPERATING_INCOME`, `TOTAL_DEBT` и `EBITDA`
помечены `false`, потому что у банков «выручка», «операционная прибыль» и «долг» означают
другое (привлечённые средства — не долг в смысле leverage). Нормализация банков в V1 не решена.

---

## 5. Feature-контракты

Обе фичи считаются по запросу и **не** материализуются в общий feature store.

`fundamental_daily` v1 — только если отчёты есть; иначе `status=NOT_READY` и ноль строк:

- `days_since_latest_report` = `as_of - known_at`;
- `report_age_days` = `as_of - period_end`;
- `has_recent_report` (порог 180 дней);
- `metric_<CODE>` — только для фактов со статусом `NORMALIZED` и непустым значением.

Отсутствующий показатель **пропускается**, а не заполняется нулём: выдуманный ноль
неотличим от настоящего.

`event_daily` v1 — из corporate events и дивидендов, когда они есть:
`days_since_last_split`, `split_events_365d`, `days_since_last_dividend_disclosure`,
`last_disclosed_dividend_per_share`, `has_known_upcoming_dividend`,
`days_to_next_dividend_record_date`. Если по инструменту нет ни одного дивидендного
раскрытия, дивидендные признаки отсутствуют: «неизвестно» ≠ «дивиденда не будет».

Каждая строка несёт `feature_known_at`; `feature_known_at > as_of` — жёсткая ошибка
(`LookaheadError`), а не предупреждение.

---

## 6. Dataset V3 readiness

`application/readiness.py` — измерение, а не датасет: `DatasetSpec` не создаётся и не меняется
(`dataset_spec_mutated: false`). Целевые исследовательские спеки
(`ABSOLUTE_RETURN_20D`, `EXCESS_VS_CASH_20D`, `TOP20_20D`, `EXCESS_VS_IMOEX_20D`)
хранятся только как метаданные.

---

## 7. CLI

```bash
docker compose exec backend python -m app.modules.fundamentals.cli audit
docker compose exec backend python -m app.modules.fundamentals.cli sync-identity [--symbols SBER,GAZP] [--dry-run]
docker compose exec backend python -m app.modules.fundamentals.cli sync-events [--dry-run]
docker compose exec backend python -m app.modules.fundamentals.cli status
docker compose exec backend python -m app.modules.fundamentals.cli backfill
```

`backfill` = metric registry + identity + corporate events; отчётность и дивиденды
записывают DEFERRED-run с причиной и ничего не пишут.

## 8. API

`GET /api/v1/fundamentals/{status,sources/audit,coverage,readiness,quality,metrics,issuers,mappings,dividends,events}`,
`GET /api/v1/fundamentals/issuers/{issuer_id}/reports?as_of=`,
`GET /api/v1/fundamentals/features/{fundamental-daily,event-daily}?as_of=`.

Пустые данные отдаются как `NOT_READY` с причиной, а не как правдоподобная пустая структура.

## 9. Celery

`projectai.update_fundamental_data` — тонкая задача: при `FUNDAMENTALS_UPDATE_ENABLED=false`
возвращает `DISABLED`, при `true` выполняет только identity + corporate events.
В `beat_schedule` не регистрируется.

---

## 10. Честное покрытие (на 2026-09-05)

| Данные | Факт |
| --- | --- |
| Эмитенты | 36 на 40 инструментов текущей когорты |
| `security_issuer_mappings` | 40 MAPPED (100 % когорты), 0 AMBIGUOUS / UNMAPPED |
| `corporate_events` | 5 (проекция SPLIT / REVERSE_SPLIT) |
| `financial_reports` / `financial_facts` | 0 — нет принятого источника |
| `dividend_events` | 0 — оба ISS-эндпоинта отклонены аудитом |
| Readiness | `PARTIAL`: `event_daily` материализуется, `fundamental_daily` — нет |

Эмитентов меньше, чем инструментов, потому что привилегированные и обыкновенные акции одного
эмитента (SBER/SBERP, TATN/TATNP и т. д.) ссылаются на один `moex_emitent_id`.

## 11. Что нужно, чтобы слой стал полезным

1. Легальный источник отчётности с доказуемой датой публикации (лицензированный фид или API).
2. Источник дивидендов с датами рекомендации / утверждения / фиксации.
3. Отдельная задача нормализации банков (`applies_to_banks`).
4. Только после этого — обсуждение Dataset V3 и обучение.
