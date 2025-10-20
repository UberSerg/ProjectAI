# Шаг 3.1: Backtesting

## Введение
Этот документ описывает реализацию модуля бэктестинга (`Backtester`) для оценки стратегий, основанных на рекомендациях `Recommender`, на исторических данных котировок, хранящихся в DuckDB. Модуль следует принципам модульности из `ModularityConcept.md`: чёткий контракт через `BacktesterInterface`, pydantic модели, Dependency Injection (DI) через factory, простота для MVP с хуками для масштабирования. Бэктестер вычисляет метрики Win Rate, Sharpe Ratio и Max Drawdown, используя рекомендации (`buy/sell/hold`) и котировки. Результаты интегрируются с `MainWindow` для отображения на вкладке "Обучение".

**Цели шага**:
- Реализовать `Backtester` с методом `run_backtest` для симуляции стратегий.
- Вычислять метрики: Win Rate, Sharpe Ratio, Max Drawdown.
- Использовать pydantic модели для входа (`BacktestInput`) и выхода (`BacktestResult`).
- Интегрировать с `Aggregator` для получения рекомендаций и `DatabaseManager` для котировок.
- Добавить тесты (`pytest`) с mock-данными.
- Реализовать логирование и обработку ошибок.
- Подготовить к масштабированию (например, поддержка MLflow или портфельных стратегий).

**Место в архитектуре**:
- Модуль: `src/backtesting/backtester.py`.
- Зависимости: `pandas`, `numpy`, `pydantic`, `src/core/models.py`, `src/core/interfaces.py`, `src/core/logging.py`, `src/core/exceptions.py`, `src/ai/aggregator.py`, `src/data/database_manager.py`.
- Интеграция: `Backtester` инжектируется в `MainWindow` через DI.

## Требования
- **Источник данных**: Котировки из таблицы `quotes` в DuckDB (через `DatabaseManager`) и рекомендации от `Aggregator`.
- **Метрики**:
  - **Win Rate**: Доля прибыльных сделок (доходность >0).
  - **Sharpe Ratio**: (Средняя доходность - безрисковая ставка) / стандартное отклонение доходности.
  - **Max Drawdown**: Максимальная просадка капитала.
- **Контракт**:
  - Вход: `BacktestInput` (тикеры, диапазон дат, начальный капитал).
  - Выход: `BacktestResult` (метрики, список сделок).
- **Оффлайн-режим**: Данные из DuckDB, fallback при отсутствии данных — пустой результат.
- **Ошибки**: Кастомное исключение (`BacktestError`), логи в `logs/app_YYYYMMDD.log`.
- **Тесты**: Unit-тесты с mock-данными (coverage >80%).
- **Масштаб**: Хук для MLflow, портфельных стратегий или REST.

## Контракт модуля
Модуль реализует `BacktesterInterface`, определяющий метод `run_backtest` для выполнения бэктестинга. Используются pydantic модели для входа и выхода.

### Абстрактный класс
```python
from abc import ABC, abstractmethod
from typing import Dict, List
from pydantic import BaseModel
from datetime import date

class BacktestInput(BaseModel):
    """Входные данные для бэктестинга."""
    tickers: List[str]  # Список тикеров
    date_range: tuple[date, date]  # Диапазон дат
    initial_capital: float  # Начальный капитал
    position_size: float = 0.1  # Доля капитала на сделку (10% для MVP)

class Trade(BaseModel):
    """Информация о сделке."""
    ticker: str
    entry_date: date
    exit_date: date
    entry_price: float
    exit_price: float
    quantity: int
    profit: float
    stop_loss: float | None

class BacktestResult(BaseModel):
    """Результаты бэктестинга."""
    win_rate: float  # Доля прибыльных сделок
    sharpe_ratio: float  # Коэффициент Шарпа
    max_drawdown: float  # Максимальная просадка
    trades: List[Trade]  # Список сделок

class BacktesterInterface(ABC):
    @abstractmethod
    def run_backtest(self, input_data: BacktestInput) -> BacktestResult:
        """Выполняет бэктестинг стратегии.

        Args:
            input_data: Входные данные (тикеры, диапазон дат, капитал).

        Returns:
            BacktestResult: Результаты с метриками и сделками.

        Raises:
            BacktestError: Если ошибка бэктестинга.
        """
        pass
```

