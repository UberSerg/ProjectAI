# Концепция модульности в проекте

## Введение
Концепция модульности — основа архитектуры приложения для инвестиций на Московской бирже (MOEX). Она упрощает разработку, тестирование и улучшение, сохраняя возможность масштабирования. Для MVP строим простой модульный монолит (все в одном процессе Python), где каждый модуль — независимый компонент с чётким контрактом (интерфейсы ABC и pydantic модели). Это позволяет менять реализацию модуля (например, анализ новостей с RSS на LLM) без касания других частей, если контракт сохранён. Подход соответствует SOLID (Single Responsibility, Dependency Inversion) и готовит к микро-сервисам (например, Docker + REST).

**Цели модульности**:
- **Простота**: Минимум кода, лёгкость понимания для разработчиков.
- **Декомпозиция**: Разделение задач на маленькие модули.
- **Коллаборация**: Команды работают над своими модулями без конфликтов.
- **Гибкость**: Улучшения затрагивают только целевой модуль, не ломая "верхние" (UI, Aggregator) или "нижние" (DataProvider) слои.
- **Масштабируемость**: Подготовка к асинхронности и микро-сервисам без переписывания.

**Принцип**: Каждый модуль делает одну задачу, общается через контракт, реализация скрыта. Для MVP фокус на простоте и скорости, с хуками для роста.

## Техническая реализация модульности
Модульность строится на простых правилах, чтобы ускорить разработку MVP, но оставить возможность масштабирования.

### 1. Контракты через ABC и pydantic
Каждый модуль имеет:
- **Абстрактный класс (ABC)**: Определяет методы модуля (из `abc` Python). Один ключевой метод — `process` — для обработки данных. Это гарантирует одинаковую сигнатуру.
- **Pydantic модели**: Вход/выход — через `pydantic.BaseModel` с базовой валидацией (типы, обязательные поля). Это упрощает проверку данных и сериализацию.
- **Простота**: Только sync методы для MVP, без async (добавим позже через хук).

**Пример контракта для анализа новостей**:
```python
from abc import ABC, abstractmethod
from pydantic import BaseModel
from typing import Dict, List

class AnalyzerInput(BaseModel):
    """Входные данные для анализаторов."""
    urls: List[str]  # Источники новостей
    tickers: List[str]  # Тикеры для анализа

class AnalyzerOutput(BaseModel):
    """Выходные данные анализаторов."""
    score: float  # -1..1, оценка (например, sentiment)
    confidence: float  # 0..1, уверенность
    reason: str  # Краткое обоснование

class AnalyzerInterface(ABC):
    @abstractmethod
    def process(self, input_data: AnalyzerInput) -> Dict[str, AnalyzerOutput]:
        """Обрабатывает данные и возвращает результаты для тикеров.

        Args:
            input_data: Входные данные (urls, tickers).

        Returns:
            Dict[ticker, AnalyzerOutput]: Результаты для каждого тикера.
        """
        pass
```

**Имплементация (BasicNewsAnalyzer)**:
```python
import feedparser
from src.core.exceptions import ProcessingError

class BasicNewsAnalyzer(AnalyzerInterface):
    def process(self, input_data: AnalyzerInput) -> Dict[str, AnalyzerOutput]:
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
                    reason=f"{mentions[ticker]} упоминаний в новостях"
                )
                for ticker in input_data.tickers
            }
        except Exception as e:
            raise ProcessingError(f"Ошибка обработки новостей: {str(e)}")
```

**Правила для контрактов**:
- Один ABC на модуль с одним методом `process`.
- Вход: Pydantic `AnalyzerInput` (или специфичный, например, `DataInput`).
- Выход: `Dict[str, AnalyzerOutput]` (для анализаторов) или `List[Model]` (для DataProvider).
- Исключения: Кастомные (`ProcessingError`), логируются в `logs/app_YYYYMMDD.log`.
- Backward-compatibility: Новые поля в pydantic — optional, удаление полей — через новый контракт.

