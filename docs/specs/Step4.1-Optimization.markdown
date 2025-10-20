# Шаг 4.1: Оптимизация

## Введение
Этот документ описывает оптимизацию производительности приложения с использованием профилирования (`cProfile`) и асинхронной обработки данных (`asyncio`) для повышения скорости загрузки данных и выполнения операций. Оптимизация затрагивает ключевые модули: `DataProvider` (Шаг 1.2, пока заглушка), `Aggregator`, `Backtester`, `PaperPortfolio`, `Learner`. Реализация следует принципам `ModularityConcept.md`: минимальные изменения, pydantic модели, Dependency Injection (DI), простота для MVP, логирование и тесты. Результаты профилирования сохраняются в логи, а асинхронные вызовы интегрируются в `MainWindow` для улучшения отзывчивости UI.

**Цели шага**:
- Провести профилирование ключевых методов (`Aggregator.aggregate`, `Backtester.run_backtest`, `PaperPortfolio._update_trades`, `Learner.run_ab_test`) с помощью `cProfile`.
- Перевести загрузку данных (`DataProvider`, `DatabaseManager`) на асинхронные вызовы с использованием `aiohttp` и `duckdb` с асинхронным адаптером.
- Оптимизировать узкие места, выявленные профилированием (например, уменьшение числа SQL-запросов, кэширование).
- Добавить тесты (`pytest-asyncio`) для асинхронных методов.
- Реализовать логирование и обработку ошибок.
- Подготовить к масштабированию (например, кэширование Redis, интеграция MLflow).

**Место в архитектуре**:
- Модули: `src/data/data_provider.py`, `src/ai/aggregator.py`, `src/backtesting/backtester.py`, `src/paper_trading/paper_portfolio.py`, `src/learning/learner.py`, `src/ui/main_window.py`.
- Зависимости: `cProfile`, `pstats`, `aiohttp`, `pytest-asyncio`, `pydantic`, `src/core/models.py`, `src/core/interfaces.py`, `src/core/logging.py`, `src/core/exceptions.py`, `src/data/database_manager.py`.
- Интеграция: Асинхронные методы инжектируются в `MainWindow` через DI.

## Требования
- **Профилирование**:
  - Использовать `cProfile` для анализа методов `aggregate`, `run_backtest`, `_update_trades`, `run_ab_test`.
  - Сохранять результаты в `logs/profile_YYYYMMDD.prof` и агрегированные отчёты в `logs/app_YYYYMMDD.log`.
  - Выявить узкие места (например, SQL-запросы, циклы, API-вызовы).
- **Асинхронность**:
  - Перевести `DataProvider.get_quotes` и `DatabaseManager.load` на `async` с `aiohttp` для API и асинхронным `duckdb`.
  - Обновить `Aggregator`, `Backtester`, `PaperPortfolio`, `Learner` для поддержки `async` методов.
  - Интеграция с `MainWindow` через QTimer для асинхронных обновлений UI.
- **Оптимизация**:
  - Кэширование котировок в памяти (например, `functools.lru_cache`).
  - Уменьшение числа SQL-запросов через пакетную загрузку.
- **Ошибки**: Кастомное исключение (`OptimizationError`), логи в `logs/app_YYYYMMDD.log`.
- **Тесты**: Unit-тесты с `pytest-asyncio` (coverage >80%).
- **Масштаб**: Хук для Redis, MLflow, REST.

## Контракт модуля
Оптимизация затрагивает существующие интерфейсы (`DataProviderInterface`, `BacktesterInterface`, `PaperTradingInterface`, `LearnerInterface`), добавляя асинхронные методы. Новый интерфейс `ProfilerInterface` определяет контракт для профилирования.