**Правила для контракта**:
- Метод: Только `run_backtest` (sync, без async для MVP).
- Вход: `BacktestInput` с тикерами, диапазоном дат, начальным капиталом.
- Выход: `BacktestResult` с метриками (Win Rate, Sharpe Ratio, Max Drawdown) и списком сделок.
- Исключения: `BacktestError` для ошибок обработки.
- Backward-compatibility: Новые поля в `BacktestResult` — optional.

## Реализация Backtester
Модуль `Backtester` реализует `BacktesterInterface`, выполняет бэктестинг стратегии, используя рекомендации от `Aggregator`. Для MVP:
- **Стратегия**: Следуем сигналам `Recommender` (buy/sell/hold).
- **Сделки**: Покупка на `buy` (10% капитала), продажа на `sell` или по стоп-лоссу (из `Recommendation`), держим до конца горизонта (4 недели) или сигнала `sell`.
- **Метрики**:
  - Win Rate: Доля сделок с `profit > 0`.
  - Sharpe Ratio: Средняя доходность (безрисковая ставка = 0 для MVP) / стандартное отклонение.
  - Max Drawdown: Максимальная просадка капитала (в процентах).
- **Данные**: Котировки из DuckDB, рекомендации генерируются для каждого дня в диапазоне дат.

### Код
```python
# src/backtesting/backtester.py
"""Модуль для бэктестинга стратегий."""

import pandas as pd
import numpy as np
from typing import List
from src.core.interfaces import BacktesterInterface, BacktestInput, BacktestResult, Trade
from src.core.models import Recommendation, AnalyzerInput
from src.core.exceptions import BacktestError
from src.core.logging import setup_logging
from src.data.database_manager import DatabaseManager
from src.ai.aggregator import Aggregator
from datetime import date, timedelta

class Backtester(BacktesterInterface):
    def __init__(self, aggregator: Aggregator, db_manager: DatabaseManager):
        """Инициализация бэктестера.

        Args:
            aggregator: Модуль для получения рекомендаций.
            db_manager: Модуль для доступа к котировкам.
        """
        self.aggregator = aggregator
        self.db_manager = db_manager
        self.logger = setup_logging()

    def run_backtest(self, input_data: BacktestInput) -> BacktestResult:
        """Выполняет бэктестинг стратегии.

        Args:
            input_data: Входные данные (тикеры, диапазон дат, капитал).

        Returns:
            BacktestResult: Результаты с метриками и сделками.

        Raises:
            BacktestError: Если ошибка бэктестинга.
        """
        try:
            self.logger.info(f"[backtest] Запуск бэктестинга для {input_data.tickers}, диапазон {input_data.date_range}")
            trades = []
            capital = input_data.initial_capital
            equity = [capital]
            position = {}  # ticker: {quantity, entry_price, entry_date, stop_loss}

            # Итерация по дням
            current_date = input_data.date_range[0]
            while current_date <= input_data.date_range[1]:
                # Получаем рекомендации
                recommendations = self.aggregator.aggregate({
                    'news': AnalyzerInput(urls=['https://ria.ru/rss'], tickers=input_data.tickers),
                    'technical': AnalyzerInput(tickers=input_data.tickers),
                    'risk': AnalyzerInput(tickers=input_data.tickers)
                })
                # Загружаем котировки за день
                quotes = self.db_manager.load(
                    f"SELECT * FROM quotes WHERE date = '{current_date}' AND ticker IN ({','.join(f"'{t}'" for t in input_data.tickers)})",
                    Quote
                )
                quote_dict = {q.ticker: q.close for q in quotes}

                # Обработка позиций
                for ticker in input_data.tickers:
                    rec = recommendations.get(ticker, Recommendation(signal="hold", target_price=None, stop_loss=None, horizon="4 недели", confidence=0, reason="Нет данных"))
                    current_price = quote_dict.get(ticker)
                    if not current_price:
                        continue

                    # Открытие позиции
                    if rec.signal == "buy" and ticker not in position:
                        quantity = int((capital * input_data.position_size) / current_price)
                        if quantity > 0:
                            position[ticker] = {
                                'quantity': quantity,
                                'entry_price': current_price,
                                'entry_date': current_date,
                                'stop_loss': rec.stop_loss
                            }
                            capital -= quantity * current_price
                            self.logger.info(f"[backtest] Покупка {ticker}: {quantity} по {current_price}")

                    # Закрытие позиции
                    if ticker in position:
                        pos = position[ticker]
                        should_close = rec.signal == "sell" or (
                            pos['stop_loss'] and current_price <= pos['stop_loss']
                        ) or (current_date - pos['entry_date']).days >= 28  # 4 недели
                        if should_close:
                            profit = pos['quantity'] * (current_price - pos['entry_price'])
                            capital += pos['quantity'] * current_price
                            trades.append(Trade(
                                ticker=ticker,
                                entry_date=pos['entry_date'],
                                exit_date=current_date,
                                entry_price=pos['entry_price'],
                                exit_price=current_price,
                                quantity=pos['quantity'],
                                profit=profit,
                                stop_loss=pos['stop_loss']
                            ))
                            self.logger.info(f"[backtest] Продажа {ticker}: прибыль {profit}")
                            del position[ticker]
                
                equity.append(capital + sum(pos['quantity'] * quote_dict.get(ticker, pos['entry_price']) for ticker, pos in position.items()))
                current_date += timedelta(days=1)

            # Вычисление метрик
            returns = pd.Series(equity).pct_change().dropna()
            win_rate = len([t for t in trades if t.profit > 0]) / len(trades) if trades else 0
            sharpe_ratio = returns.mean() / returns.std() * np.sqrt(252) if returns.std() != 0 else 0
            equity_series = pd.Series(equity)
            max_drawdown = ((equity_series.cummax() - equity_series) / equity_series.cummax()).max() * 100

            result = BacktestResult(
                win_rate=win_rate,
                sharpe_ratio=sharpe_ratio,
                max_drawdown=max_drawdown,
                trades=trades
            )
            self.logger.info(f"[backtest] Результат: Win Rate={win_rate:.2f}, Sharpe={sharpe_ratio:.2f}, Max Drawdown={max_drawdown:.2f}%")
            return result
        except Exception as e:
            self.logger.error(f"[backtest] Ошибка бэктестинга: {str(e)}")
            raise BacktestError(f"Ошибка бэктестинга: {str(e)}")
```

