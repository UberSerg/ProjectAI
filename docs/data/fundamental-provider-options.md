# Источники фундаментальных данных (Provider Coverage V1.1)

Обзор кандидатов для Fundamental & Event Intelligence V1. Статусы честные: адаптер без
учётных данных ≠ REJECTED, если OpenAPI/публичный JSON существует.

## Сводная таблица

| Источник | Ценность | PIT | Покрытие | Автоматизация | Доступ | Стоимость (публично) | Приоритет |
|----------|----------|-----|----------|---------------|--------|----------------------|-----------|
| MOEX ISS | Идентичность эмитента по SECID | N/A (не отчётность) | Все торгуемые акции на MOEX | Работает сейчас | Публичный API | Бесплатно | **P0 — принят** |
| Интерфакс шлюз (gateway.e-disclosure.ru) | События раскрытия, файлы, СФ | `eventDate` — date-time (MSK) | Широкое по эмитентам РФ при активном договоре | OpenAPI + Bearer token | Договор + логин/пароль | Не публикуется — по договору с Интерфакс | **P1 — READY_REQUIRES_CREDENTIALS** |
| ГИР БО (bo.nalog.gov.ru) | БФО / РСБУ строки по ИНН (typeCorrections) | `actualBfoDate` — только дата | Частично: не все крупные эмитенты в публичном поиске | Публичный JSON + browser UA; bulk — заявка | Публичный partial; `/subscriptions` — заявка | Публичный просмотр; массовая выгрузка — отдельно | **P2 — READY (DATE_ONLY), off by default** |
| e-disclosure.ru (HTML) | То же доменное содержание | Теоретически timestamp в шлюзе | Широкое | Scraping | HTTP 403 для ботов | — | **Отклонён** — только шлюз |
| MOEX ISS dividends | Дивиденды | — | — | Эндпоинты не отдают таблицу | Публичный | Бесплатно | **Отклонён** |

## MOEX ISS

- **Ценность:** `emitent_id`, `emitent_inn`, `isin`, точное сопоставление SECID.
- **PIT:** не источник отчётности; для ML-фундаментала недостаточен.
- **Статус:** `READY`, используется в `sync-identity`.

## Интерфакс шлюз (e-disclosure Gateway)

- **Ценность:** лента `DisclosureEvent` (Publish/Change/Exclude/Restore/Delete), справочники
  типов сообщений/файлов, скачивание файлов по `uid`.
- **PIT:** `eventDate` → `known_at` / `published_at` с качеством `EXACT_TIMESTAMP`.
- **Покрытие:** зависит от договора; технически — все субъекты раскрытия в системе.
- **Автоматизация:** `POST /api/v1/auth`, paginated `GET /api/v1/disclosure/events`.
- **Доступ:** `EDISCLOSURE_GATEWAY_ENABLED=false` по умолчанию; нужны
  `EDISCLOSURE_GATEWAY_USERNAME` и `EDISCLOSURE_GATEWAY_SECRET`.
- **Стоимость:** коммерческий продукт Интерфакс; публичный прайс не фиксируем.
- **Приоритет:** первый целевой источник для PIT-безопасных событий раскрытия и отчётных файлов.

## ГИР БО

- **Ценность:** карточка организации, список БФО, **встроенные формы РСБУ** в
  `typeCorrections[].correction` (`balance` / `financialResult` / `fundsMovement` с кодами
  `current2110`, `current2400`, `current1600`, …). Детализация статей —
  `/nbo/details/{type}?id={correctionId}` (id БФО даёт `{}`).
- **PIT:** `actualBfoDate` — `DATE_ONLY`; `publishedCorrectionDate` для версий. Время не
  изобретаем. Агрегаты `actives`/`gainSum` без кода строки в канон не маппятся.
- **Покрытие:** проба GAZP (ИНН 7736050003, org `6622458`) — БФО + формы ok; SBER/LKOH/GMKN
  по ИНН в публичном поиске — часто пусто (банки/часть крупных эмитентов).
- **Автоматизация:** точный поиск по ИНН; fuzzy name отклоняется; bulk через UI подписок —
  `REQUIRES_APPLICATION` / `PAID_SUBSCRIPTION`.
- **Доступ:** `GIR_BO_ENABLED=false` по умолчанию; browser-like `GIR_BO_USER_AGENT`.
- **Стоимость:** публичный просмотр; массовая подписка — по правилам ФНС (без выдуманных цен).
- **Приоритет:** лучший кандидат на RAS-факты с DATE_ONLY PIT; для EXACT_TIMESTAMP событий —
  шлюз e-disclosure.

## Dataset V3 gate (критерии NOT_READY)

Измерение в `application/dataset_v3_gate.py`:

1. Привязка эмитентов ≥ 80% когорты.
2. ≥ 1 финансовый отчёт с PIT-safe источника.
3. ≥ 3 лет истории отчётности.
4. ≥ 50% отчётов с ключевыми метриками (REVENUE, NET_INCOME, TOTAL_ASSETS, TOTAL_EQUITY, CASH).
5. Преобладание `DATE_ONLY` known_at блокирует «полную» готовность.

Dataset V3 **не создаётся** этим модулем — только честный статус.

---

## Candidate V2 — чеклист данных (metadata)

Без обучения и без мутации Dataset V2:

- [ ] ≥ 80% инструментов когорты с `MappingStatus.MAPPED`
- [ ] Финансовые отчёты с доказуемым `known_at` (Gateway preferred)
- [ ] ≥ 3 календарных года отчётности на эмитента (целевой минимум)
- [ ] Core metrics normalized: REVENUE, NET_INCOME, TOTAL_ASSETS, TOTAL_EQUITY, CASH
- [ ] Unit scale явный и согласованный (без silent rescale)
- [ ] Dividend events с announcement date — отдельный источник (пока DEFERRED)
- [ ] Corporate events SPLIT projected с documented `known_at_basis`
- [ ] PIT preview `fundamental_daily` / `event_daily` без нарушений
- [ ] Provider matrix: ни один UNAVAILABLE не стирает уже ingested данные
- [ ] Walk-forward evaluation plan зафиксирован до pin Candidate V2 spec
