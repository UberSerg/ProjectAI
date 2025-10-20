# Шаг 2.1: Реализация технического анализа (TechnicalAnalyzer)

## Введение
Этот документ описывает реализацию модуля технического анализа (`TechnicalAnalyzer`) для расчёта индикаторов (RSI, MACD, SMA/EMA) на основе котировок акций, хранящихся в DuckDB. Модуль следует принципам модульности из `ModularityConcept.md`: чёткий контракт через `AnalyzerInterface` и pydantic модели, независимость, Dependency Injection (DI) через factory, простота для MVP с хуками для масштабирования. Для MVP используются индикаторы RSI (14), MACD (12, 26, 9) и SMA/EMA (20), реализованные через `pandas_ta`. Модуль интегрируется с `Aggregator` для формирования рекомендаций и `DatabaseManager` для доступа к данным котировок.

**Цели шага**:
- Создать `TechnicalAnalyzer` для расчёта индикаторов (RSI, MACD, SMA/EMA).
- Реализовать контракт через `AnalyzerInterface` с методом `process`, возвращающим `Dict[str, AnalyzerOutput]`.
- Использовать pydantic модели для входа (`AnalyzerInput`) и выхода (`AnalyzerOutput`).
- Интегрировать с `DatabaseManager` для получения котировок.
- Добавить тесты (`pytest`) с mock-данными.
- Реализовать логирование и обработку ошибок.
- Подготовить к масштабированию (например, добавление новых индикаторов или PyTorch).

**Место в архитектуре**:
- Модуль: `src/analysis/technical.py`.
- Зависимости: `pandas`, `pandas_ta`, `pydantic`, `src/core/models.py`, `src/core/interfaces.py`, `src/core/logging.py`, `src/core/exceptions.py`, `src/data/database_manager.py`.
- Интеграция: `TechnicalAnalyzer` инжектируется в `Aggregator` через `config.yaml`.

## Требования
- **Источник данных**: Котировки из таблицы `quotes` в DuckDB (получаются через `DatabaseManager`).
- **Индикаторы**:
  - RSI (14): Относительный индекс силы, диапазон 0–100.
  - MACD (12, 26, 9): Разница между EMA(12) и EMA(26), сигнал — EMA(9) от разницы.
  - SMA/EMA (20): Простая и экспоненциальная скользящие средние.
- **Контракт**:
  - Вход: `AnalyzerInput` (список тикеров, опциональный диапазон дат).
  - Выход: `Dict[str, AnalyzerOutput]` (оценка, уверенность, обоснование для каждого тикера).
- **Оффлайн-режим**: Данные из DuckDB, fallback при отсутствии данных — `AnalyzerOutput(score=0, confidence=0)`.
- **Ошибки**: Кастомное исключение (`ProcessingError`), логи в `logs/app_YYYYMMDD.log`.
- **Тесты**: Unit-тесты с mock-данными (coverage >80%).
- **Масштаб**: Хук для добавления индикаторов или ML-анализа (PyTorch).

## Контракт модуля
Модуль реализует `AnalyzerInterface`, определённый в `src/core/interfaces.py` (или `src/core/models.py`). Контракт повторяет тот, что используется в `Step1.4-NewsParser.md`, но адаптирован для технического анализа.

### Абстрактный класс
```python
from abc import ABC, abstractmethod
from typing import Dict, List
from pydantic import BaseModel
from datetime import date

class AnalyzerInput(BaseModel):
    """Входные данные для анализаторов."""
    tickers: List[str]  # Список тикеров
    date_range: tuple[date, date] | None = None  # Опциональный диапазон дат

class AnalyzerOutput(BaseModel):
    """Выходные данные анализаторов."""
    score: float  # Оценка (-1..1, на основе индикаторов)
    confidence: float  # Уверенность (0..1)
    reason: str  # Обоснование (например, "RSI=75, MACD crossover")

class AnalyzerInterface(ABC):
    @abstractmethod
    def process(self, input_data: AnalyzerInput) -> Dict[str, AnalyzerOutput]:
        """Анализирует данные и возвращает результаты для тикеров.

        Args:
            input_data: Входные данные (tickers, date_range).

        Returns:
            Dict[ticker, AnalyzerOutput]: Результаты анализа.

        Raises:
            ProcessingError: Если ошибка обработки.
        """
        pass
```

