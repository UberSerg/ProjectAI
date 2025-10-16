# Инвестиционный советник: Система рекомендаций на основе ИИ

## Обзор
Этот репозиторий содержит документацию для desktop-приложения для среднесрочного инвестирования на Московской бирже (MOEX) с ИИ-советником. Приложение будет давать утренние рекомендации "купить/продать/держать" на основе технического анализа, анализа новостей и моделей машинного обучения (Scikit-learn: RandomForest, GradientBoosting, SVM). Поддерживает оффлайн-режим (DuckDB), импорт портфеля (CSV/XLSX), бэктестинг, бумажную торговлю и самообучение с обратной связью от пользователя.

- **Технологии**: Python 3.9+, PyQt5, DuckDB, Scikit-learn, pandas_ta, feedparser, schedule, pydantic, pytest.
- **Архитектура**: Модульный монолит с ABC интерфейсами (`AnalyzerInterface`, `DataProvider`), pydantic для типизации, Dependency Injection (DI) через `config.yaml`. Масштабируется до микросервисов (FastAPI/gRPC), облачных хранилищ (PostgreSQL/S3) и продвинутого ИИ (PyTorch, RLHF-подобный подход).
- **Текущая стадия**: На 16 октября 2025, 10:55 CDT, разработка ещё не началась. Завершена подготовка документации в `docs/specs/` (Шаги 1.1 и 1.2), готова структура для старта разработки.

## Структура репозитория
```
investment_advisor/
├── src/                    # Папка для исходного кода (пока пустая)
│   ├── core/               # Базовые модели, логирование, конфигурация
│   ├── data/               # Провайдеры данных и хранилище
│   ├── analysis/           # Анализаторы (технический, новости, риски)
│   ├── ai/                 # ИИ-модели, аггрегатор, бэктестинг
│   ├── ui/                 # Компоненты UI на PyQt5
├── tests/                  # Папка для тестов (пока пустая)
├── docs/
│   └── specs/              # Пошаговые спецификации
│       ├── Step1.1-SetupAndModels.md
│       └── Step1.2-DataProviders.md
├── logs/                   # Логи (в .gitignore)
├── models/                 # Обученные модели (в .gitignore)
├── scripts/                # Утилиты (пока пустая)
├── InvestmentAdvisorDetailedPlanWithUI.md  # Концепция проекта
├── DevelopmentApproachAndIndex.md          # Подход к разработке и индекс документации
├── ModularityConcept.md                    # Принципы модульности
├── DevPrompt.md                            # Промт для ИИ/разработчиков
├── requirements.txt                        # Зависимости
├── config.yaml                            # Конфигурация для DI
└── .gitignore                             # Игнорируемые файлы (venv, logs, models)
```

## Начало работы
### Требования
- Python 3.9+
- Git
- Виртуальное окружение (рекомендуется)

### Установка
1. Клонируйте репозиторий:
   ```bash
   git clone [INSERT_GIT_LINK]
   cd investment_advisor
   ```
2. Создайте и активируйте виртуальное окружение:
   ```bash
   python -m venv venv
   source venv/bin/activate  # или venv\Scripts\activate на Windows
   ```
3. Установите зависимости (на основе `Step1.1-SetupAndModels.md`):
   ```bash
   pip install -r requirements.txt
   ```
   **Примечание**: `requirements.txt` уже содержит зависимости для Шагов 1.1 и 1.2 (`pydantic`, `pytest`, `requests`, `pandas`, `duckdb`, `pyqt5`, `scikit-learn`, `pandas_ta`, `feedparser`, `schedule`, `joblib`, `yfinance`).

### Подготовка к разработке
- Разработка ещё не началась, но документация готова для старта.
- Начните с Шага 1.1 (`Step1.1-SetupAndModels.md`):
  - Реализуйте структуру репо, pydantic-модели (`Quote`, `Recommendation`, др.), логирование.
  - Пишите тесты (`tests/test_models.py`) с coverage >80%.
- Используйте `DevPrompt.md` для подключения ИИ или разработчиков.

## Документация
- **`InvestmentAdvisorDetailedPlanWithUI.md`**: Полная концепция проекта, пользовательские сценарии, функции, UI (PyQt5), архитектура, фазы разработки.
- **`DevelopmentApproachAndIndex.md`**: Подход к разработке (MVP, модульность, Git-воркфлоу, тестирование) и индекс пошаговых спецификаций.
- **`ModularityConcept.md`**: Принципы модульности (ABC интерфейсы, pydantic, DI, тестирование).
- **`DevPrompt.md`**: Универсальный промт для подключения ИИ/разработчиков с инструкциями и вопросами.
- **Пошаговые спецификации** (`docs/specs/`):
  - `Step1.1-SetupAndModels.md`: Настройка проекта, pydantic-модели (`Quote`, `Recommendation`, др.), логирование, тесты.
  - `Step1.2-DataProviders.md`: Универсальный API (`DataProvider`, `MoexProvider`, `FallbackProvider`), тесты.

## Процесс разработки
1. **Прочитайте `DevPrompt.md`** для инструкций по подключению.
2. **Изучите текущую стадию** в `DevelopmentApproachAndIndex.md` (Фаза 1, документация завершена для Шагов 1.1 и 1.2).
3. **Начните с Шага 1.1** (`Step1.1-SetupAndModels.md`):
   - Создайте структуру репо (`src/`, `tests/`, др.).
   - Реализуйте код в `src/core/` (модели, логирование).
   - Пишите тесты в `tests/` с coverage >80%.
   - Логируйте в `logs/app_YYYYMMDD.log` с форматом `[module] message`.
4. **Следуйте `ModularityConcept.md`**:
   - Используйте ABC интерфейсы (`DataProvider`), pydantic (`Quote`, `AnalyzerOutput`), DI (`config.yaml`).
   - Код: PEP8, black, Google-style docstrings.
5. **Коммитьте**:
   ```bash
   git checkout -b feature/phase1-<module>
   git commit -m "feat: add <module> <feature>"
   ```
6. **Документируйте**: Обновите или создайте `docs/specs/StepX.Y-<Name>.md`.

## Как внести вклад
- Следуйте `ModularityConcept.md` для стиля кода (PEP8, black, Google-style docstrings).
- Используйте `config.yaml` для DI (например, `data_provider: moex`).
- Пишите тесты: Unit (`tests/test_<module>.py`), integration, E2E, coverage >80%.
- Коммитьте в ветки `feature/<module>-<feature>`, теги для моделей (`vX.Y-<model>`).
- Логируйте ошибки в `logs/app_YYYYMMDD.log`.

## Текущие задачи
- **Начать разработку с Шага 1.1** (`Step1.1-SetupAndModels.md`):
  - Создать структуру репо, pydantic-модели, логирование, тесты.
- **Подготовить Шаг 1.3** (`Step1.3-DatabaseManager.md`): Написать документацию для `DatabaseManager` (DuckDB).
- Добавить тикеры в `config.yaml` (например, `tickers: ['SBER', 'GAZP']`).
- Устранить потенциальные проблемы с MOEX API (например, HTTP 503) в Шаге 1.2.

## Вопросы
- Какие тикеры использовать для тестов (по умолчанию: SBER, GAZP)?
- Нужен ли API ключ для MOEX или Tinkoff? Предоставьте или подтвердите публичный доступ.
- Есть ли предпочтения по версиям зависимостей (например, `pydantic==2.5.0`)?
- Логировать в консоль в дополнение к файлам?
- Нужна ли документация для новых шагов (например, `Step1.3-DatabaseManager.md`) перед разработкой?

## Лицензия
MIT License (будет добавлена).