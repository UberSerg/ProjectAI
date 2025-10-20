# Шаг 4.2: Расширение

## Введение
Этот документ описывает расширение функциональности приложения для среднесрочного инвестирования на MOEX с использованием PyTorch LSTM для прогнозирования цен в модуле `Learner`, интеграции MLflow для логирования экспериментов и реализации `TinkoffProvider` для получения котировок через Tinkoff API. Реализация следует принципам `ModularityConcept.md`: чёткие контракты (ABC + pydantic), Dependency Injection (DI), минимальные изменения в существующих модулях (`Learner`, `DataProvider`), простота для MVP с хуками для масштабирования. Расширение включает асинхронные вызовы (`aiohttp` для Tinkoff API), логирование (`logs/app_YYYYMMDD.log`), тесты (`pytest`) и оффлайн-режим через DuckDB.

**Цели шага**:
- Добавить модель PyTorch LSTM в `Learner` для прогнозирования цен (`predict_price`) и улучшения A/B-тестирования.
- Интегрировать MLflow для логирования метрик и параметров экспериментов (`run_ab_test`).
- Реализовать `TinkoffProvider` в `DataProvider` для получения котировок через Tinkoff API с fallback на `MoexProvider` или `FallbackProvider` (yfinance).
- Обновить `MainWindow` для отображения прогнозов LSTM в вкладке "Обучение".
- Добавить тесты (`pytest`, `pytest-asyncio`) для новых функций (coverage >80%).
- Реализовать логирование и обработку ошибок.
- Подготовить к масштабированию (например, Redis, REST API).

**Место в архитектуре**:
- Модули: `src/learning/learner.py`, `src/data/providers.py`, `src/ui/main_window.py`, `src/optimization/mlflow_logger.py`.
- Зависимости: `torch`, `mlflow`, `aiohttp`, `pytest-asyncio`, `pydantic`, `duckdb`, `src/core/models.py`, `src/core/interfaces.py`, `src/core/logging.py`, `src/core/exceptions.py`, `src/data/database_manager.py`.
- Интеграция: `Learner` и `DataProvider` инжектируются в `MainWindow` через DI; MLflow логирует эксперименты в `mlruns/`.

## Требования
- **PyTorch LSTM**:
  - Реализовать модель LSTM в `Learner` для прогнозирования цен (метод `predict_price`).
  - Интегрировать в A/B-тестирование (`run_ab_test`) с Random Forest (RF) и SVM.
  - Сохранять модели в `models/` с помощью `torch.save`.
- **MLflow**:
  - Логировать метрики (`win_rate`, `accuracy`, `mse`), параметры и артефакты экспериментов.
  - Хранить эксперименты в `mlruns/` (локально для MVP).
- **TinkoffProvider**:
  - Использовать Tinkoff API для получения котировок (`async def fetch_quotes`).
  - Fallback на `MoexProvider` или `FallbackProvider` при ошибках.
  - Сохранять котировки в DuckDB через `DatabaseManager`.
- **UI**:
  - Обновить вкладку "Обучение" в `MainWindow` для отображения прогнозов LSTM (QTextEdit).
  - Добавить кнопку "Прогноз LSTM" для вызова `Learner.predict_price`.
- **Ошибки**: Кастомное исключение (`ExtensionError`), логи в `logs/app_YYYYMMDD.log`.
- **Тесты**: Unit- и интеграционные тесты с `pytest` и `pytest-asyncio` (coverage >80%).
- **Масштаб**: Хуки для Redis, REST API, облачного MLflow.

## Контракт модуля
Расширение затрагивает интерфейсы (`LearnerInterface`, `DataProviderInterface`) и добавляет новый `MLflowLoggerInterface`. Используются pydantic модели из `Step1.1-SetupAndModels.md` и `Step1.3-DatabaseManager.md`.