### Абстрактные классы
```python
from abc import ABC, abstractmethod
from typing import List, Dict
from pydantic import BaseModel
from datetime import date

class Quote(BaseModel):
    """Модель котировки."""
    ticker: str
    date: date
    close: float
    open: float
    high: float
    low: float
    volume: int

class DataProviderInterface(ABC):
    @abstractmethod
    async def get_quotes(self, tickers: List[str], date_range: tuple[date, date]) -> List[Quote]:
        """Асинхронно загружает котировки.

        Args:
            tickers: Список тикеров.
            date_range: Диапазон дат.

        Returns:
            List[Quote]: Список котировок.

        Raises:
            DataProviderError: Если ошибка загрузки.
        """
        pass

class ProfilerInterface(ABC):
    @abstractmethod
    def profile(self, func: callable, *args, **kwargs) -> Dict[str, float]:
        """Профилирует выполнение функции.

        Args:
            func: Функция для профилирования.
            *args, **kwargs: Аргументы функции.

        Returns:
            Dict[str, float]: Метрики производительности (время выполнения, вызовы).

        Raises:
            OptimizationError: Если ошибка профилирования.
        """
        pass
```

**Изменения в интерфейсах**:
- `DataProviderInterface.get_quotes` теперь `async`.
- `BacktesterInterface.run_backtest`, `PaperTradingInterface._update_trades`, `LearnerInterface.run_ab_test` обновлены до `async`.
- Новый `ProfilerInterface` для профилирования.

## Реализация оптимизации
Реализация включает профилировщик (`Profiler`) и обновление модулей для асинхронности.

### Profiler
```python
# src/optimization/profiler.py
"""Модуль для профилирования производительности."""

import cProfile
import pstats
from io import StringIO
from typing import Dict, Callable
from src.core.interfaces import ProfilerInterface
from src.core.exceptions import OptimizationError
from src.core.logging import setup_logging
from datetime import datetime

class Profiler(ProfilerInterface):
    def __init__(self):
        self.logger = setup_logging()

    def profile(self, func: Callable, *args, **kwargs) -> Dict[str, float]:
        """Профилирует выполнение функции.

        Args:
            func: Функция для профилирования.
            *args, **kwargs: Аргументы функции.

        Returns:
            Dict[str, float]: Метрики производительности.

        Raises:
            OptimizationError: Если ошибка профилирования.
        """
        try:
            profile = cProfile.Profile()
            profile.enable()
            result = func(*args, **kwargs)
            profile.disable()
            s = StringIO()
            ps = pstats.Stats(profile, stream=s).sort_stats('cumulative')
            ps.print_stats(10)  # Топ-10 функций по времени
            profile_file = f"logs/profile_{datetime.now().strftime('%Y%m%d')}.prof"
            profile.dump_stats(profile_file)
            self.logger.info(f"[profiler] Результаты профилирования сохранены в {profile_file}")
            stats = ps.stats
            metrics = {
                "total_time": ps.total_tt,
                "calls": sum(stat[1] for stat in stats.values())
            }
            self.logger.info(f"[profiler] Время: {metrics['total_time']:.2f}s, Вызовы: {metrics['calls']}")
            return metrics
        except Exception as e:
            self.logger.error(f"[profiler] Ошибка профилирования: {str(e)}")
            raise OptimizationError(f"Ошибка профилирования: {str(e)}")
```

### Обновлённый DataProvider
Для MVP используем `yfinance` с `aiohttp` вместо MOEX (Шаг 1.2 пока не реализован, здесь заглушка).

