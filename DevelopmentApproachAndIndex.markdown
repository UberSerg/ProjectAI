# Подход к разработке интеллектуальной системы инвестиционных рекомендаций

## Введение
Этот файл описывает подход к разработке desktop-приложения для среднесрочного инвестирования на Московской бирже (MOEX) с AI-советником. Он служит индексом и оглавлением для всей документации проекта, указывая, где искать подробности по фазам, этапам и модулям. Основная концепция проекта (пользовательский сценарий, ключевые функции, интерфейсы, архитектурная схема, спецификации) отражена в файле **InvestmentAdvisorDetailedPlanWithUI.md**. Здесь мы фокусируемся на подходе к разработке, с акцентом на модульность, универсальность, детальном блоке работы с обучением и моделями, а также подробной документации по модулям и концепции модульности.

**Цель файла**: Использовать как основу для дальнейшего наполнения описания проекта. Каждый этап ссылается на отдельный файл в `docs/specs/`, где содержится максимально подробное описание (цели, действия, код, тесты, масштабируемость). Это позволяет декомпозировать проект, делать изменения локальными и масштабировать без переписывания.

**Содержание и где искать подробности**:
- **Концепция проекта**: Подробный пользовательский сценарий, функции, интерфейсы, архитектура — в **InvestmentAdvisorDetailedPlanWithUI.md**.
- **Подход к разработке**: Модульность, универсальность, обучение моделей — в этом файле.
- **Структура документации**: Фазы и этапы ниже, с ссылками на файлы шагов (например, `Step1.1-SetupAndModels.md`).
- **Детальная документация по модулям**: Ниже в разделе "Подробная документация по модулям".
- **Концепция модульности**: Ниже в разделе "Концепция модульности".

## Подход к разработке
- **MVP с масштабируемостью**: Начинаем с простого MVP (локальное desktop-приложение для одного пользователя, базовые функции на Scikit-learn), но строим архитектуру, готовую к росту (микро-сервисы, облако, продвинутый AI). Используем Python 3.9+, Visual Studio Code, Git для версионирования (ветки `feature/phase1-<module>`, теги для моделей, например, `v1.0-rf`).
- **Модульность и универсальность**: Проект — модульный монолит, где каждый компонент (данные, анализ, AI) — независимый "микро-модуль" с интерфейсом (ABC + pydantic). Изменения в модуле (например, замена `BasicNewsAnalyzer` на `LLMNewsAnalyzer`) не затрагивают другие, если контракт (вход/выход) сохранён. Dependency Injection (DI) через `config.py` factory или `config.yaml` для выбора имплементаций. Это обеспечивает глубокую декомпозицию: приложение разбивается на слои (data, analysis, ai, ui), легко тестируемые и расширяемые.
- **Git-воркфлоу**: Private репозиторий на GitHub. Коммиты по шагам (`feat: add news analyzer`, `fix: handle API error`). CI/CD через GitHub Actions (pytest, black, coverage >80%). Модели сохраняются в `models/` (`.pkl`), данные (DuckDB) в `.gitignore`.
- **Тестирование**: 
  - Unit: Каждый модуль тестируется изолированно (pytest, `tests/test_<module>.py`).
  - Integration: Проверка контрактов (`Dict[str, AnalyzerOutput]`).
  - End-to-End: Полный цикл от данных до UI (`tests/integration/test_full.py`).
  - Coverage: >80% с помощью `pytest-cov`.
- **Оффлайн-режим**: Локальный кэш в DuckDB, fallback API (yfinance) при сбоях MOEX ISS API.
- **Расширение**: Хуки для асинхронности (asyncio), микро-сервисов (FastAPI/gRPC), облачных БД (PostgreSQL), продвинутого AI (PyTorch, RLHF-like).

