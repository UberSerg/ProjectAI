# Полный план разработки интеллектуальной системы инвестиционных рекомендаций

## Введение
Этот документ — полный, детализированный план разработки desktop-приложения для среднесрочного инвестирования на Московской бирже (MOEX). Приложение включает AI-советника, который предоставляет утренние рекомендации "что покупать/продавать" на горизонте 2–8 недель, управляет портфелем, анализирует данные и обучается на своих ошибках. План составлен на основе детальных обсуждений требований, чтобы его можно было использовать как самостоятельный документ для начала разработки в любом инструменте (например, в другом AI, IDE или с командой разработчиков).

План учитывает:
- Полностью локальную работу (оффлайн-режим после загрузки данных).
- Фокус на простом MVP (минимально жизнеспособном продукте) с возможностью постепенного улучшения.
- Использование бесплатных данных и инструментов на старте.
- Подробные инструкции по установке, коду, интерфейсам и тестированию.
- **Модульную архитектуру**: Каждый компонент (данные, анализ, AI) — независимый "микро-модуль" с чётким интерфейсом (ABC + pydantic), заменяемый без касания других частей.
- **Dependency Injection (DI)**: Модули инжектируются через factory (`config.py`) для гибкости замены (например, `BasicNewsAnalyzer` на `LLMNewsAnalyzer`).
- **Контракты**: Все модули возвращают стандартизированный формат (`Dict[str, AnalyzerOutput]`), Aggregator собирает данные для Recommender.
- **Масштабируемость**: Подготовка к асинхронности (asyncio), микро-сервисам (FastAPI/gRPC), облачным БД (PostgreSQL).
- **Git-репозиторий**: Версионирование кода, моделей, документации (ветки, теги).

**Инструкция для нового чата/ИИ**: "Разработай приложение по этому плану, начиная с Фазы 1, Шаг 1.1. Предоставь код для настройки окружения, типизации (pydantic), UI (PyQt5) и тестов, следуя упрощённому модульному подходу из ModularityConcept.md."

## Полные требования
### Пользовательский сценарий
- Утром пользователь открывает приложение.
- Приложение автоматически обновляет данные (котировки MOEX, RSS-новости) за период простоя и в реальном времени, пока запущено.
- Пользователь видит утренний дашборд с рекомендациями на среднесрок (2–8 недель) по текущему портфелю.
- Рекомендации включают: тикер актива, действие (купить/продавать/игнорировать), целевую цену, стоп-лосс, срок удержания, уверенность (процент или цветовая кодировка), обоснование (на основе индикаторов, новостей).
- Пользователь принимает решение: покупает/продаёт/игнорирует сигнал (ручное подтверждение в UI).
- Через 2–4 недели система анализирует результат (сравнивает прогноз с реальной доходностью), фиксирует ошибку/успех и корректирует модель.
- Обновление портфеля: планово 2 раза в месяц (например, 1-го и 15-го) или вручную по сигналам.
- Ежедневная корректировка: сравнение прогнозов с реальностью, анализ ошибок, переобучение модели.

### Ключевые функции
1. **Управление портфелем**:
   - Ручной ввод позиций (тикер, количество, цена покупки, дата).
   - Импорт из брокерских отчётов (CSV/XLSX от Сбер Инвестиций): парсинг файлов для извлечения позиций.
   - Полная детализация: текущие позиции и история транзакций (покупки/продажи с датами, ценами).
   - Экспорт портфеля в CSV для анализа в Excel.
   - Поддержка только одного портфеля (без нескольких профилей).

2. **Утренний дашборд с рекомендациями**:
   - Компактная таблица: тикер, действие, цель, стоп-лосс, срок (2–8 недель), уверенность (цвет/процент).
   - Кликабельная детализация: обоснование (индикаторы, новости, риски).
   - Минималистичный стиль: без лишних графиков, фокус на читаемости.

3. **Анализ новостей и рыночных данных**:
   - Технический анализ: тренды, уровни поддержки/сопротивления, индикаторы (RSI, MACD, SMA/EMA).
   - Базовый новостной анализ: частота упоминаний активов в RSS (без сложного NLP для MVP).
   - Корреляционный анализ: акции vs индекс MOEX.
   - Анализ рисков: стоп-лосс, волатильность, корреляционные лимиты, position sizing.

