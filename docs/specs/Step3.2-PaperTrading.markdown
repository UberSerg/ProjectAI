# Шаг 3.2: Paper Trading

## Введение
Этот документ описывает реализацию модуля симуляции торговли в реальном времени (`PaperPortfolio`) для тестирования рекомендаций `Recommender` на текущих котировках. Модуль следует принципам модульности из `ModularityConcept.md`: чёткий контракт через `PaperTradingInterface`, pydantic модели, Dependency Injection (DI) через factory, простота для MVP с хуками для масштабирования. `PaperPortfolio` симулирует сделки (buy/sell/hold) на основе рекомендаций от `Aggregator`, используя котировки из `DataProvider` (или заглушки для MVP). Результаты сохраняются в таблицу `paper_trades` в DuckDB и отображаются в UI (`MainWindow`) на вкладке "Портфель" или новой вкладке "Paper Trading".

**Цели шага**:
- Реализовать `PaperPortfolio` с методами для симуляции торговли (`start_trading`, `stop_trading`, `get_status`).
- Использовать pydantic модели для входа (`PaperTradingInput`) и выхода (`PaperTradingResult`).
- Интегрировать с `Aggregator` для рекомендаций и `DataProvider` (или заглушка) для котировок.
- Сохранять сделки в таблицу `paper_trades` через `DatabaseManager`.
- Добавить тесты (`pytest`) с mock-данными.
- Реализовать логирование и обработку ошибок.
- Подготовить к масштабированию (например, интеграция с реальным API или MLflow).

**Место в архитектуре**:
- Модуль: `src/paper_trading/paper_portfolio.py`.
- Зависимости: `pandas`, `pydantic`, `src/core/models.py`, `src/core/interfaces.py`, `src/core/logging.py`, `src/core/exceptions.py`, `src/ai/aggregator.py`, `src/data/database_manager.py`, `src/data/data_provider.py` (заглушка для MVP).
- Интеграция: `PaperPortfolio` инжектируется в `MainWindow` через DI.

## Требования
- **Источник данных**: Котировки из `DataProvider` (или заглушка с `DatabaseManager`) и рекомендации от `Aggregator`.
- **Симуляция**:
  - Открытие позиций на сигнал `buy` (10% капитала).
  - Закрытие на сигнал `sell`, по стоп-лоссу или через горизонт (4 недели).
  - Учёт комиссий (0% для MVP).
- **Хранение**: Сделки сохраняются в таблицу `paper_trades` (аналогична `Trade` из Шага 3.1).
- **Контракт**:
  - Вход: `PaperTradingInput` (тикеры, начальный капитал).
  - Выход: `PaperTradingResult` (текущий капитал, позиции, сделки).
- **Оффлайн-режим**: Заглушка котировок из DuckDB, fallback при отсутствии данных.
- **Ошибки**: Кастомное исключение (`PaperTradingError`), логи в `logs/app_YYYYMMDD.log`.
- **Тесты**: Unit-тесты с mock-данными (coverage >80%).
- **Масштаб**: Хук для реального API (MOEX/yfinance), MLflow, REST.

## Контракт модуля
Модуль реализует `PaperTradingInterface`, определяющий методы `start_trading`, `stop_trading` и `get_status`. Используются pydantic модели для входа и выхода.

### Абстрактный класс
```python
from abc import ABC, abstractmethod
from typing import Dict, List
from pydantic import BaseModel
from datetime import date

class PaperTradingInput(BaseModel):
    """Входные данные для paper trading."""
    tickers: List[str]  # Список тикеров
    initial_capital: float  # Начальный капитал
    position_size: float = 0.1  # Доля капитала на сделку (10% для MVP)

class PaperTrade(BaseModel):
    """Информация о сделке в paper trading."""
    ticker: str
    entry_date: date
    exit_date: date | None
    entry_price: float
    exit_price: float | None
    quantity: int
    profit: float | None
    stop_loss: float | None

class PaperTradingResult(BaseModel):
    """Результаты paper trading."""
    current_capital: float  # Текущий капитал
    positions: Dict[str, PaperTrade]  # Открытые позиции
    closed_trades: List[PaperTrade]  # Закрытые сделки

class PaperTradingInterface(ABC):
    @abstractmethod
    def start_trading(self, input_data: PaperTradingInput) -> None:
        """Запускает симуляцию торговли.

        Args:
            input_data: Входные данные (тикеры, капитал).

        Raises:
            PaperTradingError: Если ошибка запуска.
        """
        pass

    @abstractmethod
    def stop_trading(self) -> PaperTradingResult:
        """Останавливает симуляцию и возвращает результаты.

        Returns:
            PaperTradingResult: Текущий капитал, позиции, сделки.

        Raises:
            PaperTradingError: Если ошибка остановки.
        """
        pass

    @abstractmethod
    def get_status(self) -> PaperTradingResult:
        """Возвращает текущий статус симуляции.

        Returns:
            PaperTradingResult: Текущий капитал, позиции, сделки.

        Raises:
            PaperTradingError: Если ошибка получения статуса.
        """
        pass
```