### Абстрактные классы
```python
from abc import ABC, abstractmethod
from typing import List, Dict, Tuple
from pydantic import BaseModel
from datetime import date

class LearnerInterface(ABC):
    @abstractmethod
    async def run_ab_test(self, input_data: 'LearningInput') -> 'LearningResult':
        """Асинхронно выполняет A/B-тестирование."""
        pass

    @abstractmethod
    async def analyze_errors(self, input_data: 'LearningInput') -> List[str]:
        """Асинхронно анализирует ошибки."""
        pass

    @abstractmethod
    async def predict_price(self, ticker: str, date_range: Tuple[date, date], lookback: int = 30) -> float:
        """Асинхронно прогнозирует цену актива с помощью LSTM."""
        pass

class DataProviderInterface(ABC):
    @abstractmethod
    async def fetch_quotes(self, tickers: List[str], start_date: date, end_date: date) -> List['Quote']:
        """Асинхронно получает котировки."""
        pass

class MLflowLoggerInterface(ABC):
    @abstractmethod
    def log_experiment(self, experiment_name: str, metrics: Dict, params: Dict, artifacts: List[str]) -> None:
        """Логирует эксперимент в MLflow."""
        pass
```

### Pydantic модели
Используем модели из `Step1.1` и добавляем новые для `Learner`:

```python
# src/core/models.py
from pydantic import BaseModel
from typing import List
from datetime import date, datetime

class LearningInput(BaseModel):
    tickers: List[str]
    date_range: Tuple[date, date]
    model_path: str

class LearningResult(BaseModel):
    win_rate_rf: float
    accuracy_rf: float
    win_rate_svm: float
    accuracy_svm: float
    win_rate_lstm: float  # Новая метрика
    accuracy_lstm: float  # Новая метрика
    mse_lstm: float       # Новая метрика
    best_model: str
    errors: List[str]
```

## Реализация расширений
Реализация включает обновление `Learner` с PyTorch LSTM, новый `TinkoffProvider`, `MLflowLogger` и обновление `MainWindow`.

### Обновлённый Learner
Добавляем модель LSTM и прогнозирование цен.