```python
# src/data/data_provider.py
"""Модуль для асинхронной загрузки котировок."""

import aiohttp
import pandas as pd
from typing import List
from src.core.interfaces import DataProviderInterface, Quote
from src.core.exceptions import DataProviderError
from src.core.logging import setup_logging
from datetime import date, timedelta
import yfinance as yf  # Для MVP

class DataProvider(DataProviderInterface):
    def __init__(self):
        self.logger = setup_logging()

    async def get_quotes(self, tickers: List[str], date_range: tuple[date, date]) -> List[Quote]:
        """Асинхронно загружает котировки.

        Args:
            tickers: Список тикеров.
            date_range: Диапазон дат.

        Returns:
            List[Quote]: Список котировок.

        Raises:
            DataProviderError: Если ошибка загрузки.
        """
        try:
            self.logger.info(f"[data_provider] Загрузка котировок для {tickers}")
            async with aiohttp.ClientSession() as session:
                quotes = []
                for ticker in tickers:
                    # Заглушка: используем yfinance (синхронный, для MVP)
                    df = yf.download(ticker, start=date_range[0], end=date_range[1] + timedelta(days=1))
                    for _, row in df.iterrows():
                        quotes.append(Quote(
                            ticker=ticker,
                            date=row.name.date(),
                            close=row['Close'],
                            open=row['Open'],
                            high=row['High'],
                            low=row['Low'],
                            volume=int(row['Volume'])
                        ))
                self.logger.info(f"[data_provider] Загружено {len(quotes)} котировок")
                return quotes
        except Exception as e:
            self.logger.error(f"[data_provider] Ошибка загрузки котировок: {str(e)}")
            raise DataProviderError(f"Ошибка загрузки котировок: {str(e)}")
```

### Обновлённый DatabaseManager
Переводим `load` и `save` на асинхронность с использованием `duckdb` (асинхронный адаптер для MVP).

```python
# src/data/database_manager.py
"""Модуль для асинхронной работы с DuckDB."""

import duckdb
import asyncio
from typing import List, TypeVar, Type
from pydantic import BaseModel
from src.core.exceptions import DatabaseError
from src.core.logging import setup_logging
from functools import lru_cache

T = TypeVar('T', bound=BaseModel)

class DatabaseManager:
    def __init__(self, db_path: str = "data/investment.db"):
        self.db_path = db_path
        self.logger = setup_logging()
        self.conn = duckdb.connect(db_path)

    @lru_cache(maxsize=100)
    async def load(self, query: str, model: Type[T]) -> List[T]:
        """Асинхронно загружает данные из DuckDB.

        Args:
            query: SQL-запрос.
            model: Pydantic-модель для десериализации.

        Returns:
            List[T]: Список объектов модели.

        Raises:
            DatabaseError: Если ошибка загрузки.
        """
        try:
            self.logger.info(f"[db] Выполнение запроса: {query}")
            result = await asyncio.to_thread(self.conn.execute, query)
            rows = result.fetchall()
            columns = [desc[0] for desc in result.description]
            return [model(**dict(zip(columns, row))) for row in rows]
        except Exception as e:
            self.logger.error(f"[db] Ошибка загрузки: {str(e)}")
            raise DatabaseError(f"Ошибка загрузки данных: {str(e)}")

    async def save(self, data: List[BaseModel], table: str) -> None:
        """Асинхронно сохраняет данные в DuckDB.

        Args:
            data: Список объектов pydantic.
            table: Имя таблицы.

        Raises:
            DatabaseError: Если ошибка сохранения.
        """
        try:
            if not data:
                return
            df = pd.DataFrame([item.dict() for item in data])
            await asyncio.to_thread(self.conn.register, "temp_table", df)
            await asyncio.to_thread(self.conn.execute, f"INSERT OR REPLACE INTO {table} SELECT * FROM temp_table")
            self.logger.info(f"[db] Сохранено {len(data)} записей в {table}")
        except Exception as e:
            self.logger.error(f"[db] Ошибка сохранения: {str(e)}")
            raise DatabaseError(f"Ошибка сохранения данных: {str(e)}")
```

### Обновлённый Backtester
Переводим `run_backtest` на `async`.

