# Public Data Source Audit V1 — бесплатные источники для Fundamentals / Dividends / Total Return

**Статус:** research only  
**Дата живых проб:** 2026-09-08  
**Ветка / worktree:** `research/public-data-source-audit-v1` @ `71caeb3`  
(`E:\!AI\ProjectAI-wt-public-data-source-audit-v1`)  
**Принцип:** только бесплатные публичные данные. Платные API = `REJECTED`.  
**Production code:** не менялся.

Артефакты (локально, `.tmp/` gitignored):  
`.tmp/public-data-source-audit-v1/*.json` + `samples/`.

---

## 1. Executive summary (READY / PARTIAL / BLOCKED)

| Область | Вердикт | Комментарий |
|---|---|---|
| Issuer identity (MOEX) | **READY** | `emitent_id` / INN / ISIN уже в архитектуре Fundamentals V1 |
| Market prices / listings / survivorship snapshots | **READY** | ISS history + listing-by-date |
| Mechanical CA (splits) | **READY** | `/iss/statistics/engines/stock/splits.json` (не путать с false-positive path) |
| Bond reference / OFZ curve / coupons | **READY** | bondization + ZCYC history |
| Macro hurdle (CBR key rate / FX / RUONIA) | **READY** / RUONIA CONDITIONAL | уже в стеке ProjectAI |
| Industrial RAS fundamentals (FNS GIR BO) | **PARTIAL → READY candidate** | публичный JSON с датами подачи; глубина ~2021–2025; не все blue-chips находятся по INN |
| Bank / FI fundamentals | **BLOCKED** (отдельная семантика) | SBER в GIR BO search = 0 hits |
| IFRS structured free feed | **BLOCKED** | в FNS BFO нет; IR = RESEARCH_ONLY |
| Dividends PIT feed | **BLOCKED** | MOEX «dividends» = false positive; IR/e-disclosure ещё не provider |
| Credit ratings (ratings.cbr.ru) | **PARTIAL (human) / BLOCKED (machine)** | сайт публичный, JSON API за CSRF+captcha |
| Gross Total Return | **BLOCKED** | нет accepted dividend events |
| Dataset V3 (features+labels с TR/deep fundamentals) | **PARTIAL / gated** | RAS features условно с ~2022; TR labels — нет |

**Топ бесплатных источников для Kraken сейчас:**

1. **MOEX ISS** — рынок, identity, сплиты, листинги, OFZ/ZCYC, ISSUESIZE snapshot  
2. **CBR** — KEY_RATE / FX / RUONIA  
3. **FNS GIR BO (`bo.nalog.gov.ru/nbo/...`)** — RAS отчётность + `actualBfoDate` / `datePresent`  
4. **e-disclosure.ru** — кандидат на события/дивиденды (нужен отдельный spike)  
5. **IR сайты** — только research/fallback, не единый provider  

---

## 2. Что уже есть в Kraken (не reinvent)

Прочитаны и учтены:

- `docs/fundamentals/fundamental-event-data-v1.md` — схема `fundamentals.*`, PIT `known_at`, audit SOURCE_FINDINGS  
- `docs/architecture/dividend-total-return-data-v2.md`, `docs/research/dividend-pit-readiness-v1.md`, ADR 0010  
- `docs/architecture/decisions/0005-raw-market-corporate-actions-returns.md`  
- `docs/research/credit-quality-v0.md`  
- curated `research_equity_v1` seed в `backend/app/modules/market/universe.py` (**не изменялся**)

Вывод: рекомендации должны **наполнять** уже спроектированные порты/таблицы (`financial_reports`, `dividend_events`, DividendProvider), а не плодить параллельную модель.

---

## 3. Fundamentals — ответы на ключевые вопросы

### Можно ли автоматизировать десятки–сотни эмитентов бесплатно?

**Да, условно (industrials)** через FNS GIR BO:

- Search: `/advanced-search/organizations/search?query={INN}`  
- Card: `/nbo/organizations/{id}`  
- Reports: `/nbo/organizations/{id}/bfo/` → JSON со вложенными `balance` / `financialResult` / `capitalChange` / `fundsMovement`  
- Auth: **NONE** (логин не требовался в пробах)  
- PIT-якоря: `actualBfoDate`, `datePresent`, correction dates  

**Ограничения:**