4. **AI-движок с самообучением**:
   - Модели: Scikit-learn (Random Forest, Gradient Boosting или SVM) для классификации сигналов (buy/sell/hold).
   - Стратегии: моментум-трейдинг (2–4 недели), среднесрочные тренды (4–8 недель).
   - Самообучение: tracking сигналов, анализ ошибок (почему не сработал), корректировка весов фич (например, снижение веса RSI), A/B-тестирование стратегий, backtesting.
   - Ежедневная корректировка: переобучение на новых данных.

5. **Валидация прогнозов и корректировка стратегий**:
   - Backtesting: на 1–5 лет исторических данных MOEX (по умолчанию 3 года).
   - Paper trading: симуляция в реальном времени.
   - Метрики: Win Rate (%), Sharpe Ratio, Max Drawdown (%), сравнение с buy-and-hold (индекс MOEX).
   - Отдельный модуль в UI для просмотра метрик и анализа ошибок.

### Описание интерфейсов для MVP
#### Общие принципы дизайна
- **Стиль**: Минималистичный, монохромная палитра (белый фон, чёрный текст), акценты для уверенности (зелёный/оранжевый/красный: 🟢/🟠/🔴).
- **Компактность**: Основная информация видна сразу, детализация по клику.
- **Структура**: Одно окно (QMainWindow) с вкладками (QTabWidget): Дашборд, Портфель, Логи, Обучение.
- **Элементы**: Таблицы (QTableWidget), кнопки (QPushButton), текстовые поля (QTextEdit), диалоги (QDialog) для ввода/импорта.
- **Оффлайн-режим**: Данные из DuckDB, уведомление "API недоступен" при сбоях.

#### 1. Главное окно
- **Название**: "Investment Advisor".
- **Размер**: 800x600 пикселей (адаптивно, с возможностью растягивания).
- **Элементы**:
  - **Верхняя панель**:
    - Заголовок окна.
    - Кнопка "Обновить данные" (QPushButton): Запускает загрузку MOEX и RSS.
    - Кнопка "Настройки" (QPushButton): Открывает диалог для расписания.
  - **Основная область**: QTabWidget с вкладками:
    - Дашборд (рекомендации).
    - Портфель (управление).
    - Логи (обновления, отладка).
    - Обучение (метрики, анализ ошибок).
  - **Строка статуса**: QLabel с текстом (например, "Последнее обновление: 15.10.2025 13:55" или "MOEX API недоступен").
- **Макет**:
  ```
  [ Главное окно: Investment Advisor ]
  [ Кнопка: Обновить данные ] [ Кнопка: Настройки ]
  [ QTabWidget: Дашборд | Портфель | Логи | Обучение ]
  [ Статус: Последнее обновление: 15.10.2025 13:55 ]
  ```

#### 2. Вкладка "Дашборд"
- **Цель**: Показать компактный список рекомендаций с кликабельной детализацией.
- **Элементы**:
  - **Таблица рекомендаций** (QTableWidget):
    - Колонки: Тикер | Действие | Целевая цена | Стоп-лосс | Срок | Уверенность.
    - Пример строк:
      - SBER | Купить | 320.5 | 300.0 | 4 недели | 🟢 85%.
      - GAZP | Продать | 150.0 | 160.0 | 2 недели | 🟠 70%.
    - Цветовая кодировка: 🟢 (>80%), 🟠 (50–80%), 🔴 (<50%) в столбце "Уверенность".
    - Двойной клик: Открывает QDialog с детализацией (обоснование: RSI, MACD, упоминания).
  - **Диалог детализации** (QDialog):
    - Поля: Тикер (QLabel), Действие, Обоснование (QTextEdit, например, "RSI=75, MACD crossover, mentions=10").
    - Кнопки: "ОК" (закрыть), "Игнорировать" (удалить рекомендацию).
  - **Кнопка**: "Обновить рекомендации" (пересчёт сигналов).
- **Макет**:
  ```
  [ Вкладка: Дашборд ]
    [ Таблица: Тикер | Действие | Целевая цена | Стоп-лосс | Срок | Уверенность ]
      [ SBER | Купить | 320.5 | 300.0 | 4 недели | 🟢 85% ]
      [ GAZP | Продать | 150.0 | 160.0 | 2 недели | 🟠 70% ]
    [ Кнопка: Обновить рекомендации ]
  ```