**Правила для контракта**:
- Метод: Только `process` (sync, без async для MVP).
- Вход: `AnalyzerInput` с обязательным полем `tickers`, опциональным `date_range`.
- Выход: `Dict[str, AnalyzerOutput]` с оценкой, уверенностью и обоснованием.
- Исключения: `ProcessingError` для ошибок расчёта индикаторов.
- Backward-compatibility: Новые поля в `AnalyzerOutput` — optional.

## Реализация TechnicalAnalyzer
Модуль `TechnicalAnalyzer` реализует `AnalyzerInterface`, загружает котировки через `DatabaseManager` и вычисляет индикаторы с помощью `pandas_ta`. Для MVP оценка (`score`) основана на простых правилах:
- RSI > 70: Перекупленность (score=-0.5), RSI < 30: Перепроданность (score=0.5).
- MACD: Положительный кроссовер (score=0.5), отрицательный (score=-0.5).
- SMA/EMA: Цена выше SMA/EMA (score=0.3), ниже (score=-0.3).
- Итоговый `score`: Среднее арифметическое (в диапазоне -1..1).
- `confidence`: Фиксированное 0.5 (для MVP, позже — динамическое).

### Код
```python
# src/analysis/technical.py
"""Модуль для технического анализа котировок (RSI, MACD, SMA/EMA)."""

import pandas as pd
import pandas_ta as ta
from typing import Dict, List
from src.core.interfaces import AnalyzerInterface, AnalyzerInput, AnalyzerOutput
from src.core.exceptions import ProcessingError
from src.core.logging import setup_logging
from src.data.database_manager import DatabaseManager
from src.core.models import Quote
from datetime import date, timedelta

class TechnicalAnalyzer(AnalyzerInterface):
    def __init__(self, db_manager: DatabaseManager):
        """Инициализация анализатора.

        Args:
            db_manager: Модуль для доступа к котировкам.
        """
        self.db_manager = db_manager
        self.logger = setup_logging()

    def process(self, input_data: AnalyzerInput) -> Dict[str, AnalyzerOutput]:
        """Вычисляет индикаторы и возвращает оценки для тикеров.

        Args:
            input_data: Входные данные (tickers, date_range).

        Returns:
            Dict[ticker, AnalyzerOutput]: Оценки на основе индикаторов.

        Raises:
            ProcessingError: Если ошибка расчёта.
        """
        try:
            self.logger.info(f"[technical] Анализ для тикеров: {input_data.tickers}")
            results = {}
            # Устанавливаем диапазон дат: последние 60 дней для индикаторов
            end_date = date.today()
            start_date = input_data.date_range[0] if input_data.date_range else end_date - timedelta(days=60)
            for ticker in input_data.tickers:
                quotes = self.db_manager.load(
                    f"SELECT * FROM quotes WHERE ticker = '{ticker}' AND date >= '{start_date}' AND date <= '{end_date}' ORDER BY date",
                    Quote
                )
                if len(quotes) < 20:  # Минимально для SMA/EMA
                    results[ticker] = AnalyzerOutput(score=0, confidence=0, reason="Недостаточно данных")
                    continue
                df = pd.DataFrame([q.dict() for q in quotes])
                score, reason = self._calculate_indicators(df)
                results[ticker] = AnalyzerOutput(
                    score=score,
                    confidence=0.5,  # Фиксированная уверенность для MVP
                    reason=reason
                )
            return results
        except Exception as e:
            self.logger.error(f"[technical] Ошибка анализа: {str(e)}")
            raise ProcessingError(f"Ошибка обработки индикаторов: {str(e)}")

    def _calculate_indicators(self, df: pd.DataFrame) -> tuple[float, str]:
        """Вычисляет индикаторы (RSI, MACD, SMA/EMA) и возвращает оценку.

        Args:
            df: DataFrame с котировками (ticker, date, open, close, volume).

        Returns:
            tuple[float, str]: Оценка (-1..1) и обоснование.
        """
        try:
            scores = []
            reasons = []

            # RSI (14)
            df['rsi'] = ta.rsi(df['close'], length=14)
            rsi = df['rsi'].iloc[-1]
            if pd.notna(rsi):
                if rsi > 70:
                    scores.append(-0.5)  # Перекупленность
                    reasons.append(f"RSI={rsi:.1f} (перекупленность)")
                elif rsi < 30:
                    scores.append(0.5)  # Перепроданность
                    reasons.append(f"RSI={rsi:.1f} (перепроданность)")
                else:
                    scores.append(0)
                    reasons.append(f"RSI={rsi:.1f} (нейтрально)")

            # MACD (12, 26, 9)
            macd = ta.macd(df['close'], fast=12, slow=26, signal=9)
            macd_line = macd['MACD_12_26_9'].iloc[-1]
            signal_line = macd['MACDs_12_26_9'].iloc[-1]
            if pd.notna(macd_line) and pd.notna(signal_line):
                if macd_line > signal_line and macd_line > 0:
                    scores.append(0.5)  # Бычий кроссовер
                    reasons.append("MACD кроссовер вверх")
                elif macd_line < signal_line and macd_line < 0:
                    scores.append(-0.5)  # Медвежий кроссовер
                    reasons.append("MACD кроссовер вниз")
                else:
                    scores.append(0)
                    reasons.append("MACD нейтрально")

            # SMA/EMA (20)
            df['sma'] = ta.sma(df['close'], length=20)
            df['ema'] = ta.ema(df['close'], length=20)
            sma = df['sma'].iloc[-1]
            ema = df['ema'].iloc[-1]
            close = df['close'].iloc[-1]
            if pd.notna(sma) and pd.notna(ema):
                if close > sma and close > ema:
                    scores.append(0.3)  # Цена выше скользящих
                    reasons.append(f"Цена выше SMA={sma:.2f}, EMA={ema:.2f}")
                elif close < sma and close < ema:
                    scores.append(-0.3)  # Цена ниже скользящих
                    reasons.append(f"Цена ниже SMA={sma:.2f}, EMA={ema:.2f}")
                else:
                    scores.append(0)
                    reasons.append("Цена около SMA/EMA")

            # Итоговая оценка
            score = sum(scores) / max(len(scores), 1)
            score = max(min(score, 1.0), -1.0)  # Ограничиваем -1..1
            reason = "; ".join(reasons) if reasons else "Нет значимых сигналов"
            return score, reason
        except Exception as e:
            self.logger.warning(f"[technical] Ошибка расчёта индикаторов: {str(e)}")
            return 0, f"Ошибка расчёта: {str(e)}"
```

