# ProjectAI — AI Development Workflow

## Назначение

ProjectAI разрабатывается в связке:

- владелец проекта определяет цели и принимает продуктовые решения;
- ChatGPT используется для архитектуры, декомпозиции, технического ревью и подготовки заданий;
- Cursor выполняет реализацию;
- GitHub является общей точкой фиксации кода, diff, Pull Request и истории решений.

Основной цикл разработки:

```text
architecture discussion
  → bounded Cursor task
  → implementation
  → tests / acceptance (with timeout)
  → report
  → review
  → fix
  → commit / PR
```

Owner → ChatGPT → Cursor → Tests → Git commit → GitHub Pull Request → Review → Fixes → Merge.

Cursor не должен самостоятельно начинать следующий функциональный этап после завершения текущего задания.

Долгосрочная цель продукта и архитектурные инварианты: `docs/architecture/future-intelligence-roadmap.md`
и `.cursor/rules/00-project-core.mdc`. Зрелое состояние системы называется **Kraken** (концепт, не модуль).

---

## 1. Источник требований

Для каждой задачи приоритет следующий:

1. Текущее явно сформулированное задание пользователя.
2. Project Rules в `.cursor/rules/`.
3. Актуальная документация в `docs/`.
4. Существующая архитектура и ADR.
5. Старые/legacy документы.

Если старый документ противоречит новой архитектуре, нельзя молча возвращать старое решение.

При существенном противоречии нужно указать его в итоговом отчёте.

---

## 2. Главный архитектурный принцип

ProjectAI развивается как модульный монолит.

Не создавать микросервисы без реальной необходимости.

Основные границы:

- domain;
- application;
- infrastructure;
- API;
- modules;
- workers;
- frontend.

Бизнес-логика не должна напрямую зависеть от:

- FastAPI;
- SQLAlchemy;
- Redis;
- Celery;
- конкретной LLM;
- конкретной ML-библиотеки;
- внешнего HTTP API.

Использовать dependency inversion там, где компонент действительно предполагается заменяемым.

Не создавать абстракции ради абстракций.

---

## 3. Сменные компоненты

Архитектура должна позволять заменять реализации без переписывания вызывающего кода.

Примеры:

TechnicalModel
- RuleBasedModel
- CatBoostModel
- XGBoostModel

PortfolioPolicy
- RuleBasedPolicy
- ContextualBanditPolicy

**Naming note:** today's domain port `PortfolioPolicy` maps conceptually to future
**Trading Policy** (desired action proposal). It is **not** Portfolio Manager, Risk Manager,
or Execution Adapter. Portfolio state / virtual portfolio persistence and broker execution
remain separate concerns.

LLMProvider
- PolzaProvider

MarketDataProvider
- MoexIssProvider
- CbrProvider
- будущие источники

Сначала используется простая реализация.

Более сложная добавляется только тогда, когда появились данные и доказана необходимость.

---

## 4. Принцип развития

Не реализовывать будущие этапы заранее.

Правило:

> Build for extension, not speculation.

Можно подготовить корректную границу будущего компонента.

Нельзя создавать десятки пустых классов, сервисов и generic framework только потому, что они потенциально понадобятся через год.

Большие этапы дробить на **bounded phases** с явным DoD. Увидев в roadmap Simulator / Meta Model /
Broker / Fundamentals / Market Regime, Cursor не должен начинать их «заодно» с текущей задачей.

---

## 5. Data-first

ProjectAI является data-driven системой.

Любая модель или аналитический алгоритм должен иметь воспроизводимый источник данных.

Сырые данные по возможности сохраняются отдельно от нормализованных.

Основной принцип (упрощённый data umbrella):

RAW
→ NORMALIZED
→ FEATURES
→ ANALYTICS
→ DECISION
→ OUTCOME
→ LEARNING

`DECISION` здесь — зонтичный этап, а не один monolith-сервис. Целевой decision path
(см. `docs/architecture/future-intelligence-roadmap.md`):

Prediction → Trading Policy → Risk Manager → Order Intent → Execution Adapter

Meta Model оценивает полезность/доверие к агентам и моделям; она не подменяет Policy,
Risk или Execution.

Производные данные не должны уничтожать исходные.

---

## 6. ML

LLM не используется для задач, которые надёжнее и дешевле решаются:

- математикой;
- SQL;
- статистикой;
- обычными алгоритмами;
- локальными ML-моделями.

ML-модель не заменяется новой только потому, что новая версия дала красивый результат.

Будущий lifecycle модели:

```text
Training Dataset
→ Candidate
→ Backtest / Walk-forward
→ Candidate vs Champion
→ Accept / Reject / Rollback
```

Историческая оценка — walk-forward (train on past → evaluate on unseen future).
Повторные прогоны одного и того же известного периода не считаются независимым рыночным опытом.

Модели должны иметь версии.

Результаты прогнозов должны быть воспроизводимы относительно версии модели.

Prediction Model не равен Trading Policy / Risk / Execution — см. core rules.

---

## 7. LLM

