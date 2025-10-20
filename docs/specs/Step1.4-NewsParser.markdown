# Шаг 1.4: Реализация анализа новостей (NewsAnalyzer)

## Введение
Этот документ описывает реализацию модуля анализа новостей (`NewsAnalyzer`) для парсинга RSS-лент и формирования оценок для тикеров на основе упоминаний. Модуль следует принципам модульности из `ModularityConcept.md`: чёткий контракт через ABC (`AnalyzerInterface`) и pydantic модели, независимость, Dependency Injection (DI) через factory, простота для MVP с хуками для масштабирования. Для MVP используется библиотека `feedparser` для парсинга RSS (например, Интерфакс/РИА), а анализ ограничивается подсчётом упоминаний тикеров в заголовках и описаниях новостей. Модуль интегрируется с `DatabaseManager` для логирования и хранения результатов, если потребуется.

**Цели шага**:
- Создать `NewsAnalyzer` для анализа RSS-лент.
- Реализовать контракт через `AnalyzerInterface` с методом `process`, возвращающим `Dict[str, AnalyzerOutput]`.
- Использовать pydantic модели для входа (`AnalyzerInput`) и выхода (`AnalyzerOutput`).
- Обеспечить интеграцию с `Aggregator` через DI.
- Добавить тесты (`pytest`) с mock-данными.
- Реализовать логирование и обработку ошибок.
- Подготовить к масштабированию (например, замена на LLM-анализ).

**Место в архитектуре**:
- Модуль: `src/analysis/news.py`.
- Зависимости: `feedparser`, `pydantic`, `src/core/models.py`, `src/core/logging.py`, `src/core/exceptions.py`.
- Интеграция: `NewsAnalyzer` инжектируется в `Aggregator` через `config.yaml`.

## Требования
- **Источник данных**: RSS-ленты (например, Интерфакс: `https://www.interfax.ru/rss`, РИА: `https://ria.ru/export/rss2/archive/index.xml`).
- **Анализ**: Подсчёт упоминаний тикеров в заголовках и описаниях новостей.
- **Контракт**:
  - Вход: `AnalyzerInput` (список URL RSS-лент, список тикеров).
  - Выход: `Dict[str, AnalyzerOutput]` (оценка, уверенность, обоснование для каждого тикера).
- **Оффлайн-режим**: Fallback — возврат `AnalyzerOutput(score=0, confidence=0)` при ошибке API.
- **Ошибки**: Кастомное исключение (`ProcessingError`), логи в `logs/app_YYYYMMDD.log`.
- **Тесты**: Unit-тесты с mock-данными (coverage >80%).
- **Масштаб**: Хук для замены RSS на LLM (например, Grok API).

## Контракт модуля
Модуль реализует `AnalyzerInterface`, определённый в `src/core/interfaces.py` (или `src/core/models.py`, в зависимости от структуры). Контракт уже задан в `ModularityConcept.md`, но здесь уточняется для новостей.

### Абстрактный класс
```python
from abc import ABC, abstractmethod
from typing import Dict
from pydantic import BaseModel

class AnalyzerInput(BaseModel):
    """Входные данные для анализаторов."""
    urls: List[str]  # Список RSS-лент
    tickers: List[str]  # Список тикеров для анализа

class AnalyzerOutput(BaseModel):
    """Выходные данные анализаторов."""
    score: float  # Оценка (-1..1, например, нормализованное количество упоминаний)
    confidence: float  # Уверенность (0..1)
    reason: str  # Обоснование (например, "5 упоминаний в новостях")

class AnalyzerInterface(ABC):
    @abstractmethod
    def process(self, input_data: AnalyzerInput) -> Dict[str, AnalyzerOutput]:
        """Анализирует данные и возвращает результаты для тикеров.

        Args:
            input_data: Входные данные (urls, tickers).

        Returns:
            Dict[ticker, AnalyzerOutput]: Результаты анализа.

        Raises:
            ProcessingError: Если ошибка обработки.
        """
        pass
```

**Правила для контракта**:
- Метод: Только `process` (sync, без async для MVP).
- Вход: `AnalyzerInput` с обязательными полями `urls` и `tickers`.
- Выход: `Dict[str, AnalyzerOutput]` с оценкой, уверенностью и обоснованием.
- Исключения: `ProcessingError` для ошибок парсинга/анализа.
- Backward-compatibility: Новые поля в `AnalyzerOutput` — optional.