```python
# src/learning/learner.py
"""Модуль для асинхронного самообучения с LSTM."""

import asyncio
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from typing import List, Tuple
from sklearn.ensemble import RandomForestClassifier
from sklearn.svm import SVC
from src.core.interfaces import LearnerInterface, LearningInput, LearningResult
from src.core.models import Quote, LearningInput, LearningResult
from src.core.exceptions import LearningError
from src.core.logging import setup_logging
from src.data.database_manager import DatabaseManager
from src.ai.aggregator import Aggregator
from datetime import date, timedelta

class LSTMModel(nn.Module):
    """Модель LSTM для прогнозирования цен."""
    def __init__(self, input_size=1, hidden_size=50, num_layers=2):
        super().__init__()
        self.lstm = nn.LSTM(input_size, hidden_size, num_layers, batch_first=True)
        self.fc = nn.Linear(hidden_size, 1)

    def forward(self, x):
        _, (hn, _) = self.lstm(x)
        return self.fc(hn[-1])

class Learner(LearnerInterface):
    def __init__(self, aggregator: Aggregator, db_manager: DatabaseManager):
        self.aggregator = aggregator
        self.db_manager = db_manager
        self.logger = setup_logging()
        self.rf_model = RandomForestClassifier(n_estimators=100)
        self.svm_model = SVC(probability=True)
        self.lstm_model = LSTMModel()
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.lstm_model.to(self.device)

    async def run_ab_test(self, input_data: LearningInput) -> LearningResult:
        """Асинхронно выполняет A/B-тестирование с RF, SVM и LSTM."""
        try:
            self.logger.info(f"[learner] Запуск A/B-теста для {input_data.tickers}")
            quotes = await self.db_manager.load(
                f"SELECT * FROM quotes WHERE ticker IN ({','.join(f"'{t}'" for t in input_data.tickers)}) "
                f"AND date BETWEEN '{input_data.date_range[0]}' AND '{input_data.date_range[1]}'",
                Quote
            )
            df = pd.DataFrame([q.dict() for q in quotes])
            if df.empty:
                raise LearningError("Нет данных для обучения")

            # Подготовка данных
            X = df[['open', 'volume']].values
            y = (df['close'].shift(-1) > df['close']).astype(int).values[:-1]
            X = X[:-1]

            # RF
            self.rf_model.fit(X, y)
            rf_pred = self.rf_model.predict(X)
            rf_accuracy = (rf_pred == y).mean()
            rf_win_rate = np.mean([1 for i, p in enumerate(rf_pred) if p == 1 and y[i] == 1])

            # SVM
            self.svm_model.fit(X, y)
            svm_pred = self.svm_model.predict(X)
            svm_accuracy = (svm_pred == y).mean()
            svm_win_rate = np.mean([1 for i, p in enumerate(svm_pred) if p == 1 and y[i] == 1])

            # LSTM
            X_lstm = torch.tensor(df[['close']].values, dtype=torch.float32).unsqueeze(0).to(self.device)
            y_lstm = torch.tensor(df['close'].shift(-1).values[:-1], dtype=torch.float32).to(self.device)
            optimizer = torch.optim.Adam(self.lstm_model.parameters(), lr=0.001)
            criterion = nn.MSELoss()
            for _ in range(10):  # Минимальные эпохи для MVP
                self.lstm_model.zero_grad()
                pred = self.lstm_model(X_lstm[:, :-1]).squeeze()
                loss = criterion(pred, y_lstm)
                loss.backward()
                optimizer.step()
            lstm_pred = self.lstm_model(X_lstm[:, :-1]).detach().cpu().numpy()
            lstm_mse = np.mean((lstm_pred - y_lstm.cpu().numpy()) ** 2)
            lstm_accuracy = np.mean((lstm_pred > 0) == (y_lstm.cpu().numpy() > 0))
            lstm_win_rate = np.mean([1 for i, p in enumerate(lstm_pred) if p > 0 and y_lstm[i] > 0])

            # Сохранение модели
            torch.save(self.lstm_model.state_dict(), f"{input_data.model_path}/lstm.pt")

            # Определение лучшей модели
            accuracies = {"rf": rf_accuracy, "svm": svm_accuracy, "lstm": lstm_accuracy}
            best_model = max(accuracies, key=accuracies.get)

            result = LearningResult(
                win_rate_rf=rf_win_rate,
                accuracy_rf=rf_accuracy,
                win_rate_svm=svm_win_rate,
                accuracy_svm=svm_accuracy,
                win_rate_lstm=lstm_win_rate,
                accuracy_lstm=lstm_accuracy,
                mse_lstm=lstm_mse,
                best_model=best_model,
                errors=[]
            )
            self.logger.info(f"[learner] A/B-тест завершен: лучшая модель = {best_model}")
            return result
        except Exception as e:
            self.logger.error(f"[learner] Ошибка A/B-теста: {str(e)}")
            raise LearningError(f"Ошибка A/B-теста: {str(e)}")

    async def predict_price(self, ticker: str, date_range: Tuple[date, date], lookback: int = 30) -> float:
        """Асинхронно прогнозирует цену актива с помощью LSTM."""
        try:
            self.logger.info(f"[learner] Прогноз цены для {ticker}")
            quotes = await self.db_manager.load(
                f"SELECT * FROM quotes WHERE ticker = '{ticker}' AND date BETWEEN "
                f"'{(date_range[0] - timedelta(days=lookback)).isoformat()}' AND '{date_range[1].isoformat()}' "
                f"ORDER BY date DESC LIMIT {lookback}",
                Quote
            )
            if len(quotes) < lookback:
                raise LearningError(f"Недостаточно данных для {ticker}: {len(quotes)} < {lookback}")

            df = pd.DataFrame([q.dict() for q in quotes]).sort_values("date")
            X = torch.tensor(df[['close']].values, dtype=torch.float32).unsqueeze(0).to(self.device)
            self.lstm_model.eval()
            with torch.no_grad():
                pred = self.lstm_model(X).detach().cpu().numpy().flatten()[-1]
            self.logger.info(f"[learner] Прогноз для {ticker}: {pred:.2f}")
            return pred
        except Exception as e:
            self.logger.error(f"[learner] Ошибка прогноза: {str(e)}")
            raise LearningError(f"Ошибка прогноза цены: {str(e)}")

    async def analyze_errors(self, input_data: LearningInput) -> List[str]:
        """Асинхронно анализирует ошибки."""
        try:
            errors = []
            quotes = await self.db_manager.load(
                f"SELECT * FROM quotes WHERE ticker IN ({','.join(f"'{t}'" for t in input_data.tickers)}) "
                f"AND date BETWEEN '{input_data.date_range[0]}' AND '{input_data.date_range[1]}'",
                Quote
            )
            if not quotes:
                errors.append("Нет данных котировок")
            return errors
        except Exception as e:
            self.logger.error(f"[learner] Ошибка анализа ошибок: {str(e)}")
            return [f"Ошибка анализа: {str(e)}"]
```