Внешние LLM ProjectAI вызываются через Polza API.

Domain-код не должен зависеть от конкретной модели Polza.

LLM используется преимущественно для:

- понимания текста;
- анализа событий и новостей;
- сложной интерпретации;
- формирования экспертного заключения;
- анализа накопленного опыта.

LLM не должна использоваться для:

- вычисления RSI;
- корреляций;
- SQL-агрегаций;
- простых классификаций, которые можно выполнить локально;
- задач, где deterministic алгоритм даёт тот же результат.

Принцип:

> Не экономить на интеллекте, но не тратить дорогой интеллект на механическую работу.

---

## 8. Decision Memory

Decision Memory — самостоятельный домен и отдельная PostgreSQL DB + pgvector.

В ней в будущем хранятся immutable snapshots:

- Decision / Prediction;
- версии моделей, features, dataset;
- market / agent / portfolio state;
- Trading Policy / Risk / Order Intent / Execution / costs;
- Outcome / PnL / drawdown / Evaluation;
- Review / lesson;
- embeddings where useful.

Нельзя задним числом переписывать первоначальное решение после появления результата.

Decision и subsequent review — разные сущности.

Decision Memory **не заменяет** обычные ML datasets / feature store.

Подробнее: `docs/architecture/future-learning.md`.

---

## 9. Реальные деньги

На текущем этапе ProjectAI не совершает реальные брокерские операции.

Система должна сначала доказать себя в Historical Simulator / Paper / Signal Mode.

В будущем допускается read-only получение реального пользовательского портфеля.

Путь к реальному исполнению: Simulation → walk-forward → Shadow/Paper → Signal →
human-confirmed broker → small capital → limited autonomy.

Broker API появляется только как Execution Adapter и не должен требовать переписывания
prediction / policy / risk.

Любая возможность реальной автоматической торговли является отдельным будущим архитектурным
и security-этапом и не должна появляться случайно в рамках другой задачи.

---

## 10. Frontend

Frontend — ProjectAI Control Center.

Он нужен не только для отображения результата, но и для прозрачности работы системы.

Через UI пользователь должен постепенно иметь возможность видеть:

- состояние системы;
- рыночные данные;
- workflows;
- модели;
- рекомендации;
- факторы рекомендации;
- Decision Memory;
- виртуальный портфель;
- результаты обучения.

Frontend не выполняет тяжёлые расчёты.

Основная схема:

Workers
→ DB
→ API
→ Browser

UI общается с системой только через API.

---

## 11. Язык UI

Пользовательский интерфейс ProjectAI — русский.

Не переводятся технические идентификаторы:

- тикеры;
- валютные коды;
- MOEX;
- UUID;
- model IDs;
- API technical names.

Backend enums не переводятся ради UI.

Перевод выполняется presentation layer frontend.

---

## 12. Docker

Проект Docker-first.

Локальная разработка и будущий deployment должны использовать максимально одинаковое окружение.

Не требовать ручной установки PostgreSQL, Redis и backend dependencies в Windows.

Persistent data должны находиться в volumes или внешних storage.

Секреты не хранятся в Git.

---

## 13. Базы данных

Текущая архитектура:

Core PostgreSQL
- market
- analytics
- portfolio
- learning
- system

Memory PostgreSQL
- Decision Memory
- embeddings

Не смешивать Memory DB с основной рыночной БД без отдельного архитектурного решения.

Redis не является постоянным хранилищем бизнес-данных.

---

## 14. Миграции

Изменения схемы БД выполняются через Alembic.

Не использовать `create_all()` как production migration mechanism.

Миграции должны работать на чистой БД.

Existing migration history не переписывать без чрезвычайной причины.

---

## 15. Производительность

Не выполнять тяжёлые вычисления во время открытия страницы frontend.

Избегать:

- N+1;
- поштучных INSERT при массовой загрузке;
- загрузки огромных dataset в браузер;
- синхронных долгих операций внутри HTTP request.

Использовать workers для тяжёлых задач.

Оптимизировать реальные bottleneck, а не предполагаемые.

---

## 16. Background jobs

Тяжёлые операции выполняются через worker.

HTTP API должно:

1. проверить запрос;
2. создать workflow/job;
3. поставить работу в очередь;
4. вернуть ID.

Долгий расчёт не должен держать HTTP request открытым.

Acceptance / backfill / длинные pytest / Docker jobs обязаны иметь:

- hard timeout или watchdog;
- poll interval;
- stale detection;
- non-zero exit code при failure.

Нельзя часами polling-ить без deadline.

Background agents не должны незаметно продолжать следующий scope после остановки задачи пользователем.

---

## 17. Workflows

Значимые фоновые процессы должны быть наблюдаемыми.

Минимально:

- type;
- status;
- start;
- finish;
- steps;
- errors.

В UI технические имена преобразуются в человекочитаемые.

---

## 18. Ошибки

Не скрывать ошибки.

Не превращать реальную ошибку в warning только ради зелёного dashboard.

Ошибки внешнего API должны:

