# Шаг 2.2: Реализация управления рисками (RiskAnalyzer)

## Введение
Этот документ описывает реализацию модуля управления рисками (`RiskAnalyzer`) для расчёта стоп-лоссов и оценки волатильности на основе котировок акций, хранящихся в DuckDB. Модуль следует принципам модульности из `ModularityConcept.md`: чёткий контракт через `AnalyzerInterface` и pydantic модели, независимость, Dependency Injection (DI) через factory, простота для MVP с хуками для масштабирования. Для MVP используется Average True Range (ATR) для стоп-лосса и стандартное отклонение цен для волатильности. Модуль интегрируется с `DatabaseManager` для доступа к данным и с `Aggregator` для формирования рекомендаций.

**Цели шага**:
- Создать `RiskAnalyzer` для расчёта стоп-лосса и волатильности.
- Реализовать контракт через `AnalyzerInterface` с методом `process`, возвращающим `Dict[str, AnalyzerOutput]`.
- Использовать pydantic модели для входа (`AnalyzerInput`) и выхода (`AnalyzerOutput`).
- Интегрировать с `DatabaseManager` для получения котировок.
- Добавить тесты (`pytest`) с mock-данными.
- Реализовать логирование и обработку ошибок.
- Подготовить к масштабированию (например, добавление position sizing или ML).

**Место в архитектуре**:
- Модуль: `src/analysis/risk.py`.
- Зависимости: `pandas`, `pandas_ta`, `pydantic`, `src/core/models.py`, `src/core/interfaces.py`, `src/core/logging.py`, `src/core/exceptions.py`, `src/data/database_manager.py`.
- Интеграция: `RiskAnalyzer` инжектируется в `Aggregator` через `config.yaml`.

## Требования
- **Источник данных**: Котировки из таблицы `quotes` в DuckDB (через `DatabaseManager`).
- **Метрики риска**:
  - **Стоп-лосс**: Рассчитывается как текущая цена минус 2×ATR (14-дневный).
  - **Волатильность**: Стандартное отклонение цен закрытия за 20 дней.
- **Контракт**:
  - Вход: `AnalyzerInput` (список тикеров, опциональный диапазон дат).
  - Выход: `Dict[str, AnalyzerOutput]` (оценка риска, уверенность, обоснование).
- **Оффлайн-режим**: Данные из DuckDB, fallback при отсутствии данных — `AnalyzerOutput(score=0, confidence=0)`.
- **Ошибки**: Кастомное исключение (`ProcessingError`), логи в `logs/app_YYYYMMDD.log`.
- **Тесты**: Unit-тесты с mock-данными (coverage >80%).
- **Масштаб**: Хук для position sizing, VaR или ML-анализа.

## Контракт модуля
Модуль реализует `AnalyzerInterface`, определённый в `src/core/interfaces.py`. Контракт совпадает с используемым в `Step1.4-NewsParser.md` и `Step2.1-TechnicalAnalysis.md`, но адаптирован для управления рисками.

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
    score: float  # Оценка риска (-1..1, где -1 — высокий риск)
    confidence: float  # Уверенность (0..1)
    reason: str  # Обоснование (например, "Стоп-лосс: 280.0, Волатильность: 5%")

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
- Выход: `Dict[str, AnalyzerOutput]` с оценкой риска, уверенностью и обоснованием.
- Исключения: `ProcessingError` для ошибок расчёта.
- Backward-compatibility: Новые поля в `AnalyzerOutput` — optional.

## Реализация RiskAnalyzer
Модуль `RiskAnalyzer` реализует `AnalyzerInterface`, загружает котировки через `DatabaseManager` и вычисляет стоп-лосс (ATR) и волатильность (стандартное отклонение). Для MVP оценка (`score`) основана на волатильности и расстоянии до стоп-лосса:
- Высокая волатильность (>5%) или близкий стоп-лосс (<2% от цены): `score` = -0.5 (высокий риск).
- Низкая волатильность (<2%) и далёкий стоп-лосс (>5%): `score` = 0.5 (низкий риск).
- Итоговый `score`: Среднее, нормализованное в -1..1.
- `confidence`: Фиксированное 0.5 (для MVP).