### MLflow Logger
Логируем эксперименты в MLflow.

```python
# src/optimization/mlflow_logger.py
"""Модуль для логирования экспериментов в MLflow."""

import mlflow
from typing import Dict, List
from src.core.interfaces import MLflowLoggerInterface
from src.core.exceptions import ExtensionError
from src.core.logging import setup_logging

class MLflowLogger(MLflowLoggerInterface):
    def __init__(self):
        self.logger = setup_logging()
        mlflow.set_experiment("investment_advisor")

    def log_experiment(self, experiment_name: str, metrics: Dict, params: Dict, artifacts: List[str]) -> None:
        """Логирует эксперимент в MLflow."""
        try:
            with mlflow.start_run(run_name=experiment_name):
                for key, value in params.items():
                    mlflow.log_param(key, value)
                for key, value in metrics.items():
                    mlflow.log_metric(key, value)
                for artifact in artifacts:
                    mlflow.log_artifact(artifact)
                self.logger.info(f"[mlflow] Эксперимент {experiment_name} залогирован")
        except Exception as e:
            self.logger.error(f"[mlflow] Ошибка логирования: {str(e)}")
            raise ExtensionError(f"Ошибка MLflow: {str(e)}")
```

### TinkoffProvider
Добавляем `TinkoffProvider` в `DataProvider`.

```python
# src/data/providers.py
"""Модуль для асинхронной загрузки данных с MOEX, yfinance и Tinkoff API."""

import aiohttp
import pandas as pd
from typing import List
from datetime import date, timedelta
from src.core.interfaces import DataProviderInterface, Quote
from src.core.exceptions import DataProviderError
from src.core.logging import setup_logging
import yfinance as yf
from tinkoff.invest import AsyncClient, CandleInterval
from tinkoff.invest.utils import now

class TinkoffProvider(DataProviderInterface):
    """Провайдер данных с Tinkoff API."""
    def __init__(self, token: str):
        self.token = token
        self.logger = setup_logging()

    async def fetch_quotes(self, tickers: List[str], start_date: date, end_date: date) -> List[Quote]:
        """Асинхронно получает котировки с Tinkoff API."""
        try:
            self.logger.info(f"[data_provider] Загрузка котировок Tinkoff для {tickers}")
            quotes = []
            async with AsyncClient(self.token) as client:
                for ticker in tickers:
                    try:
                        candles = await client.market_data.get_candles(
                            figi=ticker,  # Для MVP предполагаем, что ticker = FIGI
                            from_=start_date,
                            to=end_date + timedelta(days=1),
                            interval=CandleInterval.CANDLE_INTERVAL_DAY
                        )
                        for candle in candles.candles:
                            quotes.append(Quote(
                                ticker=ticker,
                                date=candle.time.date(),
                                open=candle.open.units + candle.open.nano / 1e9,
                                high=candle.high.units + candle.high.nano / 1e9,
                                low=candle.low.units + candle.low.nano / 1e9,
                                close=candle.close.units + candle.close.nano / 1e9,
                                volume=candle.volume
                            ))
                    except Exception as e:
                        self.logger.error(f"[data_provider] Tinkoff API ошибка для {ticker}: {str(e)}")
                        quotes.extend(await MoexProvider().fetch_quotes([ticker], start_date, end_date))
            self.logger.info(f"[data_provider] Загружено {len(quotes)} котировок Tinkoff")
            return quotes
        except Exception as e:
            self.logger.error(f"[data_provider] Ошибка Tinkoff API: {str(e)}")
            raise DataProviderError(f"Ошибка Tinkoff API: {str(e)}")

class MoexProvider(DataProviderInterface):
    # Код из Step1.2 без изменений
    async def fetch_quotes(self, tickers: List[str], start_date: date, end_date: date) -> List[Quote]:
        try:
            self.logger = setup_logging()
            async with aiohttp.ClientSession() as session:
                quotes = []
                for ticker in tickers:
                    url = f"http://iss.moex.com/iss/history/engines/stock/markets/shares/boards/TQBR/securities/{ticker}/candles.json?from={start_date}&till={end_date}&interval=24"
                    try:
                        async with session.get(url, timeout=10) as response:
                            response.raise_for_status()
                            data = (await response.json()).get("history", {}).get("data", [])
                            for row in data:
                                quotes.append(Quote(
                                    ticker=ticker,
                                    date=date.fromisoformat(row[1]),
                                    open=row[2],
                                    high=row[3],
                                    low=row[4],
                                    close=row[5],
                                    volume=int(row[6])
                                ))
                    except (aiohttp.ClientError, ValueError) as e:
                        self.logger.error(f"[data_provider] MOEX API ошибка для {ticker}: {str(e)}")
                        quotes.extend(await FallbackProvider().fetch_quotes([ticker], start_date, end_date))
                self.logger.info(f"[data_provider] Загружено {len(quotes)} котировок MOEX")
                return quotes
        except Exception as e:
            self.logger.error(f"[data_provider] Ошибка MOEX API: {str(e)}")
            raise DataProviderError(f"Ошибка MOEX API: {str(e)}")

class FallbackProvider(DataProviderInterface):
    # Код из Step1.2 с минимальной адаптацией для async
    async def fetch_quotes(self, tickers: List[str], start_date: date, end_date: date) -> List[Quote]:
        try:
            self.logger = setup_logging()
            quotes = []
            for ticker in [f"{t}.ME" for t in tickers]:
                try:
                    self.logger.info(f"[data_provider] Загрузка yfinance для {ticker}")
                    df = await asyncio.to_thread(yf.download, ticker, start=start_date, end=end_date + timedelta(days=1), interval="1d")
                    for index, row in df.iterrows():
                        quotes.append(Quote(
                            ticker=ticker.replace(".ME", ""),
                            date=index.date(),
                            open=row["Open"],
                            high=row["High"],
                            low=row["Low"],
                            close=row["Close"],
                            volume=int(row["Volume"])
                        ))
                except Exception as e:
                    self.logger.error(f"[data_provider] yfinance ошибка для {ticker}: {str(e)}")
                    continue
            self.logger.info(f"[data_provider] Загружено {len(quotes)} котировок yfinance")
            return quotes
        except Exception as e:
            self.logger.error(f"[data_provider] Ошибка yfinance: {str(e)}")
            raise DataProviderError(f"Ошибка yfinance: {str(e)}")
```