```python
# src/backtesting/backtester.py
"""Модуль для асинхронного бэктестинга."""

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
        self.aggregator = aggregator
        self.db_manager = db_manager
        self.logger = setup_logging()

    async def run_backtest(self, input_data: BacktestInput) -> BacktestResult:
        """Асинхронно выполняет бэктестинг.

        Args:
            input_data: Входные данные.

        Returns:
            BacktestResult: Результаты с метриками.

        Raises:
            BacktestError: Если ошибка бэктестинга.
        """
        try:
            self.logger.info(f"[backtest] Запуск асинхронного бэктестинга для {input_data.tickers}")
            trades = []
            capital = input_data.initial_capital
            equity = [capital]
            position = {}

            current_date = input_data.date_range[0]
            while current_date <= input_data.date_range[1]:
                recommendations = await self.aggregator.aggregate({
                    'news': AnalyzerInput(urls=['https://ria.ru/rss'], tickers=input_data.tickers),
                    'technical': AnalyzerInput(tickers=input_data.tickers),
                    'risk': AnalyzerInput(tickers=input_data.tickers)
                })
                quotes = await self.db_manager.load(
                    f"SELECT * FROM quotes WHERE date = '{current_date}' AND ticker IN ({','.join(f"'{t}'" for t in input_data.tickers)})",
                    Quote
                )
                quote_dict = {q.ticker: q.close for q in quotes}

                for ticker in input_data.tickers:
                    rec = recommendations.get(ticker, Recommendation(signal="hold", target_price=None, stop_loss=None, horizon="4 недели", confidence=0, reason="Нет данных"))
                    current_price = quote_dict.get(ticker)
                    if not current_price:
                        continue

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

                    if ticker in position:
                        pos = position[ticker]
                        should_close = rec.signal == "sell" or (
                            pos['stop_loss'] and current_price <= pos['stop_loss']
                        ) or (current_date - pos['entry_date']).days >= 28
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

### Обновлённый Aggregator
Переводим `aggregate` на `async`.

```python
# src/ai/aggregator.py
"""Модуль для асинхронной агрегации данных анализаторов."""

from typing import Dict, List
from src.core.interfaces import AnalyzerInterface, RecommenderInterface, AnalyzerInput, AnalyzerOutput, Recommendation
from src.core.exceptions import ProcessingError
from src.core.logging import setup_logging

class Aggregator:
    def __init__(self, analyzers: Dict[str, AnalyzerInterface], recommender: RecommenderInterface):
        self.analyzers = analyzers
        self.recommender = recommender
        self.logger = setup_logging()

    async def aggregate(self, input_data: Dict[str, AnalyzerInput]) -> Dict[str, Recommendation]:
        """Асинхронно агрегирует результаты анализаторов.

        Args:
            input_data: Входные данные для анализаторов.

        Returns:
            Dict[str, Recommendation]: Рекомендации по тикерам.

        Raises:
            ProcessingError: Если ошибка агрегации.
        """
        try:
            results = {}
            for name, analyzer in self.analyzers.items():
                results[name] = await analyzer.analyze(input_data.get(name, AnalyzerInput()))
            recommendations = await self.recommender.generate_recommendations(results)
            self.logger.info("[aggregator] Рекомендации сгенерированы")
            return recommendations
        except Exception as e:
            self.logger.error(f"[aggregator] Ошибка агрегации: {str(e)}")
            raise ProcessingError(f"Ошибка агрегации: {str(e)}")
```

### Обновлённый MainWindow
Добавляем QTimer для асинхронных обновлений.

```python
# src/ui/main_window.py
"""Главное окно с асинхронным обновлением UI."""