#### 3. Вкладка "Портфель"
- **Цель**: Управление портфелем (импорт, ручной ввод, экспорт).
- **Элементы**:
  - **Таблица портфеля** (QTableWidget):
    - Колонки: Тикер | Количество | Цена покупки | Дата покупки | Текущая цена | Доходность (%).
    - Пример строк:
      - SBER | 100 | 300.0 | 01.10.2025 | 315.0 | +5%.
      - GAZP | 50 | 160.0 | 15.09.2025 | 155.0 | -3%.
  - **Кнопки**:
    - "Импорт CSV" (QPushButton): QFileDialog для выбора файла Сбер Инвестиций.
    - "Добавить вручную" (QPushButton): QDialog для ввода.
    - "Экспорт в CSV" (QPushButton): Сохранение портфеля.
    - "Обновить портфель" (QPushButton): Плановое обновление или по сигналам.
  - **Диалог ручного ввода** (QDialog):
    - Поля: Тикер (QLineEdit), Количество (QSpinBox), Цена покупки (QDoubleSpinBox), Дата (QDateEdit).
    - Кнопки: "Сохранить", "Отмена".
- **Макет**:
  ```
  [ Вкладка: Портфель ]
    [ Таблица: Тикер | Количество | Цена покупки | Дата покупки | Текущая цена | Доходность ]
      [ SBER | 100 | 300.0 | 01.10.2025 | 315.0 | +5% ]
      [ GAZP | 50 | 160.0 | 15.09.2025 | 155.0 | -3% ]
    [ Кнопка: Импорт CSV ] [ Кнопка: Добавить вручную ] [ Кнопка: Экспорт в CSV ] [ Кнопка: Обновить ]
  ```

#### 4. Вкладка "Логи"
- **Цель**: Отображение обновлений и журнала отладки ("жизнь под капотом").
- **Элементы**:
  - **Текстовое поле** (QTextEdit, только чтение):
    - Категории логов:
      - Обновления: "MOEX данные обновлены: 15.10.2025 13:55".
      - API: "Запрос SBER: успех, 100 строк".
      - Ошибки: "MOEX API недоступен: HTTP 503".
      - Аналитика: "RSI для SBER: 75".
    - Логи сохраняются в DuckDB и файлы (`logs/app_YYYYMMDD.log`).
  - **Кнопки**:
    - "Очистить логи" (QPushButton).
    - "Экспорт логов" (QPushButton): В текстовый файл.
- **Макет**:
  ```
  [ Вкладка: Логи ]
    [ QTextEdit: Логи ]
      - 15.10.2025 13:55: MOEX данные обновлены
      - 15.10.2025 13:56: Запрос SBER: успех
      - 15.10.2025 13:57: RSI для SBER: 75
    [ Кнопка: Очистить логи ] [ Кнопка: Экспорт логов ]
  ```

#### 5. Вкладка "Обучение"
- **Цель**: Показать метрики, анализ ошибок, отчёты самообучения.
- **Элементы**:
  - **Таблица метрик** (QTableWidget):
    - Колонки: Стратегия | Win Rate | Sharpe Ratio | Max Drawdown | Сравнение с MOEX.
    - Пример строк:
      - Моментум | 65% | 1.2 | 15% | +5%.
      - Тренды | 60% | 1.0 | 20% | +2%.
  - **Текстовое поле отчётов** (QTextEdit):
    - Пример: "Научился: RSI переоценён, снижен вес на 20%. Поправка: Добавлен фильтр по волатильности."
  - **Кнопки**:
    - "Запустить backtesting" (QPushButton): Выбор периода (1–5 лет).
    - "Запустить paper trading" (QPushButton).
    - "Обновить модель" (QPushButton).
- **Макет**:
  ```
  [ Вкладка: Обучение ]
    [ Таблица: Стратегия | Win Rate | Sharpe Ratio | Max Drawdown | Сравнение с MOEX ]
      [ Моментум | 65% | 1.2 | 15% | +5% ]
      [ Тренды | 60% | 1.0 | 20% | +2% ]
    [ QTextEdit: Отчёты ]
      - Научился: RSI переоценён, снижен вес на 20%
      - Поправка: Добавлен фильтр по волатильности
    [ Кнопка: Запустить backtesting ] [ Кнопка: Paper trading ] [ Кнопка: Обновить модель ]
  ```

#### 6. Диалог настроек
- **Цель**: Настройка расписания обновлений.
- **Элементы**:
  - Поля:
    - Время обновления (QTimeEdit, например, "08:00").
    - Частота реал-тайм обновлений (QComboBox: 5, 10, 15 минут).
  - Кнопки: "Сохранить", "Отмена".