- Online глубина у probed имён ≈ **2021–2025**, не 2014+  
- **SBER (банк)** — `NOT_FOUND` в GIR BO  
- ROSN / NVTK / GMKN / PLZL — INN search пустой в этой пробе (нужен entity-resolution: холдинг vs операционная компания / иной ИНН)  
- IFRS как структурированный фид — **не найден**  
- Вложения PDF/XBRL имеют `fileToken`; стабильный download path в аудите **не закрыт** (но строки отчёта уже в JSON)

### Банки отдельно?

Да. Research-only разделение:

- `INDUSTRIAL_FUNDAMENTALS` ← FNS RAS  
- `FINANCIAL_INSTITUTION_FUNDAMENTALS` ← отдельный контур (CBR bank reporting / XBRL catalogs) — **ещё не READY**

Это согласуется с осторожным `applies_to_banks` в metric registry Fundamentals V1.

### Representative live tests

| SECID | FNS search | BFO periods | Вердикт |
|---|---|---|---|
| LKOH | hit org 6681478 | 2021–2025 | ACCEPTED |
| GAZP | hit | 2021,2023–2025 | ACCEPTED |
| MGNT | hit | 2021–2025 | ACCEPTED |
| YDEX | hit (новый юрлицо) | 2023–2025 | CONDITIONAL |
| SBER | 0 hits | — | NOT_FOUND (FI) |
| TATN | hit | 2021–2025 | ACCEPTED |

Sample: `.tmp/.../samples/fns-lkoh-report-sample.json`

---

## 4. Dividends — вердикт

| Источник | Статус | Auth |
|---|---|---|
| MOEX `/securities/{SECID}/dividends.json` | **REJECTED** (false positive: description/boards) | NONE |
| MOEX `history/.../dividends` | **REJECTED** (candles) | NONE |
| Issuer IR (LKOH XLS и др.) | **RESEARCH_ONLY** | NONE |
| e-disclosure | **CONDITIONAL** | PUBLIC_SESSION |
| Accepted Kraken provider | **нет** | — |

**Итог:** дивидендный PIT-фид для production ingest **не готов**. Схема `dividend_events` готова, провайдер — нет.

Ex-date derivation от record_date при известном settlement cycle:

- до **2023-07-31**: equities **T+2**  
- с **2023-07-31**: equities **T+1**  
(официальные материалы MOEX; рублёвые облигации были T+1 раньше)

Это **не заменяет** источник событий, а только помогает, когда есть `record_date`.

---

## 5. Credit — ratings.cbr.ru

| Вопрос | Ответ |
|---|---|
| Сайт публичный? | Да (HTTP 200) |
| Machine-consumable без captcha? | **Нет** |
| Механизм | Bitrix `runComponentAction('prr.form','searchRating')` + CSRF + captcha |
| Статус | **CONDITIONAL** (human UI) / automation **RESEARCH_ONLY** |
| Покупать платный рейтинг-фид? | **Нет** (`REJECTED_PAID`) |

Для Kraken credit layer: оставить честный `UNKNOWN` / `READY_REQUIRES_ACCESS`, не симулировать score.

---

## 6. Macro

| Серия | Статус |
|---|---|
| CBR KEY_RATE / FX | ACCEPTED |
| RUONIA | CONDITIONAL (best-effort) |
| MOEX OFZ ZCYC history | ACCEPTED |
| Rosstat | CONDITIONAL (SSL fail в среде аудита) |
| Fedstat | RESEARCH_ONLY |

Рекомендуемый macro stack для Kraken: **оставить CBR + MOEX curve**, Rosstat не блокирует.

---

## 7. PIT table (кратко)

| Тип знания | Economic date | known_at candidate | Качество |
|---|---|---|---|
| RAS report (FNS) | `period` year-end | `actualBfoDate` / `datePresent` | хорошее для online window |
| Split (MOEX stats) | `tradedate` | сейчас = effective (conservative) | без announcement date |
| Dividend | ex/record/pay | disclosure timestamp | **нет accepted source** |
| Rating (CBR UI) | assignment date | UI history (если доступна) | automation blocked |
| Macro CBR | observation date | publication of series | READY |

---

## 8. Identity & coverage research equities

- Join **MOEX emitent_inn → FNS** работает для части universe.  
- `research_equity_v1` (~40 equities в `universe.py`) **не модифицировался**.  
- Survivorship: ISS `history/.../securities.json?date=` даёт дневной universe → поиск delisted **возможен**.  
- Shares outstanding: `ISSUESIZE` snapshot на board endpoint; **исторической серии в ISS history columns не видно**.

---