## Реализация NewsAnalyzer
Модуль `NewsAnalyzer` реализует `AnalyzerInterface`, парсит RSS-ленты и подсчитывает упоминания тикеров. Для MVP анализ простой: `score` — нормализованное количество упоминаний (делим на максимум), `confidence` — фиксированное значение (0.5), `reason` — текстовое описание.

### Код
```python
# src/analysis/news.py
"""Модуль для анализа новостей через RSS-ленты."""

import feedparser
from typing import Dict, List
from pydantic import BaseModel
from src.core.interfaces import AnalyzerInterface, AnalyzerInput, AnalyzerOutput
from src.core.exceptions import ProcessingError
from src.core.logging import setup_logging

class BasicNewsAnalyzer(AnalyzerInterface):
    def __init__(self):
        """Инициализация анализатора новостей."""
        self.logger = setup_logging()

    def process(self, input_data: AnalyzerInput) -> Dict[str, AnalyzerOutput]:
        """Анализирует RSS-ленты и возвращает оценки для тикеров.

        Args:
            input_data: Входные данные (urls, tickers).

        Returns:
            Dict[ticker, AnalyzerOutput]: Оценки на основе упоминаний.

        Raises:
            ProcessingError: Если ошибка парсинга RSS.
        """
        try:
            self.logger.info(f"[news] Анализ RSS для тикеров: {input_data.tickers}")
            mentions = self._parse_rss(input_data.urls, input_data.tickers)
            max_mentions = max(mentions.values(), default=1) or 1  # Избегаем деления на 0
            return {
                ticker: AnalyzerOutput(
                    score=min(mentions[ticker] / max_mentions, 1.0),  # Нормализация
                    confidence=0.5,  # Фиксированная уверенность для MVP
                    reason=f"Найдено {mentions[ticker]} упоминаний в новостях"
                )
                for ticker in input_data.tickers
            }
        except Exception as e:
            self.logger.error(f"[news] Ошибка анализа новостей: {str(e)}")
            raise ProcessingError(f"Ошибка обработки RSS: {str(e)}")

    def _parse_rss(self, urls: List[str], tickers: List[str]) -> Dict[str, int]:
        """Парсит RSS-ленты и подсчитывает упоминания тикеров.

        Args:
            urls: Список RSS-лент.
            tickers: Список тикеров.

        Returns:
            Dict[ticker, int]: Количество упоминаний для каждого тикера.
        """
        mentions = {ticker: 0 for ticker in tickers}
        for url in urls:
            try:
                feed = feedparser.parse(url)
                if feed.bozo:  # Ошибка парсинга RSS
                    self.logger.warning(f"[news] Неверный RSS: {url}")
                    continue
                for entry in feed.entries:
                    text = (entry.get('title', '') + ' ' + entry.get('description', '')).lower()
                    for ticker in tickers:
                        if ticker.lower() in text:
                            mentions[ticker] += 1
            except Exception as e:
                self.logger.warning(f"[news] Ошибка парсинга {url}: {str(e)}")
        return mentions
```

### Пояснения к реализации
- **Парсинг**: Используется `feedparser` для чтения RSS (заголовки и описания).
- **Анализ**: Подсчёт упоминаний тикеров в тексте (case-insensitive).
- **Score**: Нормализованное количество упоминаний (`mentions[ticker] / max_mentions`).
- **Confidence**: Фиксированное 0.5 (для MVP, позже — динамическое, например, от качества RSS).
- **Reason**: Текстовое описание количества упоминаний.
- **Ошибки**: Логируются, при сбое RSS возвращается `AnalyzerOutput(score=0)` через `ProcessingError`.

## Интеграция с другими модулями
- **Aggregator**: Вызывает `NewsAnalyzer.process(input)` для получения оценок, инжектирует через DI:
  ```python
  # src/core/config.py
  def get_analyzer(analyzer_type: str) -> AnalyzerInterface:
      analyzers = {'basic_news': BasicNewsAnalyzer}
      return analyzers[analyzer_type]()
  ```
  ```python
  # src/ai/aggregator.py
  aggregator = Aggregator(analyzers={'news': get_analyzer('basic_news')})
  outputs = aggregator.aggregate({'news': AnalyzerInput(urls=['https://ria.ru/rss'], tickers=['SBER', 'GAZP'])})
  ```