## Концепция модульности
- **Принципы**:
  - **Микромодульность**: Каждый компонент (данные, тех анализ, новости, риски, AI) имеет single responsibility (SOLID). Реализуется через ABC интерфейсы (`AnalyzerInterface`, `DataProvider`) и pydantic модели для входов/выходов (`AnalyzerInput`, `AnalyzerOutput`).
  - **Контракты**: Модули возвращают стандартизированный формат (`Dict[str, AnalyzerOutput]` для анализаторов, `List[Quote]` для данных). Вход: `AnalyzerInput` (например, `urls: List[str], tickers: List[str]`). Это обеспечивает backward-compatibility: новые поля в pydantic — optional.
  - **Dependency Injection**: Модули инжектируются через factory (`config.py: get_analyzer('news')`) или `config.yaml` (например, `analyzers: {news: BasicNewsAnalyzer}`). Позволяет заменить модуль без изменения кода (например, `BasicNewsAnalyzer` → `LLMNewsAnalyzer`).
  - **Декомпозиция**: Слои (data, analysis, ai, ui) и подмодули (technical, news, risk) изолированы. Aggregator собирает outputs от всех анализаторов, Recommender генерирует рекомендации.
  - **Масштабируемость**: Хуки для asyncio (реал-тайм обновления), FastAPI/gRPC (микро-сервисы), PostgreSQL/S3 (облако).
- **Преимущества**:
  - Локализация изменений: Замена модуля не ломает другие (например, RSS → LLM).
  - Тестируемость: Изолированные unit-тесты для каждого модуля, интеграционные для контрактов.
  - Масштабируемость: Монолит для MVP, микро-сервисы для продакшена (Docker, Kubernetes).
- **Пример**:
  ```python
  from abc import ABC, abstractmethod
  from pydantic import BaseModel
  from typing import Dict, List

  class AnalyzerInput(BaseModel):
      urls: List[str]
      tickers: List[str]

  class AnalyzerOutput(BaseModel):
      score: float  # -1..1
      confidence: float  # 0..1
      reason: str
      metadata: Dict[str, str] = {}

  class AnalyzerInterface(ABC):
      @abstractmethod
      def process(self, input_data: AnalyzerInput) -> Dict[str, AnalyzerOutput]:
          pass
  ```
- **DI пример**:
  - `config.yaml`:
    ```yaml
    analyzers:
      technical: BasicTechnicalAnalyzer
      news: BasicNewsAnalyzer
      risk: BasicRiskAnalyzer
    ```
  - Factory:
    ```python
    from src.analysis.news import BasicNewsAnalyzer, LLMNewsAnalyzer
    from src.analysis.technical import BasicTechnicalAnalyzer

    def get_analyzer(analyzer_type: str) -> AnalyzerInterface:
        analyzers = {
            'basic_news': BasicNewsAnalyzer,
            'llm_news': LLMNewsAnalyzer,
            'basic_technical': BasicTechnicalAnalyzer
        }
        return analyzers[analyzer_type]()
    ```

## Блок работы с обучением и моделями (детализированный)
- **Концепция**: Supervised learning с self-improving feedback loop, вдохновлённым RLHF (reinforcement learning with human feedback). Базовые модели — Scikit-learn (RandomForestClassifier, GradientBoostingClassifier, SVM) для классификации сигналов (buy/sell/hold) на основе фич (RSI, MACD, SMA/EMA, mentions, volatility, корреляции с индексом MOEX). Обучение: оффлайн (backtesting на 3 года) + онлайн (ежедневный retrain). Пользовательский feedback (подтверждение/игнорирование в UI) формирует labels для улучшения. A/B-тестирование для выбора лучшей модели/стратегии. Метрики трекятся в MLflow для экспериментов.
- **Процесс обучения**:
  1. **Подготовка данных**:
     - Aggregator собирает outputs от анализаторов: `Dict[str, Dict[str, AnalyzerOutput]]` (например, `technical: {SBER: {score: 0.7, confidence: 0.8, reason: 'RSI=75'}}`).
     - Фичи: aggregated scores (technical_score, news_score, risk_score), historical returns, volatility, корреляции.
     - Labels: Исторические returns (buy: >5% рост, sell: >5% падение, hold: -5%..+5%).
  2. **Обучение**:
     - Модель: `RandomForestClassifier(n_estimators=100, max_depth=10)` или `GradientBoostingClassifier(learning_rate=0.1)` или `SVC(probability=True)`.
     - Cross-validation: `TimeSeriesSplit(n_splits=5)` для избежания data leakage.
     - `model.fit(X, y)` на 3 года MOEX данных.
  3. **Retrain**:
     - Ежедневно (через `schedule` в 00:00): добавляем новые данные (quotes, user feedback).
     - Анализ ошибок: Если accuracy <0.6 или Win Rate <60%, корректируем веса (feature_importances_ в RandomForest, feature selection в SVM/GB).
     - Сохранение: `joblib.dump(model, 'models/rf_v2.pkl')`, тег в Git (`v2.0-rf`).
  4. **A/B-тестирование**:
     - Две модели (например, RandomForest vs SVM) или стратегии (momentum vs trends).
     - Параллельный запуск в backtesting/paper trading.
     - Сравнение по метрикам: Sharpe Ratio, Win Rate, Max Drawdown.
     - Победитель сохраняется как основная модель (`config.yaml: model: rf`).
  5. **Human feedback**:
     - UI кнопки "Confirm/Ignore" в рекомендациях.
     - Confirm → label=action (buy/sell/hold), Ignore → label=hold.
     - Batch retrain на feedback каждые 7 дней или при >50 labels.
  6. **Метрики**:
     - Win Rate: `successful_trades / total_trades`.
     - Sharpe Ratio: `(mean_return - risk_free_rate) / std_return`.
     - Max Drawdown: `max(peak - trough)`.
     - Сравнение с buy-and-hold (индекс MOEX).
  7. **Сохранение и трекинг**:
     - Модели: `joblib.dump(model, 'models/<model>_vX.pkl')`.
     - MLflow: `mlflow.log_metric('sharpe', 1.2)`, `mlflow.log_artifact('models/rf_v2.pkl')`.
     - Git тег: `git tag v2.0-rf`.