## 9. Total Return

**Вердикт: NOT_READY**

Готово: цены, сплиты, формула gross TR в коде, ADR 0010.  
Не готово: cash dividends store / provider.

---

## 10. Dataset V3 feasibility

| Старт | Оценка |
|---|---|
| RAS fundamental features (industrials, coverage mask) | условно с **~2022-03** (кластер первых `actualBfoDate`) |
| Deep history 2014+ fundamentals | **не готов** на FNS online window |
| Labels / features на gross TR | **BLOCKED** |
| Единый V3 «всё сразу» | **не открывать** |

**Blockers:** dividends; FI semantics; INN gaps; shallow FNS depth; IFRS absence.

---

## 11. Recommended Free Kraken Data Stack

| Слой | Источник | Статус |
|---|---|---|
| Prices / boards / identity | MOEX ISS | ACCEPTED |
| Splits | MOEX ISS statistics/splits | ACCEPTED |
| Macro hurdle | CBR | ACCEPTED |
| OFZ curve / bond CF ref | MOEX ZCYC + bondization | ACCEPTED |
| Industrial RAS fundamentals | FNS GIR BO `/nbo/.../bfo/` | ACCEPTED (ingest candidate) |
| Dividends | e-disclosure spike → optional IR parsers | CONDITIONAL / RESEARCH_ONLY |
| Credit ratings | ratings.cbr.ru | CONDITIONAL (no captcha bypass) |
| IFRS | IR filings | RESEARCH_ONLY |
| Paid vendors | — | REJECTED |

---

## 12. Implementation order (research → later product scopes)

1. **S** — зафиксировать FNS API contract + false-positive guards в docs/audit registry  
2. **M** — `fundamentals-ras-fns-ingest-v1` (industrials only, PIT dates, no Dataset bump)  
3. **M/L** — `dividend-disclosure-provider-spike-v1` (e-disclosure HTML/XHR + settlement calendar)  
4. **L** — FI fundamentals research (CBR bank reports)  
5. **L/XL** — coverage backfill / entity resolution for missing INNs; only then Dataset V3 discussion  
6. **Never in free stack** — paid ratings/dividend vendors; captcha bypass

Effort: S/M/L/XL as above.

---

## 13. Confidence

| Утверждение | Confidence |
|---|---|
| MOEX dividends endpoint false positive | **High** (live identical payload) |
| FNS BFO JSON usable for RAS + dates | **High** (full statements in response) |
| FNS covers all research equities | **Low–Medium** (several misses) |
| Banks absent from GIR BO | **High** for SBER probe; generalize carefully |
| ratings.cbr.ru automation | **High** that captcha blocks naive API |
| e-disclosure as dividend provider | **Medium** (access CONDITIONAL; parser not built) |
| TR NOT_READY | **High** |
| Dataset V3 earliest RAS ~2022 | **Medium** (based on observed online depth) |

---

## 14. What NOT to use

- MOEX paths `.../dividends.json`, `.../corporateactions.json`, `.../securities/{SECID}/splits.json` как источник событий (false positives / wrong payloads)  
- Платные API/подписки  
- Captcha bypass / credential stuffing на e-disclosure или ratings.cbr.ru  
- Подстановка fabricated `known_at` / ex_date  
- Смешение bank и industrial fundamentals в один metric pack без версии  
- Автоматический Dataset V3 / Shadow / Candidate на «почти готовых» дивидендах  

---

## 15. Артефакты

| Файл | Назначение |
|---|---|
| `.tmp/public-data-source-audit-v1/source-matrix.json` | матрица источников |
| `fundamental-coverage.json` | fundamentals / FNS |
| `dividend-source-coverage.json` | дивиденды |
| `xbrl-audit.json` | XBRL/XSD |
| `macro-source-matrix.json` | макро |
| `cross-source-identity.json` | identity / T+1 |
| `total-return-feasibility.json` | TR |
| `dataset-v3-feasibility.json` | Dataset V3 |
| `samples/` | FNS report slim, MOEX splits, LKOH XLS, e-disclosure HTML head, CBR ratings probe, XBRL schema head, OFZ bondization |

Пробы: `probe-*.json`, скрипты `probe_*.py` (research only).

---

## 16. Recommended next mega-scope name

**`fundamentals-ras-fns-ingest-v1`**  
параллельный spike: **`dividend-disclosure-provider-spike-v1`**

Не стартовать Dataset V3 / Total Return production ingest до закрытия dividend blocker.