### Обновлённый MainWindow
Добавляем прогноз LSTM в вкладку "Обучение".

```python
# src/ui/main_window.py
"""Главное окно с асинхронным UI и прогнозами LSTM."""

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
from src.optimization.mlflow_logger import MLflowLogger
from src.core.models import Recommendation, AnalyzerInput, PortfolioPosition, Log, Quote, BacktestResult, PaperTradingResult, LearningResult
from src.core.exceptions import ProcessingError, DatabaseError, BacktestError, PaperTradingError, LearningError, OptimizationError, ExtensionError
from src.core.logging import setup_logging
from datetime import date, datetime, timedelta

class MainWindow(QMainWindow):
    def __init__(self, aggregator: Aggregator, db_manager: DatabaseManager, backtester: Backtester, paper_portfolio: PaperPortfolio, learner: Learner, profiler: Profiler, mlflow_logger: MLflowLogger):
        super().__init__()
        self.aggregator = aggregator
        self.db_manager = db_manager
        self.backtester = backtester
        self.paper_portfolio = paper_portfolio
        self.learner = learner
        self.profiler = profiler
        self.mlflow_logger = mlflow_logger
        self.logger = setup_logging()
        self.setWindowTitle("Investment Advisor")
        self.setGeometry(100, 100, 800, 600)
        self._init_ui()
        self.loop = asyncio.get_event_loop()
        self.timer = QTimer()
        self.timer.timeout.connect(self._async_update)
        self.timer.start(60000)

    def _init_ui(self):
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)
        self._init_dashboard_tab()
        self._init_portfolio_tab()
        self._init_logs_tab()
        self._init_learning_tab()
        self.status_label = QLabel("Последнее обновление: -")
        self.statusBar().addWidget(self.status_label)

    def _init_learning_tab(self):
        tab = QWidget()
        layout = QVBoxLayout()
        self.learning_table = QTableWidget()
        self.learning_table.setColumnCount(6)  # Добавляем колонку для прогноза LSTM
        self.learning_table.setHorizontalHeaderLabels([
            "Стратегия", "Win Rate", "Sharpe Ratio", "Max Drawdown", "Accuracy", "LSTM Forecast"
        ])
        self.learning_text = QTextEdit(readOnly=True)
        update_button = QPushButton("Обновить метрики")
        update_button.clicked.connect(lambda: self.loop.create_task(self._update_learning_async()))
        forecast_button = QPushButton("Прогноз LSTM")
        forecast_button.clicked.connect(self._run_lstm_forecast)
        export_button = QPushButton("Экспорт отчёта")
        export_button.clicked.connect(self._export_learning_report)
        date_start = QDateEdit(QDate.currentDate().addMonths(-1))
        date_end = QDateEdit(QDate.currentDate())
        ticker_input = QLineEdit("SBER")
        date_layout = QFormLayout()
        date_layout.addRow("Дата начала:", date_start)
        date_layout.addRow("Дата окончания:", date_end)
        date_layout.addRow("Тикер для прогноза:", ticker_input)
        layout.addLayout(date_layout)
        layout.addWidget(self.learning_table)
        layout.addWidget(self.learning_text)
        layout.addWidget(update_button)
        layout.addWidget(forecast_button)
        layout.addWidget(export_button)
        tab.setLayout(layout)
        self.tabs.addTab(tab, "Обучение")
        self.ticker_input = ticker_input
        self.date_start = date_start
        self.date_end = date_end
        self.loop.create_task(self._update_learning_async())

    async def _async_update(self):
        try:
            await self._update_learning_async()
            self.logger.info("[ui] Асинхронное обновление UI выполнено")
        except Exception as e:
            self.status_label.setText(f"Ошибка: {str(e)}")
            self.logger.error(f"[ui] Ошибка асинхронного обновления: {str(e)}")

    async def _update_learning_async(self, date_start: date = None, date_end: date = None):
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
            self.learning_table.setItem(0, 5, QTableWidgetItem("-"))

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
            self.learning_table.setItem(1, 5, QTableWidgetItem("-"))

            # A/B-тестирование
            learning_input = LearningInput(tickers=['SBER', 'GAZP'], date_range=(date_start, date_end), model_path="models")
            learning_metrics = self.profiler.profile(self.learner.run_ab_test, learning_input)
            learning_result = await self.learner.run_ab_test(learning_input)
            errors = await self.learner.analyze_errors(learning_input)
            self.learning_table.setItem(2, 0, QTableWidgetItem(f"A/B Test ({learning_result.best_model})"))
            self.learning_table.setItem(2, 1, QTableWidgetItem(f"{max(learning_result.win_rate_rf, learning_result.win_rate_svm, learning_result.win_rate_lstm):.2f}"))
            self.learning_table.setItem(2, 2, QTableWidgetItem("-"))
            self.learning_table.setItem(2, 3, QTableWidgetItem("-"))
            self.learning_table.setItem(2, 4, QTableWidgetItem(f"{max(learning_result.accuracy_rf, learning_result.accuracy_svm, learning_result.accuracy_lstm):.2f}"))
            self.learning_table.setItem(2, 5, QTableWidgetItem(f"{learning_result.mse_lstm:.2f}"))

            # Логирование в MLflow
            self.mlflow_logger.log_experiment(
                experiment_name=f"A/B Test {datetime.now().strftime('%Y%m%d_%H%M')}",
                metrics={
                    "win_rate_rf": learning_result.win_rate_rf,
                    "accuracy_rf": learning_result.accuracy_rf,
                    "win_rate_svm": learning_result.win_rate_svm,
                    "accuracy_svm": learning_result.accuracy_svm,
                    "win_rate_lstm": learning_result.win_rate_lstm,
                    "accuracy_lstm": learning_result.accuracy_lstm,
                    "mse_lstm": learning_result.mse_lstm
                },
                params={"tickers": ",".join(input_data.tickers), "epochs": 10},
                artifacts=[f"{learning_input.model_path}/lstm.pt"]
            )

            # Отчёт
            report = [
                "=== Отчёт по обучению ===",
                f"Бэктестинг (Win Rate: {backtest_result.win_rate:.2f}, Sharpe: {backtest_result.sharpe_ratio:.2f}, Max Drawdown: {backtest_result.max_drawdown:.2f}%, Время: {backtest_metrics['total_time']:.2f}s)",
                f"Paper Trading (Win Rate: {paper_win_rate:.2f}, Текущий капитал: {paper_result.current_capital:.2f})",
                f"A/B-тестирование (Лучшая модель: {learning_result.best_model}, RF Accuracy: {learning_result.accuracy_rf:.2f}, SVM Accuracy: {learning_result.accuracy_svm:.2f}, LSTM MSE: {learning_result.mse_lstm:.2f})",
                "Ошибки:",
                *errors
            ]
            self.learning_text.setText("\n".join(report))
            self.status_label.setText(f"Последнее обновление: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
            self.logger.info("[ui] Вкладка Обучение асинхронно обновлена")
        except (BacktestError, PaperTradingError, LearningError, DatabaseError, OptimizationError, ExtensionError) as e:
            self.status_label.setText(f"Ошибка: {str(e)}")
            self.logger.error(f"[ui] Ошибка асинхронного обновления обучения: {str(e)}")

    def _run_lstm_forecast(self):
        """Запускает прогноз LSTM для выбранного тикера."""
        try:
            ticker = self.ticker_input.text()
            date_start = self.date_start.date().toPyDate()
            date_end = self.date_end.date().toPyDate()
            forecast = self.loop.run_until_complete(self.learner.predict_price(ticker, (date_start, date_end)))
            self.learning_text.append(f"\nПрогноз LSTM для {ticker}: {forecast:.2f}")
            self.logger.info(f"[ui] Прогноз LSTM выполнен для {ticker}: {forecast:.2f}")
        except LearningError as e:
            self.status_label.setText(f"Ошибка прогноза: {str(e)}")
            self.logger.error(f"[ui] Ошибка прогноза LSTM: {str(e)}")
```