### Код
```python
# src/analysis/risk.py
"""Модуль для управления рисками (стоп-лосс, волатильность)."""

import pandas as pd
import pandas_ta as ta
from typing import Dict, List
from src.core.interfaces import AnalyzerInterface, AnalyzerInput, AnalyzerOutput
from src.core.exceptions import ProcessingError
from src.core.logging import setup_logging
from src.data.database_manager import DatabaseManager
from src.core.models import Quote
from datetime import date, timedelta

class RiskAnalyzer(AnalyzerInterface):
    def __init__(self, db_manager: DatabaseManager):
        """Инициализация анализатора рисков.

        Args:
            db_manager: Модуль для доступа к котировкам.
        """
        self.db_manager = db_manager
        self.logger = setup_logging()

    def process(self, input_data: AnalyzerInput) -> Dict[str, AnalyzerOutput]:
        """Вычисляет риски и возвращает оценки для тикеров.

        Args:
            input_data: Входные данные (tickers, date_range).

        Returns:
            Dict[ticker, AnalyzerOutput]: Оценки рисков.

        Raises:
            ProcessingError: Если ошибка расчёта.
        """
        try:
            self.logger.info(f"[risk] Анализ рисков для тикеров: {input_data.tickers}")
            results = {}
            # Устанавливаем диапазон дат: последние 30 дней для ATR и волатильности
            end_date = date.today()
            start_date = input_data.date_range[0] if input_data.date_range else end_date - timedelta(days=30)
            for ticker in input_data.tickers:
                quotes = self.db_manager.load(
                    f"SELECT * FROM quotes WHERE ticker = '{ticker}' AND date >= '{start_date}' AND date <= '{end_date}' ORDER BY date",
                    Quote
                )
                if len(quotes) < 14:  # Минимально для ATR
                    results[ticker] = AnalyzerOutput(score=0, confidence=0, reason="Недостаточно данных")
                    continue
                df = pd.DataFrame([q.dict() for q in quotes])
                score, reason = self._calculate_risk(df)
                results[ticker] = AnalyzerOutput(
                    score=score,
                    confidence=0.5,  # Фиксированная уверенность для MVP
                    reason=reason
                )
            return results
        except Exception as e:
            self.logger.error(f"[risk] Ошибка анализа: {str(e)}")
            raise ProcessingError(f"Ошибка обработки рисков: {str(e)}")

    def _calculate_risk(self, df: pd.DataFrame) -> tuple[float, str]:
        """Вычисляет стоп-лосс и волатильность, возвращает оценку риска.

        Args:
            df: DataFrame с котировками (ticker, date, open, close, volume).

        Returns:
            tuple[float, str]: Оценка риска (-1..1) и обоснование.
        """
        try:
            scores = []
            reasons = []

            # Текущая цена
            current_price = df['close'].iloc[-1]

            # ATR (14) для стоп-лосса
            df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=14)
            atr = df['atr'].iloc[-1]
            if pd.notna(atr):
                stop_loss = current_price - 2 * atr
                stop_loss_pct = (current_price - stop_loss) / current_price * 100
                if stop_loss_pct < 2:  # Близкий стоп-лосс
                    scores.append(-0.5)
                    reasons.append(f"Стоп-лосс: {stop_loss:.2f} ({stop_loss_pct:.1f}% от цены)")
                else:
                    scores.append(0.5)
                    reasons.append(f"Стоп-лосс: {stop_loss:.2f} ({stop_loss_pct:.1f}% от цены)")
            else:
                scores.append(0)
                reasons.append("ATR недоступен")

            # Волатильность (стандартное отклонение цен закрытия, 20 дней)
            volatility = df['close'].tail(20).std() / df['close'].tail(20).mean() * 100
            if pd.notna(volatility):
                if volatility > 5:  # Высокая волатильность
                    scores.append(-0.5)
                    reasons.append(f"Волатильность: {volatility:.1f}% (высокая)")
                elif volatility < 2:  # Низкая волатильность
                    scores.append(0.5)
                    reasons.append(f"Волатильность: {volatility:.1f}% (низкая)")
                else:
                    scores.append(0)
                    reasons.append(f"Волатильность: {volatility:.1f}% (средняя)")
            else:
                scores.append(0)
                reasons.append("Волатильность недоступна")

            # Итоговая оценка
            score = sum(scores) / max(len(scores), 1)
            score = max(min(score, 1.0), -1.0)  # Ограничиваем -1..1
            reason = "; ".join(reasons) if reasons else "Нет значимых сигналов"
            return score, reason
        except Exception as e:
            self.logger.warning(f"[risk] Ошибка расчёта рисков: {str(e)}")
            return 0, f"Ошибка расчёта: {str(e)}"
```

### Пояснения к реализации
- **Метрики риска**:
  - **Стоп-лосс**: Рассчитывается как `цена - 2×ATR(14)`. Близкий стоп-лосс (<2%) увеличивает риск (`score=-0.5`).
  - **Волатильность**: Стандартное отклонение цен закрытия (20 дней), нормализованное к средней цене. Высокая волатильность (>5%) увеличивает риск.
- **Оценка**:
  - Высокий риск (близкий стоп-лосс или высокая волатильность): `score=-0.5`.
  - Низкий риск (далёкий стоп-лосс, низкая волатильность): `score=0.5`.
  - Итог: Среднее, нормализованное в -1..1.