### Пояснения к реализации
- **Стратегия**:
  - Открытие: Покупка на сигнал `buy` (10% капитала).
  - Закрытие: Продажа на сигнал `sell`, по стоп-лоссу или через 4 недели.
  - Позиция: Одна на тикер, фиксированный размер (10%).
- **Метрики**:
  - **Win Rate**: Доля сделок с прибылью >0.
  - **Sharpe Ratio**: Средняя дневная доходность / стандартное отклонение, масштабированная на √252 (год).
  - **Max Drawdown**: Максимальная просадка капитала в процентах.
- **Данные**: Котировки из `quotes` за указанный диапазон, рекомендации от `Aggregator` для каждого дня.
- **Ошибки**: Логируются, при сбое возвращается `BacktestResult` с нулевыми метриками.
- **Оффлайн-режим**: Используются локальные данные из DuckDB.

## Интеграция с другими модулями
- **Aggregator**: Генерирует рекомендации через `aggregate`:
  ```python
  recommendations = aggregator.aggregate({
      'news': AnalyzerInput(urls=['https://ria.ru/rss'], tickers=input_data.tickers),
      'technical': AnalyzerInput(tickers=input_data.tickers),
      'risk': AnalyzerInput(tickers=input_data.tickers)
  })
  ```
- **DatabaseManager**: Загружает котировки через `load`:
  ```python
  quotes = db_manager.load(f"SELECT * FROM quotes WHERE date = '{current_date}'", Quote)
  ```