- **Масштабируемость**:
  - **PyTorch**: Переход на LSTM для временных рядов (`nn.LSTM(input_size=len(features), hidden_size=64)`, Adam optimizer, early stopping).
  - **RLHF-like**: User feedback как rewards для reinforcement learning (будущий этап).
  - **MLflow**: Трекать эксперименты (A/B, гиперпараметры, метрики).
  - **Cloud**: Модели в S3, обучение на GPU (EC2).
- **Обработка ошибок**:
  - Если retrain не удался (мало данных), fallback к предыдущей модели (`models/rf_v1.pkl`).
  - Логи: `logger.error("Retrain failed: insufficient data, using v1")`.
  - UI: Уведомление "Ошибка обучения, используется старая модель".
- **Тестирование**:
  - Unit: Mock данные для `model.fit` (`tests/test_recommender.py`).
  - Integration: Проверка `Aggregator -> Recommender` (контракт `Dict[str, AnalyzerOutput]`).
  - Assert: `accuracy > 0.5`, `Win Rate > 60%`.
  - Backtesting: Симуляция на 3 года, проверка метрик.

## Подробная документация по модулям
### Core модуль (src/core/)
- **Описание**: Базовые модели, конфиги, логирование. Типизация через pydantic для строгой валидации (например, `prices > 0`).
- **Модульность**: 
  - Модели (`Quote`, `Recommendation`, `PortfolioPosition`, `Transaction`, `LogEntry`) — shared контракты для всех слоёв.
  - Логирование: `logging_setup.py` с ротацией (`logs/app_YYYYMMDD.log`).
  - Factory: `config.py` для DI (`get_analyzer('news')`).
- **Масштабируемость**: 
  - Модели готовы для ORM (SQLAlchemy) или новых полей (optional в pydantic).
  - Логи в ELK Stack для продакшена.
- **Ключевые файлы**: 
  - `models.py`: Quote, Recommendation, AnalyzerInput, AnalyzerOutput.
  - `config.py`: Factory для DI.
  - `logging_setup.py`: Настройка логов.

### Data модуль (src/data/)
- **Описание**: Сбор данных (`DataProvider` ABC), хранение (`DatabaseManager`), парсинг новостей (`NewsAnalyzerInterface`).
- **Модульность**: 
  - `DataProvider`: ABC с `fetch_quotes`, имплементации `MoexProvider`, `FallbackProvider` (yfinance).
  - Выход: `List[Quote]` (pydantic).
  - `NewsAnalyzerInterface`: `process(input) -> Dict[str, AnalyzerOutput]`.
  - Замена: Новый провайдер (Tinkoff) через DI.
- **Масштабируемость**: 
  - Async fetch с asyncio.
  - Cloud storage: PostgreSQL, S3.
- **Ключевые файлы**: 
  - `providers.py`: DataProvider, MoexProvider, FallbackProvider.
  - `database.py`: DatabaseManager (DuckDB).
  - `news_parser.py`: NewsAnalyzerInterface, BasicNewsAnalyzer.