- **Confidence**: Фиксированное 0.5 (для MVP, позже — на основе статистики).
- **Данные**: Котировки за последние 30 дней (достаточно для ATR и волатильности).
- **Ошибки**: Логируются, при сбое возвращается `AnalyzerOutput(score=0)`.

## Интеграция с другими модулями
- **DatabaseManager**: Загружает котировки через `load(query, Quote)`:
  ```python
  quotes = db_manager.load(f"SELECT * FROM quotes WHERE ticker = '{ticker}'", Quote)
  ```
- **Aggregator**: Вызывает `RiskAnalyzer.process(input)` для получения оценок, инжектирует через DI:
  ```python
  # src/core/config.py
  def get_analyzer(analyzer_type: str, db_manager: DatabaseManager) -> AnalyzerInterface:
      analyzers = {
          'basic_news': BasicNewsAnalyzer,
          'technical': lambda: TechnicalAnalyzer(db_manager),
          'risk': lambda: RiskAnalyzer(db_manager)
      }
      return analyzers[analyzer_type]()
  ```
  ```python
  # src/ai/aggregator.py
  aggregator = Aggregator(analyzers={
      'news': get_analyzer('basic_news', db_manager),
      'technical': get_analyzer('technical', db_manager),
      'risk': get_analyzer('risk', db_manager)
  })
  outputs = aggregator.aggregate({
      'risk': AnalyzerInput(tickers=['SBER', 'GAZP'])
  })
  ```
- **MainWindow**: Отображает результаты в таблице Дашборда (`score` влияет на действие, `reason` — в диалоге).

## Тестирование
Тесты в `tests/test_risk_analyzer.py` проверяют расчёт стоп-лосса, волатильности и обработку ошибок.

```python
import pytest
import pandas as pd
from unittest.mock import Mock
from src.analysis.risk import RiskAnalyzer, AnalyzerInput, AnalyzerOutput
from src.core.exceptions import ProcessingError
from src.core.models import Quote
from datetime import date, timedelta

@pytest.fixture
def db_manager():
    db = Mock()
    # Mock котировок: линейный рост для стабильного ATR
    quotes = [
        Quote(ticker="SBER", date=date(2025, 10, i), open=300, close=300 + i, volume=1000, high=305 + i, low=295 + i)
        for i in range(1, 31)
    ]
    db.load.return_value = quotes
    return db

@pytest.fixture
def analyzer(db_manager):
    return RiskAnalyzer(db_manager)

def test_risk_analyzer_success(analyzer, db_manager):
    input_data = AnalyzerInput(tickers=['SBER'])
    output = analyzer.process(input_data)
    assert isinstance(output, Dict)
    assert 'SBER' in output
    assert isinstance(output['SBER'], AnalyzerOutput)
    assert -1 <= output['SBER'].score <= 1
    assert output['SBER'].confidence == 0.5
    assert "Стоп-лосс" in output['SBER'].reason or "Волатильность" in output['SBER'].reason

def test_risk_analyzer_no_data(analyzer, db_manager):
    db_manager.load.return_value = []
    input_data = AnalyzerInput(tickers=['SBER'])
    output = analyzer.process(input_data)
    assert output['SBER'].score == 0
    assert output['SBER'].confidence == 0
    assert "Недостаточно данных" in output['SBER'].reason

def test_risk_analyzer_error(analyzer, db_manager):
    db_manager.load.side_effect = Exception("DB error")
    input_data = AnalyzerInput(tickers=['SBER'])
    with pytest.raises(ProcessingError):
        analyzer.process(input_data)
```

## Логирование
- Логи сохраняются в `logs/app_YYYYMMDD.log` и таблице `logs` через `DatabaseManager`.
- Категории: `risk`, `error`.
- Пример:
  ```
  2025-10-20 18:30: [risk] Анализ рисков для тикеров: ['SBER', 'GAZP']
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
- **Новые метрики**: Добавить в `_calculate_risk` (например, VaR или position sizing).
- **ML-анализ**: Новый подкласс `MLRiskAnalyzer` с PyTorch, реализующий тот же `AnalyzerInterface`.
  ```python
  class MLRiskAnalyzer(AnalyzerInterface):
      def process(self, input_data: AnalyzerInput) -> Dict[str, AnalyzerOutput]:
          # Логика с ML
          return {ticker: AnalyzerOutput(score=-0.3, confidence=0.9, reason="ML risk prediction") for ticker in input_data.tickers}
  ```
  Смена в `config.yaml`: `risk_analyzer: ml`.
- **Async**: В будущем добавить `async def process` для асинхронных запросов к базе.
- **Микро-сервисы**: Переход на REST (FastAPI) с JSON-сериализацией `AnalyzerOutput`.

## Следующие шаги
- Реализовать `DataProvider` (Шаг 1.2) для загрузки котировок.
- Перейти к Шагу 2.3 (Рекомендации: RandomForest).
- Проверить зависимости: `pip install pandas pandas-ta`.