### 2. Входы и выходы между модулями
- **Вход**: Pydantic model (например, `AnalyzerInput` с `urls`, `tickers`). Простая валидация (не пустые списки).
- **Выход**: `Dict[str, AnalyzerOutput]` для анализаторов, `List[Model]` для данных (например, `List[Quote]`).
- **Передача**: Прямой вызов метода (`analyzer.process(input)`).
- **Интеграция**:
  - Aggregator собирает результаты: `outputs = {name: analyzer.process(input) for name, analyzer in analyzers.items()}`.
  - Dependency Injection (DI): Модули передаются через конструктор (`Aggregator(news_analyzer=BasicNewsAnalyzer())`).
- **Правила**:
  - Вход: Обязательные поля — required, опциональные — `None`.
  - Выход: Стандартизированный, проверяется тестами.
  - Логирование: Каждый вызов логируется (`logger.info("[news] Processing tickers")`).
  - Ошибки: Catch в Aggregator, fallback — `AnalyzerOutput(score=0, confidence=0, reason="Ошибка")`.

**Пример Aggregator**:
```python
from typing import Dict
from src.core.models import AnalyzerOutput
from src.core.exceptions import ProcessingError
from src.core.logging import setup_logging

class Aggregator:
    def __init__(self, analyzers: Dict[str, AnalyzerInterface]):
        self.analyzers = analyzers  # DI: {'news': BasicNewsAnalyzer()}
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

### 3. Регламент разработки модулей
Для простоты и скорости MVP:
- **Структура файла**:
  ```python
  # src/<module>/<name>.py
  """Краткое описание модуля (например, Анализ новостей через RSS)."""

  from pydantic import BaseModel
  from abc import ABC, abstractmethod
  from src.core.models import AnalyzerInput, AnalyzerOutput
  from src.core.exceptions import ProcessingError
  from src.core.logging import setup_logging

  logger = setup_logging()

  class <Module>Interface(ABC):
      @abstractmethod
      def process(self, input_data: AnalyzerInput) -> Dict[str, AnalyzerOutput]:
          pass

  class <Module>Impl(<Module>Interface):
      def process(self, input_data: AnalyzerInput) -> Dict[str, AnalyzerOutput]:
          logger.info(f"[{self.__class__.__name__}] Обработка {input_data.tickers}")
          try:
              # Логика
              return {}
          except Exception as e:
              logger.error(f"[{self.__class__.__name__}] Ошибка: {str(e)}")
              raise ProcessingError(str(e))
  ```
- **Именование**:
  - Интерфейсы: `<Module>Interface` (например, `NewsAnalyzerInterface`).
  - Имплементации: `<Type><Module>` (например, `BasicNewsAnalyzer`).
  - Функции: snake_case, понятные (например, `parse_rss`).
- **Документация**:
  - Google-style docstrings:
    ```python
    def process(self, input_data: AnalyzerInput) -> Dict[str, AnalyzerOutput]:
        """Анализирует новости для тикеров.

        Args:
            input_data: Входные данные (urls, tickers).

        Returns:
            Dict[ticker, AnalyzerOutput]: Результаты анализа.

        Raises:
            ProcessingError: Если ошибка обработки.
        """
    ```
  - README.md в `src/<module>/` (контракт, примеры).
- **Тестирование**:
  - Unit: `tests/test_<module>.py`, mock ABC.
  - Example:
    ```python
    import pytest
    from src.analysis.news import BasicNewsAnalyzer, AnalyzerInput

    def test_news_analyzer():
        analyzer = BasicNewsAnalyzer()
        input_data = AnalyzerInput(urls=["https://example.com/rss"], tickers=["SBER"])
        output = analyzer.process(input_data)
        assert isinstance(output, Dict)
        assert "SBER" in output
        assert isinstance(output["SBER"], AnalyzerOutput)
    ```
- **Логирование**: В `logs/app_YYYYMMDD.log`, категории (`analyzer`, `error`).
- **Исключения**: `ProcessingError`, иерархия от `BaseAppError`.

### 4. Декомпозиция больших модулей
- **Принципы**:
  - Один модуль — одна задача (например, `news` только анализирует, не парсит).
  - Большие модули разбиваются на подмодули (например, `analysis` -> `technical`, `news`, `risk`).
  - Для MVP: Минимальная декомпозиция, только ключевые подмодули.
- **Процесс**:
  1. Определите задачу: Например, `news` = анализ упоминаний.
  2. Если модуль сложный, разбейте на подмодули (но для MVP оставляем просто, например, `NewsAnalyzer` без `Parser`).
  3. Композиция через DI: Подмодули инжектируются в главный.
- **Пример**:
  - `analysis`:
    - `TechnicalAnalyzer` (RSI, MACD).
    - `NewsAnalyzer` (упоминания).
    - `RiskAnalyzer` (стоп-лосс).
  - Позже: `NewsAnalyzer` = `Parser` + `Analyzer`.

### 5. Разработка разными командами
- **Процесс**:
  1. Команда берёт модуль (например, `news`, `ai`).
  2. Работает в ветке: `feature/news-llm`.
  3. Тесты: Mock ABC, coverage >80%.
  4. PR: Проверка контракта, CI (pytest, black).
- **Целостность**:
  - Контракты фиксированы (изменение = новый ABC).
  - Mock других модулей: `unittest.mock`.
  - Документация: README в `src/<module>/`.
- **Коллаборация**: Еженедельные встречи, общие `docs/interfaces/`.

### 6. Улучшения без касания других модулей
- **Процесс**:
  1. Новый подкласс (например, `LLMNewsAnalyzer`).
  2. Тот же контракт (`process` -> `Dict[str, AnalyzerOutput]`).
  3. Тесты: `pytest tests/test_news.py`.
  4. Смена в DI: `config.yaml` (`news_analyzer: llm`).
- **Стадии**:
  - MVP: `BasicNewsAnalyzer` (RSS).
  - Стадия 2: `LLMNewsAnalyzer`, смена в config, UI/Aggregator не меняются.
- **Без касания**:
  - Новые поля в `AnalyzerOutput` — optional.
  - Breaking changes: Новый ABC (`AnalyzerInterfaceV2`), адаптер для старых модулей.

### 7. Dependency Injection (DI)
- **Реализация**:
  - `config.yaml`:
    ```yaml
    analyzers:
      news: BasicNewsAnalyzer
    ```
  - Factory:
    ```python
    from src.analysis.news import BasicNewsAnalyzer

    def get_analyzer(analyzer_type: str) -> AnalyzerInterface:
        return {'basic': BasicNewsAnalyzer}[analyzer_type]()
    ```
  - Использование:
    ```python
    aggregator = Aggregator(analyzers={'news': get_analyzer(config['analyzers']['news'])})
    ```
- **Правила**:
  - DI через конструктор.
  - Config читается разово (`src/core/config.py`).
  - Fallback: `AnalyzerOutput(score=0)` при ошибке.

### 8. Масштабируемость
- **MVP**: Sync, монолит.
- **Стадия 2**: Async через `asyncio` (добавить `async def process`).
- **Стадия 3**: Микро-сервисы (REST, FastAPI, Docker).
- **Контракты**: Те же pydantic модели для REST.

## Регламент
1. **Модуль**:
   - ABC с `process`, вход — pydantic, выход — `Dict[str, AnalyzerOutput]`.
   - Логи: `logger.info("[module] Action")`.
   - Исключения: `ProcessingError`.
2. **Код**:
   - PEP8, black.
   - Docstrings: Google style.
   - Imports: Absolute.
3. **Тесты**:
   - Unit: Mock ABC.
   - Run: `pytest tests/`.
4. **Git**:
   - Ветки: `feature/<module>-<feature>`.
   - Commits: `feat: add news`, `fix: error handling`.
5. **Документация**:
   - README в `src/<module>/`.
   - Spec в `docs/specs/`.