### Analysis модуль (src/analysis/)
- **Описание**: Технический анализ, новости, риски (каждый реализует `AnalyzerInterface`, возвращает `Dict[str, AnalyzerOutput]`).
- **Модульность**: 
  - `TechnicalAnalyzer`: RSI, MACD, SMA/EMA (pandas_ta).
  - `NewsAnalyzer`: RSS mentions (Basic) или LLM (Hugging Face).
  - `RiskAnalyzer`: Стоп-лосс, волатильность, position sizing.
  - Контракт: `process(AnalyzerInput) -> Dict[str, AnalyzerOutput]`.
- **Масштабируемость**: 
  - Добавить фундаментальный анализ как новый analyzer.
  - LLM для новостей через API (FastAPI).
- **Ключевые файлы**: 
  - `technical.py`: TechnicalAnalyzer.
  - `news.py`: NewsAnalyzerInterface, BasicNewsAnalyzer.
  - `risk.py`: RiskAnalyzer.

### AI модуль (src/ai/)
- **Описание**: Aggregator (собирает outputs), Recommender (RandomForest/GradientBoosting/SVM), Learning (retrain), Backtester, PaperTrader.
- **Модульность**: 
  - `StrategyInterface`: Для momentum/trends.
  - `Aggregator`: Собирает `Dict[str, Dict[str, AnalyzerOutput]]`.
  - `Recommender`: Генерирует рекомендации (`List[Recommendation]`).
  - DI: Analyzers и Strategy инжектируются через config.
- **Масштабируемость**: 
  - PyTorch LSTM для временных рядов.
  - MLflow для трекинга экспериментов.
  - RLHF-like для продвинутого обучения.
- **Ключевые файлы**: 
  - `aggregator.py`: Aggregator.
  - `recommender.py`: Recommender, StrategyInterface.
  - `learning.py`: Retrain, A/B-тестирование.
  - `backtest.py`, `paper_trading.py`: Backtester, PaperTrader.

### UI модуль (src/ui/)
- **Описание**: PyQt5 MainWindow, вкладки (Дашборд, Портфель, Логи, Обучение), диалоги (настройки, импорт).
- **Модульность**: 
  - `MainWindow`: Инжектирует Aggregator, DatabaseManager через DI.
  - Observer pattern: Signals/slots для обновлений (QTimer).
  - Контракты: UI работает с `List[Recommendation]`, `List[PortfolioPosition]`.
- **Масштабируемость**: 
  - Переход на Qt for WebAssembly.
  - Веб-версия через FastAPI + React.
- **Ключевые файлы**: 
  - `main_window.py`: MainWindow, вкладки.
  - `dashboard.py`: Таблица рекомендаций.
  - `portfolio.py`: Управление портфелем.

## Структура файлов документации
### Фаза 1: Прототип данных и базовый UI (4–6 недель)
- **Шаг 1.1: Настройка проекта и типизация данных** — Файл: `docs/specs/Step1.1-SetupAndModels.md` (структура репо, установка, модели `Quote`/`Recommendation` с pydantic, тесты).
- **Шаг 1.2: Универсальный API (DataProvider)** — Файл: `docs/specs/Step1.2-DataProviders.md` (ABC `DataProvider`, `MoexProvider`, `FallbackProvider`, логирование, тесты).
- **Шаг 1.3: Хранение данных в DuckDB** — Файл: `docs/specs/Step1.3-DatabaseManager.md` (класс `DatabaseManager`, таблицы `quotes`, `portfolio`, `transactions`, `logs`, `recommendations`, методы `save/load`, тесты).
- **Шаг 1.4: RSS-парсинг для новостей** — Файл: `docs/specs/Step1.4-NewsParser.md` (`NewsAnalyzerInterface`, `BasicNewsAnalyzer`, тесты).
- **Шаг 1.5: Базовый UI в PyQt5** — Файл: `docs/specs/Step1.5-MainWindow.md` (`QMainWindow`, вкладки, DI для `Aggregator`/`DatabaseManager`, тесты с pytest-qt).

### Фаза 2: Модуль анализа и рекомендаций (6–8 недель)
- **Шаг 2.1: Технический анализ** — Файл: `docs/specs/Step2.1-TechnicalAnalysis.md` (`TechnicalAnalyzerInterface`, индикаторы RSI/MACD/SMA, тесты).
- **Шаг 2.2: Риск-менеджмент** — Файл: `docs/specs/Step2.2-RiskManagement.md` (`RiskAnalyzerInterface`, стоп-лосс, волатильность, тесты).
- **Шаг 2.3: Генерация рекомендаций** — Файл: `docs/specs/Step2.3-Recommender.md` (`Aggregator`, `Recommender` с RandomForest/GradientBoosting/SVM, тесты).
- **Шаг 2.4: Интеграция в UI** — Файл: `docs/specs/Step2.4-UIIntegration.md` (таблица рекомендаций, диалог детализации, тесты).