**Правила для контракта**:
- Методы: `start_trading`, `stop_trading`, `get_status` (sync для MVP).
- Вход: `PaperTradingInput` с тикерами и начальным капиталом.
- Выход: `PaperTradingResult` с текущим капиталом, позициями и сделками.
- Исключения: `PaperTradingError` для ошибок обработки.
- Backward-compatibility: Новые поля в `PaperTradingResult` — optional.

## Реализация PaperPortfolio
Модуль `PaperPortfolio` реализует `PaperTradingInterface`, симулируя торговлю в реальном времени. Для MVP:
- **Котировки**: Заглушка из DuckDB (последняя доступная цена), в будущем — `DataProvider` (yfinance/MOEX).
- **Стратегия**: Покупка на `buy` (10% капитала), продажа на `sell`, по стоп-лоссу или через 4 недели.
- **Сохранение**: Сделки сохраняются в `paper_trades` (аналог `trades` из Шага 3.1).
- **Симуляция**: Периодический опрос рекомендаций и котировок (каждый день для MVP).

### Код
```python
# src/paper_trading/paper_portfolio.py
"""Модуль для симуляции paper trading."""

import pandas as pd
from typing import Dict, List
from src.core.interfaces import PaperTradingInterface, PaperTradingInput, PaperTradingResult, PaperTrade
from src.core.models import Recommendation, AnalyzerInput, Quote
from src.core.exceptions import PaperTradingError
from src.core.logging import setup_logging
from src.data.database_manager import DatabaseManager
from src.ai.aggregator import Aggregator
from datetime import date, timedelta, datetime

class PaperPortfolio(PaperTradingInterface):
    def __init__(self, aggregator: Aggregator, db_manager: DatabaseManager):
        """Инициализация paper trading.

        Args:
            aggregator: Модуль для получения рекомендаций.
            db_manager: Модуль для доступа к котировкам и сохранения сделок.
        """
        self.aggregator = aggregator
        self.db_manager = db_manager
        self.logger = setup_logging()
        self.capital = 0.0
        self.positions = {}  # ticker: PaperTrade
        self.closed_trades = []
        self.is_running = False
        self.tickers = []
        self.position_size = 0.1

    def start_trading(self, input_data: PaperTradingInput) -> None:
        """Запускает симуляцию торговли.

        Args:
            input_data: Входные данные (тикеры, капитал).

        Raises:
            PaperTradingError: Если ошибка запуска.
        """
        try:
            self.logger.info(f"[paper_trading] Запуск симуляции для {input_data.tickers}")
            self.capital = input_data.initial_capital
            self.tickers = input_data.tickers
            self.position_size = input_data.position_size
            self.positions = {}
            self.closed_trades = []
            self.is_running = True
            self._update_trades()  # Первичное обновление
            self.logger.info("[paper_trading] Симуляция начата")
        except Exception as e:
            self.logger.error(f"[paper_trading] Ошибка запуска: {str(e)}")
            raise PaperTradingError(f"Ошибка запуска симуляции: {str(e)}")

    def stop_trading(self) -> PaperTradingResult:
        """Останавливает симуляцию и возвращает результаты.

        Returns:
            PaperTradingResult: Текущий капитал, позиции, сделки.

        Raises:
            PaperTradingError: Если ошибка остановки.
        """
        try:
            if not self.is_running:
                raise PaperTradingError("Симуляция не запущена")
            self._update_trades()  # Финальное обновление
            self.is_running = False
            result = self.get_status()
            self.db_manager.save(self.closed_trades, "paper_trades")
            self.logger.info(f"[paper_trading] Симуляция остановлена, сохранено {len(self.closed_trades)} сделок")
            return result
        except Exception as e:
            self.logger.error(f"[paper_trading] Ошибка остановки: {str(e)}")
            raise PaperTradingError(f"Ошибка остановки симуляции: {str(e)}")

    def get_status(self) -> PaperTradingResult:
        """Возвращает текущий статус симуляции.

        Returns:
            PaperTradingResult: Текущий капитал, позиции, сделки.

        Raises:
            PaperTradingError: Если ошибка получения статуса.
        """
        try:
            return PaperTradingResult(
                current_capital=self.capital,
                positions=self.positions,
                closed_trades=self.closed_trades
            )
        except Exception as e:
            self.logger.error(f"[paper_trading] Ошибка получения статуса: {str(e)}")
            raise PaperTradingError(f"Ошибка получения статуса: {str(e)}")

    def _update_trades(self):
        """Обновляет позиции и сделки на основе текущих котировок и рекомендаций."""
        try:
            if not self.is_running:
                return
            current_date = date.today()
            # Получаем рекомендации
            recommendations = self.aggregator.aggregate({
                'news': AnalyzerInput(urls=['https://ria.ru/rss'], tickers=self.tickers),
                'technical': AnalyzerInput(tickers=self.tickers),
                'risk': AnalyzerInput(tickers=self.tickers)
            })
            # Загружаем текущие котировки (заглушка: последняя дата в DuckDB)
            quotes = self.db_manager.load(
                f"SELECT ticker, close FROM quotes WHERE date = (SELECT MAX(date) FROM quotes) AND ticker IN ({','.join(f"'{t}'" for t in self.tickers)})",
                Quote
            )
            quote_dict = {q.ticker: q.close for q in quotes}

            # Обработка позиций
            for ticker in self.tickers:
                rec = recommendations.get(ticker, Recommendation(signal="hold", target_price=None, stop_loss=None, horizon="4 недели", confidence=0, reason="Нет данных"))
                current_price = quote_dict.get(ticker)
                if not current_price:
                    continue

                # Открытие позиции
                if rec.signal == "buy" and ticker not in self.positions:
                    quantity = int((self.capital * self.position_size) / current_price)
                    if quantity > 0:
                        self.positions[ticker] = PaperTrade(
                            ticker=ticker,
                            entry_date=current_date,
                            exit_date=None,
                            entry_price=current_price,
                            exit_price=None,
                            quantity=quantity,
                            profit=None,
                            stop_loss=rec.stop_loss
                        )
                        self.capital -= quantity * current_price
                        self.logger.info(f"[paper_trading] Покупка {ticker}: {quantity} по {current_price}")

                # Закрытие позиции
                if ticker in self.positions:
                    pos = self.positions[ticker]
                    should_close = rec.signal == "sell" or (
                        pos.stop_loss and current_price <= pos.stop_loss
                    ) or (current_date - pos.entry_date).days >= 28  # 4 недели
                    if should_close:
                        profit = pos.quantity * (current_price - pos.entry_price)
                        self.capital += pos.quantity * current_price
                        closed_trade = PaperTrade(
                            ticker=ticker,
                            entry_date=pos.entry_date,
                            exit_date=current_date,
                            entry_price=pos.entry_price,
                            exit_price=current_price,
                            quantity=pos.quantity,
                            profit=profit,
                            stop_loss=pos.stop_loss
                        )
                        self.closed_trades.append(closed_trade)
                        self.db_manager.save([closed_trade], "paper_trades")
                        self.logger.info(f"[paper_trading] Продажа {ticker}: прибыль {profit}")
                        del self.positions[ticker]
        except Exception as e:
            self.logger.error(f"[paper_trading] Ошибка обновления: {str(e)}")
            raise PaperTradingError(f"Ошибка обновления сделок: {str(e)}")
```

