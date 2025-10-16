# Инвестиционный советник: Система рекомендаций на основе ИИ

## Обзор
Этот репозиторий содержит исходный код и документацию для desktop-приложения для среднесрочного инвестирования на Московской бирже (MOEX) с ИИ-советником. Приложение даёт утренние рекомендации "купить/продать/держать" на основе технического анализа, анализа новостей и моделей машинного обучения (Scikit-learn: RandomForest, GradientBoosting, SVM). Поддерживает оффлайн-режим (DuckDB), импорт портфеля (CSV/XLSX), бэктестинг, бумажную торговлю и самообучение с обратной связью от пользователя.

- **Технологии**: Python 3.9+, PyQt5, DuckDB, Scikit-learn, pandas_ta, feedparser, schedule, pydantic, pytest.
- **Архитектура**: Модульный монолит с ABC интерфейсами (`AnalyzerInterface`, `DataProvider`), pydantic для типизации, Dependency Injection (DI) через `config.yaml`. Масштабируется до микросервисов (FastAPI/gRPC), облачных хранилищ (PostgreSQL/S3) и продвинутого ИИ (PyTorch, RLHF-подобный подход).
- **Текущая стадия**: Фаза 1 (Прототип данных и базовый UI), шаги 1.1 (Настройка и модели) и 1.2 (Провайдеры данных) завершены на 16 октября 2025, 10:51 CDT.

## Структура репозитория
```
investment_advisor/
├── src/
│   ├── core/               # Базовые модели, логирование, конфигурация
│   ├── data/               # Провайдеры данных и хранилище
│   ├── analysis/           # Анализаторы (технический, новости, риски)
│   ├── ai/                 # ИИ-модели, аггрегатор, бэктестинг
│   ├── ui/                 # Компоненты UI на PyQt5
├── tests/                  # Unit, integration, E2E тесты
├── docs/
│   └── specs/              # Пошаговые спецификации
│       ├── Step1.1-SetupAndModels.md
│       └── Step1.2-DataProviders.md
├── logs/                   # Логи (в .gitignore)
├── models/                 # Обученные модели (в .gitignore)
├── scripts/                # Утилиты
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
3. Установите зависимости:
   ```bash
   pip install -r requirements.txt
   ```
4. Инициализируйте логирование:
   ```bash
   python -c "from src.core.logging_setup import setup_logging; setup_logging()"
   ```

### Запуск проекта
- На текущий момент реализованы шаги 1.1 и 1.2 (настройка, модели, провайдеры данных).
- Для тестирования моделей и провайдеров:
  ```bash
  pytest tests/ --cov=src --cov-report=html
  ```
- Пример использования `DataProvider`:
  ```python
  from src.data.providers import get_data_provider
  from datetime import date
  provider = get_data_provider("moex")
  quotes = provider.fetch_quotes(["SBER", "GAZP"], date(2025, 10, 1), date(2025, 10, 15))
  print([q.dict() for q in quotes])
  ```

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
2. **Проверьте текущую стадию** в `DevelopmentApproachAndIndex.md` (например, Фаза 1, Шаг 1.2 завершён).
3. **Работайте над следующим шагом** (например, `Step1.3-DatabaseManager.md`):
   - Следуйте `ModularityConcept.md` для интерфейсов, pydantic и DI.
   - Пишите код в `src/`, тесты в `tests/`.
   - Логируйте в `logs/app_YYYYMMDD.log` с форматом `[module] message`.
4. **Тестируйте**: Используйте `pytest`, coverage >80%.
5. **Коммитьте**:
   ```bash
   git checkout -b feature/phase1-<module>
   git commit -m "feat: add <module> <feature>"
   ```
6. **Документируйте**: Обновите или создайте `docs/specs/StepX.Y-<Name>.md`.

## Как внести вклад
- Следуйте `ModularityConcept.md` для стиля кода (PEP8, black, Google-style docstrings).
- Используйте `config.yaml` для DI (например, `data_provider: moex`).
- Пишите тесты: Unit (`tests/test_<module>.py`), integration, E2E.
- Коммитьте в ветки `feature/<module>-<feature>`, теги для моделей (`vX.Y-<model>`).
- Логируйте ошибки в `logs/app_YYYYMMDD.log`.

## Текущие задачи
- Реализовать `Step1.3-DatabaseManager.md`: Создать `DatabaseManager` для хранения в DuckDB.
- Добавить тикеры в `config.yaml` (например, `tickers: ['SBER', 'GAZP']`).
- Устранить потенциальные проблемы с MOEX API (например, HTTP 503) через fallback.

## Вопросы
- Нужен ли API ключ для MOEX или Tinkoff? Предоставьте или подтвердите публичный доступ.
- Какие тикеры использовать для тестов (по умолчанию: SBER, GAZP)?
- Есть ли предпочтения по версиям зависимостей (например, `pydantic==2.5.0`)?
- Логировать в консоль в дополнение к файлам?

## Лицензия
MIT License (будет добавлена).