### Фаза 3: Система обучения и валидации (6–8 недель)
- **Шаг 3.1: Backtesting** — Файл: `docs/specs/Step3.1-Backtesting.md` (`run_backtest`, метрики Win Rate/Sharpe/Max Drawdown, тесты).
- **Шаг 3.2: Paper trading** — Файл: `docs/specs/Step3.2-PaperTrading.md` (`PaperPortfolio`, реал-тайм симуляция, тесты).
- **Шаг 3.3: Самообучение** — Файл: `docs/specs/Step3.3-Learning.md` (анализ ошибок, retrain, A/B-тестирование RandomForest vs SVM, тесты).
- **Шаг 3.4: UI для обучения** — Файл: `docs/specs/Step3.4-TrainingUI.md` (таблица метрик, отчёты в QTextEdit, тесты).

### Фаза 4: Полировка и оптимизация (4–6 недель)
- **Шаг 4.1: Оптимизация** — Файл: `docs/specs/Step4.1-Optimization.md` (cProfile для профилирования, async для данных, тесты).
- **Шаг 4.2: Расширение** — Файл: `docs/specs/Step4.2-Extensions.md` (PyTorch LSTM, MLflow, Tinkoff API, тесты).
- **Шаг 4.3: Полное тестирование и деплой** — Файл: `docs/specs/Step4.3-TestingAndDeploy.md` (end-to-end тесты, PyInstaller для сборки, Docker для контейнеризации).

## Регламент модульности (новое)
Для соответствия `ModularityConcept.md`:
- **Контракты**:
  - Каждый модуль реализует ABC (`AnalyzerInterface`, `DataProvider`, `StrategyInterface`) с методом `process` (или `fetch_quotes` для данных).
  - Вход: Pydantic модели (`AnalyzerInput`, `DataInput`).
  - Выход: `Dict[str, AnalyzerOutput]` для анализаторов, `List[Quote]` для DataProvider, `List[Recommendation]` для Recommender.
  - Исключения: Кастомные (`ProcessingError`), логируются в `logs/app_YYYYMMDD.log`.
  - Backward-compatibility: Новые поля в pydantic — optional, удаление полей — через новый контракт.
- **Dependency Injection**:
  - Модули инжектируются через factory (`config.py`) или `config.yaml`.
  - Пример: `Aggregator(analyzers={'news': get_analyzer('basic_news')})`.
  - Замена модуля: `config.yaml: analyzers.news: llm_news`.
- **Тестирование**:
  - Unit: Mock ABC, coverage >80% (`pytest tests/test_<module>.py`).
  - Integration: Проверка контрактов (`Dict[str, AnalyzerOutput]`).
  - E2E: Полный цикл от данных до UI (`tests/integration/test_full.py`).
  - Assert: `isinstance(output, Dict)`, `output[ticker].confidence <= 1.0`.
- **Код**:
  - PEP8, форматтер `black`.
  - Google-style docstrings.
  - Именование: `<Module>Interface` (например, `NewsAnalyzerInterface`), `<Type><Module>` (например, `BasicNewsAnalyzer`).
- **Git**:
  - Ветки: `feature/<module>-<feature>` (например, `feature/news-llm`).
  - Commits: `feat: add news analyzer`, `fix: handle API error`.
  - PR: Review, CI (pytest, black).
  - Теги: `vX.Y-<model>` (например, `v1.0-rf`, `v2.0-svm`).
- **Логирование**:
  - Категории: `[data]`, `[analysis]`, `[ai]`, `[ui]`.
  - Формат: `%(asctime)s [%(levelname)s] [%(module)s] %(message)s`.
  - Ротация: Ежедневная в `logs/app_YYYYMMDD.log`.

## Следующие шаги
- Начать с Фазы 1, Шаг 1.1. Реализовать `docs/specs/Step1.1-SetupAndModels.md` (структура проекта, установка, pydantic модели, тесты).
- Проверить синхронизацию с `InvestmentAdvisorDetailedPlanWithUI.md` для согласованности.
- Добавить примеры кода для всех модулей в `docs/specs/`.