### Обновлённый Config
Добавляем поддержку TinkoffProvider и MLflowLogger.

```python
# src/core/config.py
"""Фабрика для DI."""

from src.data.providers import DataProvider, MoexProvider, FallbackProvider, TinkoffProvider
from src.data.database_manager import DatabaseManager
from src.ai.aggregator import Aggregator
from src.backtesting.backtester import Backtester
from src.paper_trading.paper_portfolio import PaperPortfolio
from src.learning.learner import Learner
from src.optimization.profiler import Profiler
from src.optimization.mlflow_logger import MLflowLogger
import yaml

def load_config() -> dict:
    with open("config.yaml", "r") as f:
        return yaml.safe_load(f)

def get_data_provider() -> DataProvider:
    config = load_config()
    provider_type = config.get("data_provider", "moex")
    token = config.get("tinkoff_token", "")
    providers = {
        "moex": MoexProvider,
        "yfinance": FallbackProvider,
        "tinkoff": lambda: TinkoffProvider(token=token)
    }
    if provider_type not in providers:
        raise ValueError(f"Unknown provider type: {provider_type}")
    return providers[provider_type]()

def get_main_window() -> 'MainWindow':
    config = load_config()
    db_manager = DatabaseManager()
    data_provider = get_data_provider()
    aggregator = Aggregator(analyzers={
        'news': get_analyzer('basic_news', db_manager),
        'technical': get_analyzer('technical', db_manager),
        'risk': get_analyzer('risk', db_manager)
    }, recommender=get_recommender())
    backtester = Backtester(aggregator=aggregator, db_manager=db_manager)
    paper_portfolio = PaperPortfolio(aggregator=aggregator, db_manager=db_manager)
    learner = Learner(aggregator=aggregator, db_manager=db_manager)
    profiler = Profiler()
    mlflow_logger = MLflowLogger()
    return MainWindow(
        aggregator=aggregator,
        db_manager=db_manager,
        backtester=backtester,
        paper_portfolio=paper_portfolio,
        learner=learner,
        profiler=profiler,
        mlflow_logger=mlflow_logger
    )
```