### Пояснения к реализации
- **Симуляция**:
  - **Покупка**: На сигнал `buy`, 10% капитала, одна позиция на тикер.
  - **Продажа**: На сигнал `sell`, по стоп-лоссу (из `Recommendation`) или через 4 недели.
  - **Котировки**: Заглушка из DuckDB (последняя цена), в будущем — `DataProvider` (yfinance/MOEX).
- **Хранение**: Закрытые сделки сохраняются в `paper_trades` с полями: ticker, entry_date, exit_date, entry_price, exit_price, quantity, profit, stop_loss.
- **Ошибки**: Логируются, при сбое симуляция продолжается с пустыми данными.
- **Оффлайн-режим**: Используются последние котировки из DuckDB.

## Интеграция с другими модулями
- **Aggregator**: Генерирует рекомендации через `aggregate`:
  ```python
  recommendations = aggregator.aggregate({
      'news': AnalyzerInput(urls=['https://ria.ru/rss'], tickers=input_data.tickers),
      'technical': AnalyzerInput(tickers=input_data.tickers),
      'risk': AnalyzerInput(tickers=input_data.tickers)
  })
  ```
- **DatabaseManager**: Загружает котировки и сохраняет сделки:
  ```python
  quotes = db_manager.load("SELECT ticker, close FROM quotes WHERE date = (SELECT MAX(date) FROM quotes)", Quote)
  db_manager.save(closed_trades, "paper_trades")
  ```