- **DatabaseManager**: Сохраняет логи через `DatabaseManager.save([Log(...), ...], "logs")`.
- **MainWindow**: Получает результаты через `Aggregator` для отображения в UI (вкладка "Дашборд").

## Тестирование
Тесты в `tests/test_news_analyzer.py` проверяют парсинг, формирование оценок и обработку ошибок.

```python
import pytest
from unittest.mock import patch
from src.analysis.news import BasicNewsAnalyzer, AnalyzerInput, AnalyzerOutput
from src.core.exceptions import ProcessingError

@pytest.fixture
def analyzer():
    return BasicNewsAnalyzer()

@patch('feedparser.parse')
def test_news_analyzer_success(mock_parse, analyzer):
    # Mock RSS-данных
    mock_parse.return_value = {
        'entries': [
            {'title': 'SBER растёт', 'description': 'SBER в новостях'},
            {'title': 'Новости', 'description': 'GAZP падает'}
        ],
        'bozo': 0
    }
    input_data = AnalyzerInput(urls=['https://example.com/rss'], tickers=['SBER', 'GAZP'])
    output = analyzer.process(input_data)
    assert isinstance(output, Dict)
    assert 'SBER' in output
    assert output['SBER'].score > 0
    assert output['SBER'].confidence == 0.5
    assert 'упоминаний' in output['SBER'].reason
    assert output['GAZP'].score > 0

@patch('feedparser.parse')
def test_news_analyzer_empty_feed(mock_parse, analyzer):
    mock_parse.return_value = {'entries': [], 'bozo': 0}
    input_data = AnalyzerInput(urls=['https://example.com/rss'], tickers=['SBER'])
    output = analyzer.process(input_data)
    assert output['SBER'].score == 0
    assert output['SBER'].confidence == 0.5
    assert '0 упоминаний' in output['SBER'].reason

@patch('feedparser.parse')
def test_news_analyzer_error(mock_parse, analyzer):
    mock_parse.side_effect = Exception("RSS unavailable")
    input_data = AnalyzerInput(urls=['https://example.com/rss'], tickers=['SBER'])
    with pytest.raises(ProcessingError):
        analyzer.process(input_data)
```

## Логирование
- Логи сохраняются в `logs/app_YYYYMMDD.log` и в таблице `logs` через `DatabaseManager`.
- Категории: `news`, `error`.
- Пример:
  ```
  2025-10-20 18:30: [news] Анализ RSS для тикеров: ['SBER', 'GAZP']
  2025-10-20 18:31: [error] Ошибка парсинга https://example.com/rss: RSS unavailable
  ```

## Обработка ошибок
- Кастомное исключение:
  ```python
  # src/core/exceptions.py
  class ProcessingError(Exception):
      """Ошибка обработки данных в анализаторах."""
      pass
  ```
- Fallback: При ошибке RSS возвращается `ProcessingError`, Aggregator формирует `AnalyzerOutput(score=0, confidence=0)`.

## Масштабируемость
- **Замена реализации**: Новый подкласс `LLMNewsAnalyzer` (например, с Grok API), реализующий тот же `AnalyzerInterface`.
  ```python
  class LLMNewsAnalyzer(AnalyzerInterface):
      def process(self, input_data: AnalyzerInput) -> Dict[str, AnalyzerOutput]:
          # Логика с LLM
          return {ticker: AnalyzerOutput(score=0.7, confidence=0.9, reason="LLM sentiment") for ticker in input_data.tickers}
  ```
  Смена в `config.yaml`: `news_analyzer: llm`.
- **Хук для async**: В будущем добавить `async def process` для asyncio (HTTP-запросы к RSS/LLM).
- **Микро-сервисы**: Переход на REST (FastAPI) с JSON-сериализацией `AnalyzerOutput`.

## Следующие шаги
- Интегрировать `NewsAnalyzer` в `Aggregator` и UI (Шаг 1.5).
- Реализовать `DataProvider` (Шаг 1.2).
- Проверить зависимости: `pip install feedparser`.