**config.yaml**:
```yaml
data_provider: tinkoff
tinkoff_token: your_tinkoff_api_token
tickers: ["SBER", "GAZP"]
```

## Интеграция с другими модулями
- **Learner**:
  - Вызывает `predict_price` для прогнозов LSTM:
    ```python
    forecast = await learner.predict_price(ticker="SBER", date_range=(date_start, date_end))
    ```
  - Логирует эксперименты через `MLflowLogger`:
    ```python
    mlflow_logger.log_experiment("A/B Test", metrics, params, artifacts)
    ```
- **TinkoffProvider**:
  - Интегрируется с `DatabaseManager` для сохранения котировок:
    ```python
    await db_manager.save(quotes, "quotes")
    ```
- **MainWindow**:
  - Отображает прогнозы LSTM в QTextEdit:
    ```python
    self.learning_text.append(f"Прогноз LSTM для {ticker}: {forecast:.2f}")
    ```

## Тестирование
Тесты в `tests/test_extensions.py` проверяют LSTM, MLflow и TinkoffProvider.

```python
# tests/test_extensions.py
import pytest
import asyncio
from unittest.mock import Mock, patch
from src.learning.learner import Learner, LSTMModel
from src.data.providers import TinkoffProvider
from src.optimization.mlflow_logger import MLflowLogger
from src.core.models import Quote, LearningInput, LearningResult
from datetime import date
import torch

@pytest.fixture
def learner(db_manager=Mock(), aggregator=Mock()):
    return Learner(aggregator=aggregator, db_manager=db_manager)

@pytest.mark.asyncio
async def test_lstm_predict(learner):
    quotes = [
        Quote(ticker="SBER", date=date(2025, 10, i), open=300, close=310 + i, high=315, low=295, volume=1000)
        for i in range(1, 31)
    ]
    learner.db_manager.load.return_value = quotes
    forecast = await learner.predict_price("SBER", (date(2025, 10, 1), date(2025, 10, 30)), lookback=30)
    assert isinstance(forecast, float)
    assert forecast > 0

@pytest.mark.asyncio
async def test_ab_test_with_lstm(learner):
    quotes = [
        Quote(ticker="SBER", date=date(2025, 10, i), open=300, close=310 + i, high=315, low=295, volume=1000)
        for i in range(1, 31)
    ]
    learner.db_manager.load.return_value = quotes
    input_data = LearningInput(tickers=["SBER"], date_range=(date(2025, 10, 1), date(2025, 10, 30)), model_path=":memory:")
    result = await learner.run_ab_test(input_data)
    assert isinstance(result, LearningResult)
    assert result.mse_lstm >= 0
    assert result.best_model in ["rf", "svm", "lstm"]

def test_mlflow_logger():
    logger = MLflowLogger()
    logger.log_experiment(
        experiment_name="test_experiment",
        metrics={"accuracy": 0.8, "mse": 0.5},
        params={"epochs": 10},
        artifacts=["models/lstm.pt"]
    )
    # Проверяем, что MLflow не выбросил ошибок (файлы в mlruns/)

@pytest.mark.asyncio
async def test_tinkoff_provider():
    provider = TinkoffProvider(token="mock_token")
    with patch("tinkoff.invest.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.market_data.get_candles.return_value.candles = [
            Mock(time=date(2025, 10, 15), open=Mock(units=300, nano=0), high=Mock(units=315, nano=0),
                 low=Mock(units=295, nano=0), close=Mock(units=310, nano=0), volume=1000)
        ]
        quotes = await provider.fetch_quotes(["SBER"], date(2025, 10, 15), date(2025, 10, 15))
        assert len(quotes) == 1
        assert quotes[0].ticker == "SBER"
        assert quotes[0].close == 310.0
```

