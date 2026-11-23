# Illustrations

Визуальные ориентиры KRAKEN Vault: схемы для быстрого входа в тему.

**Обновлено:** 2026-11-23  
**Файлов JPG:** 70  
**Заметок со встроенной картинкой:** ~110 (из ~237 содержательных)

## Политика

- Картинка только там, где схема **реально помогает** понять идею.
- Не иллюстрировать каждую карточку бага / задачи / исторического события.
- Подписи по возможности **на русском**; английский — имена сущностей (`Shadow`, `PIT`, `NAV`, `LIVE`, `API`…).
- Стили могут отличаться (documentary / винтажная бумага / чистый flat) — это нормально.
- Это **не** скриншоты приёмки UI и **не** `review-artifacts` ProjectAI.
- Иллюстрация ≠ доказательство runtime / merge / Owner acceptance.

Эталон «винтажного» стиля: `antipatterny.jpg` («Антипаттерны как ловушки»).

## Как вставлять

В заметке после заголовка:

```markdown
## Визуальный ориентир

![Краткий alt](../_assets/illustrations/имя-файла.jpg)

*Одна строка смысла. Иллюстрация Vault.*
```

Относительный путь зависит от глубины заметки (`../`, `../../`, `../../../`).

Скрипты (справочно): `_meta/QA/insert_illustrations.py`, `insert_illustrations_batch2.py`, `insert_illustrations_final.py`.

## Каталог по разделам

### 00 — Главная

| Файл | Заметки |
|---|---|
| `vault-dom-navigaciya.jpg` | [[ДОМ]], [[Навигация по проекту]] |
| `kak-chitat-vault.jpg` | [[Как пользоваться Vault]] |
| `istochniki-istiny.jpg` | [[Источники истины]] |
| `glossariy.jpg` | [[Глоссарий]] |
| `tri-knigi-uchet.jpg` | [[Kraken за 30 минут]], [[Personal vs Shadow vs Research]] |

### 01 — Продукт

| Файл | Заметки |
|---|---|
| `chto-takoe-kraken.jpg` | [[Что такое Kraken]] |
| `zachem-kraken.jpg` | [[Зачем существует Kraken]] |
| `kraken-segodnya.jpg` | [[Kraken сегодня]] |
| `idealnyy-kraken.jpg` | [[Kraken в будущем]], [[Идеальный Kraken]] |
| `osnovnye-vozmozhnosti.jpg` | [[Основные возможности]] |
| `chto-eshche-net.jpg` | [[Что пока не реализовано]] |
| `snowball-bez-brokera.jpg` | [[Конкурентное позиционирование]] |
| `scenarii-praktika.jpg` | [[Пользовательские сценарии]], [[Индекс сценариев]] |

### 02 — Архитектура

| Файл | Заметки |
|---|---|
| `kraken-runtime-topology.jpg` | [[Карта всей системы]] |
| `sloi-arhitektury.jpg` | [[Слои архитектуры]], [[Модули]], [[Modular monolith]], [[Как устроен код]] |
| `potoki-dannyh.jpg` | [[Потоки данных]] |
| `docker-servisy.jpg` | [[Docker и сервисы]], [[Инфраструктура]], [[Docker-first]] |
| `invarianty-principy.jpg` | [[Архитектурные принципы]] |
| `hranilishcha.jpg` | [[Хранилища]] |
| `shadow-portfel.jpg` | [[Shadow-портфель]], [[Shadow]], [[Shadow portfolio]], сценарий Shadow |
| `lichnyy-portfel.jpg` | [[Персональный портфель]], [[Personal portfolio]] |
| `zhurnal-resheniy.jpg` | [[Журнал решений]] |
| `ruchnoy-zhurnal.jpg` | [[Ручной журнал операций]] |
| `portfolio-hub.jpg` | [[Portfolio Hub]] |
| `rynochnye-dannye.jpg` | [[Рыночные данные]] |
| `pamyat-resheniy.jpg` | [[Память решений]], [[Decision Memory DB]] |
| `dataset-spec.jpg` | [[Датасет]], [[Dataset Spec]] |
| `prognoz-politika-risk.jpg` | [[Прогноз]], [[Торговая политика]], [[Риск]], [[Исполнение]] |
| `company-intelligence.jpg` | [[Company Intelligence]], сценарий «совет» |
| `research-evidence.jpg` | [[Исследования]], [[Research Evidence Engine]], антипаттерн Research |
| `istoricheskiy-simulyator.jpg` | [[Исторический симулятор]] |
| `fundamental.jpg` | [[Фундаментал]] |
| `korporativnye-deystviya.jpg` | [[Дивиденды и корпоративные действия]], [[Corporate actions]], антипаттерн дивидендов |
| `frontend-backend.jpg` | [[Frontend]], [[Backend API]] |