- **Макет**:
  ```
  [ Диалог: Настройки ]
    [ QTimeEdit: Время обновления: 08:00 ]
    [ QComboBox: Частота: 5 мин | 10 мин | 15 мин ]
    [ Кнопка: Сохранить ] [ Кнопка: Отмена ]
  ```

### Архитектура и технологии
- **Стек разработки**: Python 3.9+, PyQt5 для desktop.
- **Локальное хранение**: DuckDB для аналитики (котировки, портфель, сигналы, логи).
- **AI-модели**: Scikit-learn (Random Forest, Gradient Boosting, SVM) с feature engineering.
- **Источники данных**: MOEX ISS API (котировки), RSS (Интерфакс/РИА), yfinance как fallback.
- **Риск-менеджмент**: Position sizing, стоп-лосс, корреляционные лимиты, волатильность.
- **Feature engineering**: Returns, volatility, RSI, MACD, SMA/EMA, mentions из новостей.
- **Обновления**: При запуске + реал-тайм (каждые 5–15 мин), ручное расписание, логи.
- **Ограничения**: Один пользователь, оффлайн после загрузки, бесплатные данные.
- **Модульная архитектура**:
  - Каждый компонент (данные, тех анализ, новости, риски, AI) — независимый модуль с интерфейсом (ABC) и стандартизированным выходом (`AnalyzerOutput` pydantic: score, confidence, reason).
  - **Dependency Injection**: Модули инжектируются через factory (`config.py: get_analyzer('news')`).
  - **Контракты**: Все модули возвращают `Dict[str, AnalyzerOutput]`, Aggregator собирает данные для Recommender.
  - **Масштабируемость**: Хуки для асинхронности (asyncio), микро-сервисов (FastAPI/gRPC), облачных БД (PostgreSQL).
- **Git-репозиторий**:
  - Структура: `src/`, `tests/`, `docs/specs/`, `logs/`, `models/`, `scripts/`.
  - Ветки: `main`, `feature/phase1-data`, теги для моделей (`v1.0-rf`).
  - CI/CD: GitHub Actions для тестов (`pytest`, `black`).

### Концепция обучения моделей
- **Базовая модель**:
  - Scikit-learn: RandomForestClassifier, GradientBoostingClassifier или SVM для классификации сигналов (buy/sell/hold).
  - **Features**: Технические индикаторы (RSI, MACD, SMA/EMA), новостной sentiment (mentions count), волатильность, корреляции с индексом MOEX.
  - **Labels**: Исторические returns (buy: рост >5%, sell: падение >5%, hold: -5% до +5%).
  - **Обучение**: Оффлайн на 3 года MOEX данных (TimeSeriesSplit для cross-validation, чтобы избежать overfitting).
  - **Сохранение**: `joblib.dump(model, 'models/rf_v1.pkl')`, версия в Git tag (`v1.0-rf`).
- **Самообучение**:
  - **Feedback loop**: Ежедневно сравниваем прогнозы с реальностью (accuracy для классификации, MSE для цен). Если Win Rate <60%, корректируем веса (feature_importances_ в RandomForest, feature selection для SVM/GB).
  - **Human feedback**: Подтверждение/игнорирование пользователем → labels для retrain.
  - **A/B-тестирование**: Две модели (momentum vs trends) или алгоритмы (RandomForest vs SVM), сравнение по Sharpe Ratio, Max Drawdown.
  - **Cron**: `schedule` для ежедневного retrain в 00:00.
- **Масштабируемость**:
  - **PyTorch**: Переход на LSTM для временных рядов (например, `nn.LSTM(input_size=len(features), hidden_size=64)`, train с Adam, early stopping).
  - **MLflow**: Трекать эксперименты (метрики, параметры, версии моделей: `mlflow.log_metric('sharpe', 1.2)`).
  - **RLHF-like**: User feedback как rewards для reinforcement learning (будущий этап).
- **Тестирование**:
  - Backtesting: Симуляция на исторических данных (1–5 лет, по умолчанию 3 года).
  - Paper trading: Реал-тайм симуляция портфеля.
  - Метрики: Win Rate >60%, Sharpe >1.0, Max Drawdown <20%.
  - Cross-validation: TimeSeriesSplit (5 folds) для избежания overfitting.

### Критические вопросы и решения
- **Объём данных**: 1–5 лет котировок MOEX, ежедневные обновления.
- **Скорость**: Не критична (анализ может быть длительным).
- **Самообучение**: Анализ ошибок + корректировка весов.
- **Расширение**: Фундаментальный анализ, нейросети (PyTorch), платные API (Тинькофф) позже.