## Логирование
- Логи сохраняются в `logs/app_YYYYMMDD.log` и таблице `logs`.
- Категории: `learner`, `data_provider`, `mlflow`, `ui`, `error`.
- Пример:
  ```
  2025-10-20 19:30: [learner] Прогноз для SBER: 320.50
  2025-10-20 19:31: [mlflow] Эксперимент A/B Test залогирован
  2025-10-20 19:32: [data_provider] Загружено 100 котировок Tinkoff
  2025-10-20 19:33: [error] Ошибка Tinkoff API: Invalid token
  ```

## Обработка ошибок
- Кастомное исключение:
  ```python
  # src/core/exceptions.py
  class ExtensionError(Exception):
      """Ошибка расширений."""
      pass
  ```
- Fallback: При ошибке Tinkoff API переключаемся на `MoexProvider`.

## Масштабируемость
- **Redis**: Кэширование котировок для TinkoffProvider.
- **REST API**: FastAPI для сериализации прогнозов LSTM.
- **MLflow**: Переход на облачный сервер MLflow.

## Следующие шаги
- Добавить Redis для кэширования котировок.
- Реализовать REST API с FastAPI для прогнозов LSTM.
- Проверить зависимости: `pip install torch mlflow tinkoff-invest-client aiohttp pytest-asyncio`.