- **MainWindow**: Отображает `PaperTradingResult` на вкладке "Портфель" или новой вкладке "Paper Trading".
- **DI**: `PaperPortfolio` инжектируется в `MainWindow`:
  ```python
  # src/core/config.py
  def get_paper_portfolio(db_manager: DatabaseManager) -> PaperTradingInterface:
      aggregator = Aggregator(analyzers={
          'news': get_analyzer('basic_news', db_manager),
          'technical': get_analyzer('technical', db_manager),
          'risk': get_analyzer('risk', db_manager)
      }, recommender=get_recommender())
      return PaperPortfolio(aggregator=aggregator, db_manager=db_manager)
  ```

## Тестирование
Тесты в `tests/test_paper_portfolio.py` проверяют симуляцию, сделки и статус.

```python
import pytest
from unittest.mock import Mock
from src.paper_trading.paper_portfolio import PaperPortfolio, PaperTradingInput, PaperTradingResult
from src.core.exceptions import PaperTradingError
from src.core.models import Quote, Recommendation
from datetime import date

@pytest.fixture
def db_manager():
    db = Mock()
    db.load.return_value = [Quote(ticker="SBER", date=date(2025, 10, 20), close=300.0, open=300, volume=1000, high=305, low=295)]
    db.save = Mock()
    return db

@pytest.fixture
def aggregator():
    agg = Mock()
    agg.aggregate.return_value = {
        'SBER': Recommendation(signal="buy", target_price=None, stop_loss=280.0, horizon="4 недели", confidence=0.7, reason="Test")
    }
    return agg

@pytest.fixture
def paper_portfolio(db_manager, aggregator):
    return PaperPortfolio(aggregator=aggregator, db_manager=db_manager)

def test_start_trading(paper_portfolio, db_manager, aggregator):
    input_data = PaperTradingInput(tickers=['SBER'], initial_capital=10000)
    paper_portfolio.start_trading(input_data)
    assert paper_portfolio.is_running
    assert paper_portfolio.capital < 10000
    assert 'SBER' in paper_portfolio.positions

def test_stop_trading(paper_portfolio, db_manager, aggregator):
    input_data = PaperTradingInput(tickers=['SBER'], initial_capital=10000)
    paper_portfolio.start_trading(input_data)
    aggregator.aggregate.return_value = {
        'SBER': Recommendation(signal="sell", target_price=None, stop_loss=280.0, horizon="4 недели", confidence=0.7, reason="Test")
    }
    result = paper_portfolio.stop_trading()
    assert not paper_portfolio.is_running
    assert isinstance(result, PaperTradingResult)
    assert len(result.closed_trades) > 0
    assert db_manager.save.called

def test_get_status(paper_portfolio, db_manager, aggregator):
    input_data = PaperTradingInput(tickers=['SBER'], initial_capital=10000)
    paper_portfolio.start_trading(input_data)
    status = paper_portfolio.get_status()
    assert isinstance(status, PaperTradingResult)
    assert status.current_capital <= 10000
    assert 'SBER' in status.positions

def test_trading_error(paper_portfolio, db_manager):
    db_manager.load.side_effect = Exception("DB error")
    input_data = PaperTradingInput(tickers=['SBER'], initial_capital=10000)
    with pytest.raises(PaperTradingError):
        paper_portfolio.start_trading(input_data)
```

## Логирование
- Логи сохраняются в `logs/app_YYYYMMDD.log` и таблице `logs` через `DatabaseManager`.
- Категории: `paper_trading`, `error`.
- Пример:
  ```
  2025-10-20 18:30: [paper_trading] Запуск симуляции для ['SBER']
  2025-10-20 18:31: [paper_trading] Покупка SBER: 33 по 300.0
  2025-10-20 18:32: [error] Ошибка обновления: DB error
  ```

## Обработка ошибок
- Кастомное исключение:
  ```python
  # src/core/exceptions.py
  class PaperTradingError(Exception):
      """Ошибка paper trading."""
      pass
  ```
- Fallback: При ошибке симуляция продолжается с пустыми данными.

## Масштабируемость
- **Реальный API**: Замена заглушки на `DataProvider` (yfinance/MOEX).
- **MLflow**: Трекинг результатов в Фазе 3.3.
- **Async**: Добавить QTimer для асинхронного обновления.
- **REST**: Поддержка FastAPI для сериализации `PaperTradingResult`.

## Следующие шаги
- Интегрировать результаты в `MainWindow` (вкладка "Paper Trading" или "Портфель") в Шаге 3.4.
- Перейти к Шагу 3.3 (`Learning`).
- Проверить зависимости: `pip install pandas`.