### Пояснения к реализации
- **Индикаторы**: RSI, MACD, SMA/EMA вычисляются через `pandas_ta` для простоты и скорости.
- **Оценка**:
  - RSI: Перекупленность (-0.5), перепроданность (+0.5).
  - MACD: Бычий кроссовер (+0.5), медвежий (-0.5).
  - SMA/EMA: Цена выше (+0.3), ниже (-0.3).
  - Итог: Среднее, нормализованное в -1..1.
- **Confidence**: Фиксированное 0.5 (для MVP, позже — на основе статистики).
- **Данные**: Котировки за последние 60 дней (достаточно для индикаторов).
- **Ошибки**: Логируются, при сбое возвращается `AnalyzerOutput(score=0)`.

## Интеграция с другими модулями
- **DatabaseManager**: Загружает котировки через `load(query, Quote)`:
  ```python
  quotes = db_manager.load(f"SELECT * FROM quotes WHERE ticker = '{ticker}'", Quote)
  ```
- **Aggregator**: Вызывает `TechnicalAnalyzer.process(input)` для получения оценок, инжектирует через DI:
  ```python
  # src/core/config.py
  def get_analyzer(analyzer_type: str, db_manager: DatabaseManager) -> AnalyzerInterface:
      analyzers = {
          'basic_news': BasicNewsAnalyzer,
          'technical': lambda: TechnicalAnalyzer(db_manager)
      }
      return analyzers[analyzer_type]()
  ```
  ```python
  # src/ai/aggregator.py
  aggregator = Aggregator(analyzers={
      'news': get_analyzer('basic_news', db_manager),
      'technical': get_analyzer('technical', db_manager)
  })
  outputs = aggregator.aggregate({
      'technical': AnalyzerInput(tickers=['SBER', 'GAZP'])
  })
  ```