- иметь timeout;
- иметь ограниченный retry;
- логироваться;
- попадать в workflow/batch;
- быть понятны пользователю через UI.

---

## 19. Код

Не создавать файлы-комбайны.

Избегать:

- god classes;
- огромных `utils.py`;
- `dict[str, Any]` как основного domain contract;
- магических строк;
- копирования одинаковой логики;
- скрытых side effects.

Использовать конкретные типы и небольшие сущности.

Но не дробить простой код на десятки бессмысленных классов.

---

## 20. Scope control

Каждое задание имеет scope.

Большие roadmap-этапы дробить на bounded phases с явным DoD.

Cursor не должен в процессе задачи самостоятельно добавлять:

- новый аналитический модуль;
- новую ML-модель;
- новый источник данных;
- LLM-функционал;
- trading logic / broker / simulator;
- новую инфраструктурную технологию,

если этого явно не требует задача.

Если обнаружено полезное улучшение вне scope:

1. не реализовывать его;
2. записать в `Possible follow-ups` итогового отчёта.

После interrupt / aborted background task:

1. сначала recovery audit working tree (status, diff summary, что успел сделать background task);
2. не auto-revert без запроса;
3. не начинать новую реализацию, пока пользователь не подтвердил план recovery.

---

## 21. Git workflow

Новый функциональный этап выполняется в feature-ветке.

Не работать напрямую в `main`, если явно не указано обратное.

Обычный цикл:

main
→ feature branch
→ implementation
→ tests
→ commit
→ push
→ Pull Request
→ review
→ fixes
→ merge

Не выполнять:

- force push;
- reset чужой истории;
- переписывание main;
- автоматический merge,

без явного указания пользователя.

---

## 22. Commits

Commit должен описывать одну логическую работу.

Не делать commit с сообщением:

`changes`

Предпочтительно:

- `feat: ...`
- `fix: ...`
- `refactor: ...`
- `test: ...`
- `docs: ...`
- `chore: ...`

---

## 23. Tests

Новый функционал должен сопровождаться тестами там, где это разумно.

Перед объявлением задачи завершённой выполнить применимые проверки:

Backend:
- tests;
- lint.

Frontend:
- tests;
- production build.

Infrastructure:
- docker compose validation;
- health checks при изменении runtime.

Нельзя писать в отчёте "всё работает", если проверки фактически не выполнялись.

---

## 24. External APIs in tests

Обычный unit/integration test suite не должен зависеть от доступности внешнего API.

MOEX, CBR, Polza и другие внешние источники должны mock/fixture'иться в deterministic tests.

Live external tests выполняются отдельно.

---

## 25. Security

Не коммитить:

- API keys;
- PAT;
- passwords;
- `.env`;
- broker tokens;
- private credentials.

Не выводить секреты через:

- API;
- frontend;
- logs;
- health endpoints.

---

## 26. Documentation

При существенном архитектурном изменении обновить соответствующую документацию.

Для значимого архитектурного решения использовать ADR.

**Типы документов:**

- **Layer / status docs** (например `technical-agent-v1.md`, `analytics-feature-layer.md`,
  `overview.md`) — описывают **реализованную** семантику и текущее состояние слоя.
- **Roadmap / research docs** (например `future-intelligence-roadmap.md`,
  `market-regime-v0-research.md`, `future-learning.md`) — описывают **направление**,
  planned stages и research; не считать их автоматически shipped.

Legacy документация не должна восприниматься как текущая спецификация.

---

## 27. Работа с неуверенностью

Если Cursor не уверен в:

- бизнес-логике;
- источнике данных;
- destructive migration;
- изменении архитектурной границы;
- внешнем API;
- последствиях изменения,

нельзя молча выбрать рискованный вариант.

Нужно остановиться и явно описать вопрос пользователю.

Для простых локальных технических решений можно самостоятельно выбрать стандартный подход.

---

## 28. Definition of Done

Перед завершением задачи Cursor должен проверить:

- реализован ли весь заявленный scope;
- не реализовано ли лишнее;
- проходят ли tests;
- проходит ли lint/build;
- работает ли Docker, если задача его затрагивала;
- актуальна ли документация;
- нет ли секретов в diff.

---

## 29. Итоговый отчёт Cursor

После реализации выдавать короткий структурированный отчёт.

Минимум:

### Implemented
Что реально сделано.

### Tests
Какие проверки реально запускались и результат.

### Git
Branch и commit.

### Deviations
Отклонения от задания — честно, без маскировки.

### Issues
Нерешённые проблемы и known issues.

### Possible follow-ups
Полезные идеи вне текущего scope.

После отчёта не начинать следующую задачу самостоятельно. Не начинать следующий roadmap stage автоматически.

---

## 30. Review cycle

После push код может проходить внешний архитектурный review.

Замечания review должны исправляться отдельным небольшим изменением.

Не использовать review как повод переписать рабочую архитектуру целиком, если замечание локальное.

Цель процесса:

> маленькие проверяемые изменения вместо больших непроверяемых прыжков.