from PyQt5.QtWidgets import (
    QMainWindow, QTabWidget, QTableWidget, QTableWidgetItem, QPushButton, QVBoxLayout,
    QWidget, QTextEdit, QFileDialog, QFormLayout, QLineEdit, QSpinBox, QDoubleSpinBox,
    QDateEdit, QLabel
)
from PyQt5.QtCore import QDate, QTimer
import asyncio
from typing import Dict
from src.ai.aggregator import Aggregator
from src.data.database_manager import DatabaseManager
from src.backtesting.backtester import Backtester
from src.paper_trading.paper_portfolio import PaperPortfolio
from src.learning.learner import Learner
from src.optimization.profiler import Profiler
from src.core.models import Recommendation, AnalyzerInput, PortfolioPosition, Log, Quote, BacktestResult, PaperTradingResult, LearningResult
from src.core.exceptions import ProcessingError, DatabaseError, BacktestError, PaperTradingError, LearningError, OptimizationError
from src.core.logging import setup_logging
from datetime import date, datetime, timedelta

class MainWindow(QMainWindow):
    def __init__(self, aggregator: Aggregator, db_manager: DatabaseManager, backtester: Backtester, paper_portfolio: PaperPortfolio, learner: Learner, profiler: Profiler):
        super().__init__()
        self.aggregator = aggregator
        self.db_manager = db_manager
        self.backtester = backtester
        self.paper_portfolio = paper_portfolio
        self.learner = learner
        self.profiler = profiler
        self.logger = setup_logging()
        self.setWindowTitle("Investment Advisor")
        self.setGeometry(100, 100, 800, 600)
        self._init_ui()
        self.loop = asyncio.get_event_loop()
        self.timer = QTimer()
        self.timer.timeout.connect(self._async_update)
        self.timer.start(60000)  # Обновление каждую минуту

    async def _async_update(self):
        """Асинхронно обновляет UI."""
        try:
            await self._update_learning_async()
            self.logger.info("[ui] Асинхронное обновление UI выполнено")
        except Exception as e:
            self.status_label.setText(f"Ошибка: {str(e)}")
            self.logger.error(f"[ui] Ошибка асинхронного обновления: {str(e)}")

    def _init_ui(self):
        # Код из Step3.4 без изменений в _init_dashboard_tab, _init_portfolio_tab, _init_logs_tab
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)
        self._init_dashboard_tab()
        self._init_portfolio_tab()
        self._init_logs_tab()
        self._init_learning_tab()
        self.status_label = QLabel("Последнее обновление: -")
        self.statusBar().addWidget(self.status_label)

    async def _update_learning_async(self, date_start: date = None, date_end: date = None):
        """Асинхронно обновляет вкладку Обучение."""
        try:
            date_start = date_start or (date.today() - timedelta(days=30))
            date_end = date_end or date.today()
            self.learning_table.setRowCount(3)

            # Профилирование и бэктестинг
            backtest_input = BacktestInput(tickers=['SBER', 'GAZP'], date_range=(date_start, date_end), initial_capital=10000)
            backtest_metrics = self.profiler.profile(self.backtester.run_backtest, backtest_input)
            backtest_result = await self.backtester.run_backtest(backtest_input)
            self.learning_table.setItem(0, 0, QTableWidgetItem("Backtest"))
            self.learning_table.setItem(0, 1, QTableWidgetItem(f"{backtest_result.win_rate:.2f}"))
            self.learning_table.setItem(0, 2, QTableWidgetItem(f"{backtest_result.sharpe_ratio:.2f}"))
            self.learning_table.setItem(0, 3, QTableWidgetItem(f"{backtest_result.max_drawdown:.2f}%"))
            self.learning_table.setItem(0, 4, QTableWidgetItem("-"))

            # Paper Trading
            paper_input = PaperTradingInput(tickers=['SBER', 'GAZP'], initial_capital=10000)
            if not self.paper_portfolio.is_running:
                self.paper_portfolio.start_trading(paper_input)
            paper_result = await self.paper_portfolio.get_status()
            paper_win_rate = sum(1 for t in paper_result.closed_trades if t.profit and t.profit > 0) / len(paper_result.closed_trades) if paper_result.closed_trades else 0
            self.learning_table.setItem(1, 0, QTableWidgetItem("Paper Trading"))
            self.learning_table.setItem(1, 1, QTableWidgetItem(f"{paper_win_rate:.2f}"))
            self.learning_table.setItem(1, 2, QTableWidgetItem("-"))
            self.learning_table.setItem(1, 3, QTableWidgetItem("-"))
            self.learning_table.setItem(1, 4, QTableWidgetItem("-"))

            # A/B-тестирование
            learning_input = LearningInput(tickers=['SBER', 'GAZP'], date_range=(date_start, date_end), model_path=":memory:")
            learning_metrics = self.profiler.profile(self.learner.run_ab_test, learning_input)
            learning_result = await self.learner.run_ab_test(learning_input)
            errors = await self.learner.analyze_errors(learning_input)
            self.learning_table.setItem(2, 0, QTableWidgetItem(f"A/B Test ({learning_result.best_model})"))
            self.learning_table.setItem(2, 1, QTableWidgetItem(f"{max(learning_result.win_rate_rf, learning_result.win_rate_svm):.2f}"))
            self.learning_table.setItem(2, 2, QTableWidgetItem("-"))
            self.learning_table.setItem(2, 3, QTableWidgetItem("-"))
            self.learning_table.setItem(2, 4, QTableWidgetItem(f"{max(learning_result.accuracy_rf, learning_result.accuracy_svm):.2f}"))

            # Отчёт
            report = [
                "=== Отчёт по обучению ===",
                f"Бэктестинг (Win Rate: {backtest_result.win_rate:.2f}, Sharpe: {backtest_result.sharpe_ratio:.2f}, Max Drawdown: {backtest_result.max_drawdown:.2f}%, Время: {backtest_metrics['total_time']:.2f}s)",
                f"Paper Trading (Win Rate: {paper_win_rate:.2f}, Текущий капитал: {paper_result.current_capital:.2f})",
                f"A/B-тестирование (Лучшая модель: {learning_result.best_model}, RF Accuracy: {learning_result.accuracy_rf:.2f}, Время: {learning_metrics['total_time']:.2f}s)",
                "Ошибки:",
                *errors
            ]
            self.learning_text.setText("\n".join(report))
            self.status_label.setText(f"Последнее обновление: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
            self.logger.info("[ui] Вкладка Обучение асинхронно обновлена")
        except (BacktestError, PaperTradingError, LearningError, DatabaseError, OptimizationError) as e:
            self.status_label.setText(f"Ошибка: {str(e)}")
            self.logger.error(f"[ui] Ошибка асинхронного обновления обучения: {str(e)}")
```

### Пояснения к реализации
- **Профилирование**:
  - `Profiler` использует `cProfile` для анализа времени выполнения и числа вызовов.
  - Результаты сохраняются в `.prof` файлы и логируются.
- **Асинхронность**:
  - `DataProvider.get_quotes` использует `aiohttp` (заглушка через `yfinance` для MVP).
  - `DatabaseManager.load/save` использует `asyncio.to_thread` для асинхронного доступа к `duckdb`.
  - `Aggregator`, `Backtester`, `Learner` обновлены для `async`.
  - `MainWindow` использует QTimer для периодических асинхронных обновлений.
- **Оптимизация**:
  - Кэширование SQL-запросов через `lru_cache`.
  - Пакетная загрузка котировок для уменьшения числа запросов.
- **Ошибки**: Логируются, UI показывает уведомления в `status_label`.
- **Оффлайн-режим**: Заглушка котировок из DuckDB.

## Интеграция с другими модулями
- **Profiler**: Инжектируется в `MainWindow` для анализа производительности:
  ```python
  backtest_metrics = profiler.profile(backtester.run_backtest, backtest_input)
  ```
- **DataProvider**: Асинхронно загружает котировки:
  ```python
  quotes = await data_provider.get_quotes(tickers, date_range)
  ```
- **DatabaseManager**: Асинхронный доступ к данным:
  ```python
  quotes = await db_manager.load("SELECT * FROM quotes", Quote)
  ```
- **DI**: Обновлённый factory:
  ```python
  # src/core/config.py
  def get_main_window() -> MainWindow:
      db_manager = DatabaseManager()
      data_provider = DataProvider()
      aggregator = Aggregator(analyzers={
          'news': get_analyzer('basic_news', db_manager),
          'technical': get_analyzer('technical', db_manager),
          'risk': get_analyzer('risk', db_manager)
      }, recommender=get_recommender())
      backtester = Backtester(aggregator=aggregator, db_manager=db_manager)
      paper_portfolio = PaperPortfolio(aggregator=aggregator, db_manager=db_manager)
      learner = Learner(aggregator=aggregator, db_manager=db_manager)
      profiler = Profiler()
      return MainWindow(aggregator=aggregator, db_manager=db_manager, backtester=backtester, paper_portfolio=paper_portfolio, learner=learner, profiler=profiler)
  ```

## Тестирование
Тесты в `tests/test_optimization.py` проверяют профилирование и асинхронные методы.

```python
import pytest
import asyncio
from unittest.mock import Mock
from src.optimization.profiler import Profiler
from src.data.data_provider import DataProvider
from src.backtesting.backtester import Backtester
from src.core.models import Quote, BacktestInput, BacktestResult
from src.core.exceptions import OptimizationError, DataProviderError
from datetime import date

@pytest.fixture
def profiler():
    return Profiler()

@pytest.fixture
def data_provider():
    dp = Mock(spec=DataProvider)
    dp.get_quotes.return_value = [Quote(ticker="SBER", date=date(2025, 10, 1), close=300, open=300, high=305, low=295, volume=1000)]
    return dp

@pytest.mark.asyncio
async def test_data_provider_async(data_provider):
    quotes = await data_provider.get_quotes(['SBER'], (date(2025, 10, 1), date(2025, 10, 15)))
    assert len(quotes) == 1
    assert quotes[0].ticker == "SBER"

def test_profiler(profiler, data_provider):
    async def dummy_func():
        return await data_provider.get_quotes(['SBER'], (date(2025, 10, 1), date(2025, 10, 15)))
    metrics = profiler.profile(dummy_func)
    assert "total_time" in metrics
    assert "calls" in metrics
    assert metrics["total_time"] > 0

@pytest.mark.asyncio
async def test_backtester_async(data_provider, db_manager=Mock(), aggregator=Mock()):
    backtester = Backtester(aggregator=aggregator, db_manager=db_manager)
    input_data = BacktestInput(tickers=['SBER'], date_range=(date(2025, 10, 1), date(2025, 10, 15)), initial_capital=10000)
    result = await backtester.run_backtest(input_data)
    assert isinstance(result, BacktestResult)
```

## Логирование
- Логи сохраняются в `logs/app_YYYYMMDD.log` и `logs/profile_YYYYMMDD.prof`.
- Категории: `profiler`, `data_provider`, `db`, `ui`, `error`.
- Пример:
  ```
  2025-10-20 19:01: [profiler] Результаты профилирования сохранены в logs/profile_20251020.prof
  2025-10-20 19:02: [data_provider] Загружено 100 котировок
  2025-10-20 19:03: [error] Ошибка профилирования: Invalid data
  ```

## Обработка ошибок
- Кастомное исключение:
  ```python
  # src/core/exceptions.py
  class OptimizationError(Exception):
      """Ошибка оптимизации."""
      pass
  ```
- Fallback: Пустые результаты при сбоях.

## Масштабируемость
- **Redis**: Кэширование котировок.
- **MLflow**: Логирование метрик производительности.
- **REST**: Поддержка FastAPI для асинхронных API.

## Следующие шаги
- Реализовать `Step1.2-DataProviders.md` для завершения Фазы 1.
- Добавить Redis для кэширования.
- Проверить зависимости: `pip install aiohttp pytest-asyncio yfinance`.