- **MainWindow**: Отображает результаты в таблице Дашборда (`score` → действие, `reason` → диалог).

## Тестирование
Тесты в `tests/test_technical_analyzer.py` проверяют расчёт индикаторов и обработку ошибок.

```python
import pytest
import pandas as pd
from unittest.mock import Mock
from src.analysis.technical import TechnicalAnalyzer, AnalyzerInput, AnalyzerOutput
from src.core.exceptions import ProcessingError
from src.core.models import Quote
from datetime import date, timedelta

@pytest.fixture
def db_manager():
    db = Mock()
    db.load.return_value = [
        Quote(ticker="SBER", date=date(2025, 10, i), open=300, close=300 + i, volume=1000)
        for i in range(1, 31)
    ]
    return db

@pytest.fixture
def analyzer(db_manager):
    return TechnicalAnalyzer(db_manager)

def test_technical_analyzer_success(analyzer, db_manager):
    input_data = AnalyzerInput(tickers=['SBER'])
    output = analyzer.process(input_data)
    assert isinstance(output, Dict)
    assert 'SBER' in output
    assert isinstance(output['SBER'], AnalyzerOutput)
    assert -1 <= output['SBER'].score <= 1
    assert output['SBER'].confidence == 0.5
    assert "RSI" in output['SBER'].reason or "MACD" in output['SBER'].reason

def test_technical_analyzer_no_data(analyzer, db_manager):
    db_manager.load.return_value = []
    input_data = AnalyzerInput(tickers=['SBER'])
    output = analyzer.process(input_data)
    assert output['SBER'].score == 0
    assert output['SBER'].confidence == 0
    assert "Недостаточно данных" in output['SBER'].reason

def test_technical_analyzer_error(analyzer, db_manager):
    db_manager.load.side_effect = Exception("DB error")
    input_data = AnalyzerInput(tickers=['SBER'])
    with pytest.raises(ProcessingError):
        analyzer.process(input_data)
```

## Логирование
- Логи сохраняются в `logs/app_YYYYMMDD.log` и таблице `logs` через `DatabaseManager`.
- Категории: `technical`, `error`.
- Пример:
  ```
  2025-10-20 18:30: [technical] Анализ для тикеров: ['SBER', 'GAZP']
  2025-10-20 18:31: [error] Ошибка анализа: DB error
  ```

## Обработка ошибок
- Кастомное исключение:
  ```python
  # src/core/exceptions.py
  class ProcessingError(Exception):
      """Ошибка обработки данных в анализаторах."""
      pass
  ```
- Fallback: При ошибке возвращается `AnalyzerOutput(score=0, confidence=0)`.

## Масштабируемость
- **Новые индикаторы**: Добавить в `_calculate_indicators` (например, Bollinger Bands через `pandas_ta`).
- **ML-анализ**: Новый подкласс `MLTechnicalAnalyzer` с PyTorch, реализующий тот же `AnalyzerInterface`.
  ```python
  class MLTechnicalAnalyzer(AnalyzerInterface):
      def process(self, input_data: AnalyzerInput) -> Dict[str, AnalyzerOutput]:
          # Логика с PyTorch
          return {ticker: AnalyzerOutput(score=0.7, confidence=0.9, reason="ML prediction") for ticker in input_data.tickers}
  ```
  Смена в `config.yaml`: `technical_analyzer: ml`.
- **Async**: В будущем добавить `async def process` для асинхронных запросов к базе.
- **Микро-сервисы**: Переход на REST (FastAPI) с JSON-сериализацией `AnalyzerOutput`.

## Следующие шаги
- Реализовать `DataProvider` (Шаг 1.2) для загрузки котировок.
- Перейти к Шагу 2.2 (Риск-менеджмент: стоп-лосс).
- Проверить зависимости: `pip install pandas pandas-ta`.