### Модульная архитектура
- **Принципы**:
  - **Микромодульность**: Каждый компонент (данные, тех анализ, новости, риски, AI) — независимый модуль с интерфейсом (ABC) и стандартизированным выходом (`AnalyzerOutput` pydantic: score, confidence, reason).
  - **Dependency Injection**: Модули инжектируются через factory (`config.py: get_analyzer('news')`) для гибкости замены (например, `BasicNewsAnalyzer` на `LLMNewsAnalyzer`).
  - **Контракты**: Все модули возвращают `Dict[str, AnalyzerOutput]`, Aggregator собирает данные для Recommender.
  - **Масштабируемость**: Хуки для асинхронности (asyncio), микро-сервисов (FastAPI/gRPC), облачных БД (PostgreSQL).
- **Структура**:
  - **src/core/**: Модели (Quote, Recommendation, PortfolioPosition, Transaction, NewsMention, LogEntry), логирование, конфиги.
  - **src/data/**: DataProvider (MOEX, yfinance), DatabaseManager (DuckDB), NewsAnalyzer.
  - **src/analysis/**: TechnicalAnalyzer, NewsAnalyzer, RiskAnalyzer (все реализуют AnalyzerInterface).
  - **src/ai/**: Aggregator, Recommender, Backtester, PaperTrader, Learning.
  - **src/ui/**: MainWindow, вкладки, диалоги.
  - **tests/**: Unit и интеграционные тесты.
  - **docs/specs/**: Спецификации шагов (Step1.1.md).
  - **logs/**: Логи (`app_YYYYMMDD.log`).
  - **scripts/**: Утилиты (например, cron для retrain).
- **Пример интерфейса**:
  ```python
  from abc import ABC, abstractmethod
  from pydantic import BaseModel, validator
  from typing import Dict, List

  class AnalyzerInput(BaseModel):
      """Входные данные для анализаторов."""
      urls: List[str]  # Источники новостей
      tickers: List[str]  # Тикеры для анализа

      @validator('urls')
      def check_urls(cls, v):
          if not v:
              raise ValueError("URLs list cannot be empty")
          return v

  class AnalyzerOutput(BaseModel):
      """Выходные данные анализаторов."""
      score: float  # -1..1, оценка (например, sentiment)
      confidence: float  # 0..1, уверенность
      reason: str  # Краткое обоснование
      metadata: Dict[str, str] = {}  # Опционально для расширения

      @validator('confidence')
      def check_confidence(cls, v):
          if not 0 <= v <= 1:
              raise ValueError("Confidence must be between 0 and 1")
          return v

  class AnalyzerInterface(ABC):
      @abstractmethod
      def process(self, input_data: AnalyzerInput) -> Dict[str, AnalyzerOutput]:
          """Обрабатывает входные данные и возвращает результаты для тикеров.

          Args:
              input_data: Входные данные (urls, tickers).

          Returns:
              Dict[ticker, AnalyzerOutput]: Результаты для каждого тикера.

          Raises:
              ProcessingError: Если ошибка обработки.
          """
          pass
  ```
- **Пример имплементации** (BasicNewsAnalyzer):
  ```python
  import feedparser
  from src.core.exceptions import ProcessingError
  from src.core.logging import setup_logging

  class BasicNewsAnalyzer(AnalyzerInterface):
      def __init__(self):
          self.logger = setup_logging()

      def process(self, input_data: AnalyzerInput) -> Dict[str, AnalyzerOutput]:
          self.logger.info(f"[news] Обработка {input_data.tickers}")
          try:
              mentions = {ticker: 0 for ticker in input_data.tickers}
              for url in input_data.urls:
                  feed = feedparser.parse(url)
                  for entry in feed.entries:
                      for ticker in input_data.tickers:
                          if ticker.lower() in (entry.title + entry.description).lower():
                              mentions[ticker] += 1
              return {
                  ticker: AnalyzerOutput(
                      score=min(mentions[ticker] / 10, 1.0),
                      confidence=0.5,
                      reason=f"{mentions[ticker]} упоминаний в новостях",
                      metadata={"source": "RSS"}
                  )
                  for ticker in input_data.tickers
              }
          except Exception as e:
              self.logger.error(f"[news] Ошибка: {str(e)}")
              raise ProcessingError(f"Ошибка обработки новостей: {str(e)}")
  ```
- **Пример Aggregator**:
  ```python
  from typing import Dict
  from src.core.models import AnalyzerInput, AnalyzerOutput
  from src.core.exceptions import ProcessingError
  from src.core.logging import setup_logging

  class Aggregator:
      def __init__(self, analyzers: Dict[str, AnalyzerInterface]):
          self.analyzers = analyzers  # DI: {'technical': TechnicalAnalyzer, 'news': BasicNewsAnalyzer}
          self.logger = setup_logging()

      def aggregate(self, inputs: Dict[str, AnalyzerInput]) -> Dict[str, Dict[str, AnalyzerOutput]]:
          outputs = {}
          for name, analyzer in self.analyzers.items():
              try:
                  self.logger.info(f"[aggregator] Запуск {name}")
                  outputs[name] = analyzer.process(inputs[name])
              except ProcessingError as e:
                  self.logger.error(f"[aggregator] Ошибка {name}: {str(e)}")
                  outputs[name] = {ticker: AnalyzerOutput(score=0, confidence=0, reason=f"Ошибка: {str(e)}") for ticker in inputs[name].tickers}
          return outputs
  ```
- **Dependency Injection**:
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

### Поэтапный план разработки
План разделён на фазы с задачами, зависимостями, примерами кода, тестированием и проблемами. Время — для solo-разработки. Используйте Visual Studio Code с плагинами Python, Pylance.

#### Фаза 1: Прототип данных и базовый UI (4–6 недель)
**Цель**: Настроить сбор данных, хранение и интерфейс.
**Зависимости**: Python 3.9+, pip.
**Задачи**:
1. **Шаг 1.1: Настройка окружения и типизация данных**:
   - **Модуль**: `src/core/models.py`.
   - **Действия**:
     1. Создать структуру: `mkdir src src/core src/data src/analysis src/ai src/ui tests docs/specs logs models scripts`.
     2. Инициализировать Git: `git init`.
     3. Установить Python 3.9+, venv, зависимости: `pip install pydantic pytest requests pandas duckdb pyqt5 scikit-learn pandas_ta feedparser schedule`.
     4. Реализовать модели: Quote, Recommendation, PortfolioPosition, Transaction, NewsMention, LogEntry (pydantic).
     5. Тесты: `tests/test_models.py` (pytest, валидация).
   - **Масштабируемость**: Модели готовы для ORM, новые поля добавляются как optional.
   - **Код**:
     ```python
     from pydantic import BaseModel, validator
     from datetime import date, datetime
     from typing import Literal

     class Quote(BaseModel):
         ticker: str
         date: date
         open: float
         close: float
         volume: int

         @validator('open', 'close')
         def check_positive(cls, v):
             if v <= 0:
                 raise ValueError("Price must be positive")
             return v

     class Recommendation(BaseModel):
         ticker: str
         action: Literal["buy", "sell", "hold"]
         target_price: float
         stop_loss: float
         horizon: str  # Например, "4 weeks"
         confidence: float
         reason: str
         timestamp: datetime
     ```
   - **Тесты**:
     ```python
     import pytest
     from src.core.models import Quote, Recommendation
     from datetime import datetime

     def test_quote_validation():
         quote = Quote(ticker="SBER", date=date(2025, 10, 15), open=300.0, close=310.0, volume=1000)
         assert quote.close == 310.0
         with pytest.raises(ValueError):
             Quote(ticker="SBER", date=date(2025, 10, 15), open=-1, close=310.0, volume=1000)

     def test_recommendation():
         rec = Recommendation(
             ticker="SBER",
             action="buy",
             target_price=320.0,
             stop_loss=300.0,
             horizon="4 weeks",
             confidence=0.85,
             reason="RSI=75, mentions=10",
             timestamp=datetime.now()
         )
         assert rec.action == "buy"
     ```

2. **Шаг 1.2: Универсальный API (DataProvider)**:
   - **Модуль**: `src/data/providers.py`.
   - **Действия**:
     1. Реализовать ABC `DataProvider` с методом `fetch_quotes`.
     2. Подклассы: `MoexProvider`, `FallbackProvider` (yfinance).
     3. `UniversalDataFetcher`: Переключение при сбоях (например, HTTP 503).
     4. Логирование: `logging` в `logs/app_YYYYMMDD.log`.
     5. Тесты: Mock requests (`unittest.mock`).
   - **Масштабируемость**: Добавить Tinkoff API как новый провайдер через DI.
   - **Код**:
     ```python
     from abc import ABC, abstractmethod
     from src.core.models import Quote
     from datetime import date
     from typing import List

     class DataProvider(ABC):
         @abstractmethod
         def fetch_quotes(self, ticker: str, start_date: date, end_date: date) -> List[Quote]:
             """Получить котировки для тикера за период.

             Args:
                 ticker: Тикер актива.
                 start_date: Начальная дата.
                 end_date: Конечная дата.

             Returns:
                 List[Quote]: Список котировок.

             Raises:
                 ProcessingError: Если ошибка загрузки.
             """
             pass
     ```
   - **Тесты**:
     ```python
     import pytest
     from src.data.providers import DataProvider
     from unittest.mock import Mock

     def test_data_provider():
         provider = Mock(spec=DataProvider)
         provider.fetch_quotes.return_value = [Quote(ticker="SBER", date=date(2025, 10, 15), open=300.0, close=310.0, volume=1000)]
         quotes = provider.fetch_quotes("SBER", date(2025, 10, 1), date(2025, 10, 15))
         assert len(quotes) == 1
         assert quotes[0].ticker == "SBER"
     ```

3. **Шаг 1.3: Хранение данных**:
   - **Модуль**: `src/data/database.py`.
   - **Действия**:
     1. Реализовать `DatabaseManager` (DuckDB).
     2. Таблицы: quotes, portfolio, transactions, logs, recommendations.
     3. Методы: `save_quotes`, `load_quotes`, `save_portfolio`, `load_portfolio`.
     4. Тесты: Mock DuckDB connections.
   - **Масштабируемость**: Переход на PostgreSQL через ORM (SQLAlchemy) без изменения интерфейса.

4. **Шаг 1.4: RSS-парсинг для новостей**:
   - **Модуль**: `src/data/news_parser.py`.
   - **Действия**:
     1. Реализовать `NewsAnalyzerInterface` с `BasicNewsAnalyzer` (AnalyzerInterface).
     2. Парсинг RSS (feedparser), подсчёт упоминаний.
     3. Выход: `Dict[str, AnalyzerOutput]`.
     4. Тесты: Mock feedparser.
   - **Масштабируемость**: Замена на `LLMNewsAnalyzer` через DI.

5. **Шаг 1.5: UI в PyQt5**:
   - **Модуль**: `src/ui/main_window.py`.
   - **Действия**:
     1. Реализовать QMainWindow с вкладками (Дашборд, Портфель, Логи, Обучение).
     2. Интеграция: Aggregator, DatabaseManager через DI.
     3. Таблица рекомендаций, импорт/экспорт портфеля.
     4. Тесты: pytest-qt для UI, mock backend.
   - **Масштабируемость**: Observer pattern для real-time updates.
   - **Код**:
     ```python
     from PyQt5.QtWidgets import QMainWindow, QTabWidget, QPushButton, QLabel
     from src.ai.aggregator import Aggregator
     from src.data.database import DatabaseManager

     class MainWindow(QMainWindow):
         def __init__(self, aggregator: Aggregator, db: DatabaseManager):
             super().__init__()
             self.aggregator = aggregator  # DI
             self.db = db
             self.setWindowTitle("Investment Advisor")
             tabs = QTabWidget()
             self.setCentralWidget(tabs)
             self.status = QLabel("Последнее обновление: не выполнялось")
             self.statusBar().addWidget(self.status)
             update_btn = QPushButton("Обновить данные")
             update_btn.clicked.connect(self.update_data)
             self.statusBar().addWidget(update_btn)

         def update_data(self):
             inputs = self.db.load_inputs()  # Загрузка входных данных
             outputs = self.aggregator.aggregate(inputs)
             self.status.setText(f"Последнее обновление: {datetime.now()}")
     ```

#### Фаза 2: Модуль анализа и рекомендаций (6–8 недель)
**Задачи**:
1. **Шаг 2.1: Технический анализ**:
   - **Модуль**: `src/analysis/technical.py`.
   - Реализовать `TechnicalAnalyzer` (AnalyzerInterface).
   - Индикаторы: RSI, MACD, SMA/EMA (pandas_ta).
   - Выход: `Dict[str, AnalyzerOutput]`.
2. **Шаг 2.2: Риск-менеджмент**:
   - **Модуль**: `src/analysis/risk.py`.
   - Реализовать `RiskAnalyzer` (AnalyzerInterface).
   - Расчёт: стоп-лосс, волатильность, position sizing.
3. **Шаг 2.3: Рекомендации**:
   - **Модуль**: `src/ai/recommender.py`.
   - Aggregator: Собирает outputs от analyzers.
   - Recommender: RandomForestClassifier, GradientBoostingClassifier или SVM.
   - Стратегии: моментум (2–4 недели), тренды (4–8 недель).
4. **Шаг 2.4: Интеграция в UI**:
   - Таблица рекомендаций (QTableWidget).
   - Диалог детализации (QDialog).

#### Фаза 3: Система обучения и валидации (6–8 недель)
**Задачи**:
1. **Шаг 3.1: Backtesting**:
   - **Модуль**: `src/ai/backtest.py`.
   - Симуляция на исторических данных (3 года).
   - Метрики: Win Rate, Sharpe Ratio, Max Drawdown.
2. **Шаг 3.2: Paper trading**:
   - **Модуль**: `src/ai/paper_trading.py`.
   - Реал-тайм симуляция портфеля.
3. **Шаг 3.3: Самообучение**:
   - **Модуль**: `src/ai/learning.py`.
   - Анализ ошибок, retrain, A/B-тестирование (RandomForest vs SVM).
4. **Шаг 3.4: UI обучения**:
   - Таблица метрик, отчёты в QTextEdit.

#### Фаза 4: Полировка и оптимизация (4–6 недель)
**Задачи**:
1. Оптимизация: cProfile для профилирования, async для загрузки данных.
2. Расширение: PyTorch (LSTM), MLflow для трекинга, Tinkoff API.
3. Тестирование: PyInstaller для сборки, Docker для контейнеризации.

### Архитектурная схема
```
[Пользователь] -> [PyQt5 UI]
  ├── Дашборд: Aggregator -> Recommender
  ├── Портфель: DatabaseManager
  ├── Логи: LogEntry
  └── Обучение: Backtester, Learning

[Python Backend]
  ├── Data Layer: DataProvider (MOEX/yfinance), DatabaseManager (DuckDB), NewsAnalyzer
  ├── Analysis Layer: TechnicalAnalyzer, NewsAnalyzer, RiskAnalyzer (AnalyzerInterface)
  ├── AI Layer: Aggregator, Recommender (RF/GB/SVM), Learning (retrain)
  └── Automation: schedule, QTimer

[DuckDB] -> Tables: quotes, portfolio, transactions, recommendations, logs
```

### Спецификации
- **Портфель**: Таблицы `portfolio`, `transactions` в DuckDB.
- **Рекомендации**: JSON-структура, таблица `recommendations`.
- **Валидация**: Backtesting, paper trading, метрики.
- **Метрики успешности**: Win Rate >60%, Sharpe >1.0, Max Drawdown <20%.

### Регламент модульности (новое)
Для соответствия `ModularityConcept.md`:
- **Контракты**:
  - Каждый модуль реализует ABC (`AnalyzerInterface`, `DataProvider`) с методом `process` (или `fetch_quotes` для данных).
  - Вход: Pydantic `AnalyzerInput` (или специфичный, например, `DataInput`).
  - Выход: `Dict[str, AnalyzerOutput]` для анализаторов, `List[Quote]` для DataProvider.
  - Исключения: Кастомные (`ProcessingError`), логируются в `logs/app_YYYYMMDD.log`.
  - Backward-compatibility: Новые поля в pydantic — optional, удаление полей — через новый контракт.
- **Dependency Injection**:
  - Модули инжектируются через factory (`config.py`).
  - Пример: `Aggregator(analyzers={'news': get_analyzer('basic_news')})`.
  - `config.yaml` для выбора имплементаций.
- **Тестирование**:
  - Unit: Mock ABC, coverage >80% (`pytest tests/test_<module>.py`).
  - Integration: Проверка контрактов (`Dict[str, AnalyzerOutput]`).
  - E2E: Полный цикл в `tests/integration/test_full.py`.
- **Код**:
  - PEP8, форматтер black.
  - Google-style docstrings.
  - Именование: `<Module>Interface`, `<Type><Module>` (например, `BasicNewsAnalyzer`).
- **Git**:
  - Ветки: `feature/<module>-<feature>` (например, `feature/news-llm`).
  - Commits: `feat: add news analyzer`, `fix: handle API error`.
  - PR: Review, CI (pytest, black).

### Следующие шаги
Начать с Фазы 1, Шаг 1.1. Для кода: "Реализуй Шаг 1.1 по Step1.1.md, предоставь код и тесты."