- **MainWindow**: Отображает результаты (`win_rate`, `sharpe_ratio`, `max_drawdown`) на вкладке "Обучение".
- **DI**: `Backtester` инжектируется в `MainWindow`:
  ```python
  # src/core/config.py
  def get_backtester(db_manager: DatabaseManager) -> BacktesterInterface:
      aggregator = Aggregator(analyzers={
          'news': get_analyzer('basic_news', db_manager),
          'technical': get_analyzer('technical', db_manager),
          'risk': get_analyzer('risk', db_manager)
      }, recommender=get_recommender())
      return Backtester(aggregator=aggregator, db_manager=db_manager)
  ```

## Тестирование
Тесты в `tests/test_backtester.py` проверяют бэктестинг и метрики.

```python
import pytest
from unittest.mock import Mock
from src.backtesting.backtester import Backtester, BacktestInput, BacktestResult
from src.core.exceptions import BacktestError
from src.core.models import Quote, Recommendation
from datetime import date, timedelta

@pytest.fixture
def db_manager():
    db = Mock()
    db.load.return_value = [
        Quote(ticker="SBER", date=date(2025, 1, i), close=300 + i, open=300, volume=1000, high=305, low=295)
        for i in range(1, 31)
    ]
    return db

@pytest.fixture
def aggregator():
    agg = Mock()
    agg.aggregate.return_value = {
        'SBER': Recommendation(signal="buy", target_price=None, stop_loss=280.0, horizon="4 недели", confidence=0.7, reason="Test")
    }
    return agg

@pytest.fixture
def backtester(db_manager, aggregator):
    return Backtester(aggregator=aggregator, db_manager=db_manager)

def test_backtest_success(backtester, db_manager, aggregator):
    input_data = BacktestInput(
        tickers=['SBER'],
        date_range=(date(2025, 1, 1), date(2025, 1, 30)),
        initial_capital=10000
    )
    result = backtester.run_backtest(input_data)
    assert isinstance(result, BacktestResult)
    assert 0 <= result.win_rate <= 1
    assert isinstance(result.sharpe_ratio, float)
    assert 0 <= result.max_drawdown <= 100
    assert len(result.trades) > 0
    assert result.trades[0].ticker == "SBER"

def test_backtest_no_data(backtester, db_manager):
    db_manager.load.return_value = []
    input_data = BacktestInput(
        tickers=['SBER'],
        date_range=(date(2025, 1, 1), date(2025, 1, 30)),
        initial_capital=10000
    )
    result = backtester.run_backtest(input_data)
    assert result.win_rate == 0
    assert result.trades == []

def test_backtest_error(backtester, db_manager):
    db_manager.load.side_effect = Exception("DB error")
    input_data = BacktestInput(
        tickers=['SBER'],
        date_range=(date(2025, 1, 1), date(2025, 1, 30)),
        initial_capital=10000
    )
    with pytest.raises(BacktestError):
        backtester.run_backtest(input_data)
```

## Логирование
- Логи сохраняются в `logs/app_YYYYMMDD.log` и таблице `logs` через `DatabaseManager`.
- Категории: `backtest`, `error`.
- Пример:
  ```
  2025-10-20 18:30: [backtest] Запуск бэктестинга для ['SBER'], диапазон (2025-01-01, 2025-01-30)
  2025-10-20 18:31: [backtest] Покупка SBER: 33 по 301.0
  2025-10-20 18:32: [error] Ошибка бэктестинга: DB error
  ```

## Обработка ошибок
- Кастомное исключение:
  ```python
  # src/core/exceptions.py
  class BacktestError(Exception):
      """Ошибка бэктестинга."""
      pass
  ```
- Fallback: При ошибке возвращается `BacktestResult` с нулевыми метриками.

## Масштабируемость
- **Новые стратегии**: Добавить подкласс `PortfolioBacktester` для портфельных стратегий.
- **MLflow**: Трекинг метрик в Фазе 3.2.
- **Async**: В будущем добавить `async def run_backtest` для асинхронных вызовов.
- **REST**: Поддержка FastAPI для сериализации `BacktestResult`.

## Следующие шаги
- Интегрировать результаты в `MainWindow` (вкладка "Обучение") в Шаге 3.4.
- Перейти к Шагу 3.2 (`PaperTrading`).
- Проверить зависимости: `pip install pandas numpy`.