### 03 — Термины

| Файл | Заметки |
|---|---|
| `point-in-time.jpg` | [[Point-in-Time (PIT)]] |
| `look-ahead.jpg` | [[Look-ahead leakage]], [[Подглядывание в будущее]] |
| `evidence-level.jpg` | [[Evidence level]] |
| `known-at-effective.jpg` | [[known_at vs effective_date]] |
| `reshenie-zayavka-fill.jpg` | [[Decision vs Order vs Fill]], [[Решение принято за сделку]] |
| `candidate-champion.jpg` | [[Candidate vs Champion]], сценарий кампании |
| `live-vs-replay.jpg` | [[LIVE vs COUNTERFACTUAL_REPLAY]] |
| `net-ceny-ne-nol.jpg` | [[Missing price ≠ zero]], [[Фейковый ноль]] |
| `nav-polnyy-chastichnyy.jpg` | [[NAV и Partial NAV]], [[Ошибочная оценка NAV]] |
| `sebestoimost-pnl.jpg` | [[Cost basis]], [[Realized vs Unrealized P&L]], сценарий взноса |
| `xirr.jpg` | [[XIRR]] |
| `komissii-dvoynoy-uchet.jpg` | [[Комиссии и двойной учёт]], [[Двойной учёт комиссий]] |
| `moex-eod.jpg` | [[MOEX EOD]] |
| `syrie-svechi.jpg` | [[Raw candles]] |
| `total-return.jpg` | [[Total return]] |
| `walk-forward.jpg` | [[Walk-forward]] |
| `user-owner-mode.jpg` | [[USER vs OWNER mode]] |

### 04 — История

| Файл | Заметки |
|---|---|
| `hronologiya-kraken.jpg` | [[Хронология Kraken]], [[Ключевые этапы]] |
| `istoriya-versiy.jpg` | [[История версий]] |

### 05–08 — Проблемы, бэклог, план, будущее

| Файл | Заметки |
|---|---|
| `katalog-problem.jpg` | [[Все проблемы]] |
| `kriticheskie-problemy.jpg` | [[Критические проблемы]] |
| `antipatterny.jpg` | [[Индекс антипаттернов]] |
| `stale-docker-mount.jpg` | [[Устаревший Docker mount]] |
| `gorizonty-backlog.jpg` | [[Сейчас]], [[Следующее]], [[ВЕСЬ БЭКЛОГ]] |
| `otlozheno-bez-owner.jpg` | [[Позже]], [[Заблокировано]], [[Отложенные идеи]], [[Возможные модули]], [[Правила безопасности]] |
| `roadmap-gates.jpg` | [[Roadmap Kraken]], [[Критический путь]] |
| `zavisimosti-etapov.jpg` | [[Зависимости этапов]], [[План текущего этапа]] |
| `granicy-avtonomii.jpg` | [[Автономность и ограничения]] |

### 10 — Сценарии

| Файл | Заметки |
|---|---|
| `scenariy-pervaya-pokupka.jpg` | [[Сценарий — журнал от взноса до частичной продажи]] |
| `scenariy-tri-daty.jpg` | [[Сценарий — три даты одного следа]] |
| `scenariy-net-ceny.jpg` | [[Сценарий — нет цены, оценка частичная]] |
| `dva-portfelya.jpg` | [[Сценарий — два личных портфеля]] |

### 11 — Разработчикам

| Файл | Заметки |
|---|---|
| `pervyy-den-razrab.jpg` | [[Первый день разработчика]] |
| `git-worktrees.jpg` | [[Git и worktrees]] |
| `definition-of-done.jpg` | [[Definition of Done]] |

## Не используется в заметках

| Файл | Примечание |
|---|---|
| `kraken-three-books.jpg` | Ранний EN-вариант; в заметках заменён на `tri-knigi-uchet.jpg`. Можно удалить позже. |

## Добавление новой картинки

1. Положить JPG сюда: `_assets/illustrations/<slug>.jpg`
2. Вставить в **одну** (или две родственные) заметки
3. Дописать строку в таблицу этого README
4. Не плодить картинки «на каждую подстраницу» без нужды
