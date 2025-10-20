# Шаг 3.4: UI для обучения

## Введение
Этот документ описывает обновление пользовательского интерфейса (`MainWindow`) для отображения результатов бэктестинга (`Backtester`), paper trading (`PaperPortfolio`) и самообучения (`Learner`) на вкладке "Обучение" в PyQt5. Реализация включает таблицу метрик (Win Rate, Sharpe Ratio, Max Drawdown, Accuracy) и отчёты в QTextEdit для детализации ошибок и A/B-тестирования. Модуль следует принципам модульности из `ModularityConcept.md`: чёткие контракты, pydantic модели, Dependency Injection (DI) через factory, простота для MVP с хуками для масштабирования. Шаг включает тестирование UI-компонентов и обработку ошибок.

**Цели шага**:
- Обновить вкладку "Обучение" в `MainWindow` для отображения метрик из `Backtester`, `PaperPortfolio` и `Learner`.
- Реализовать таблицу метрик (QTableWidget) с колонками: Стратегия, Win Rate, Sharpe Ratio, Max Drawdown, Accuracy.
- Добавить QTextEdit для отображения отчётов (ошибки, результаты A/B-теста).
- Использовать pydantic модели (`BacktestResult`, `PaperTradingResult`, `LearningResult`) для данных.
- Добавить тесты (`pytest-qt`) для UI-компонентов и сигналов.
- Реализовать логирование и обработку ошибок.
- Подготовить к масштабированию (например, графики Matplotlib, веб-UI).

**Место в архитектуре**:
- Модуль: `src/ui/main_window.py` (обновление из `Step2.4-UIIntegration.md`).
- Зависимости: `PyQt5`, `pydantic`, `src/core/models.py`, `src/core/interfaces.py`, `src/core/logging.py`, `src/core/exceptions.py`, `src/ai/aggregator.py`, `src/data/database_manager.py`, `src/backtesting/backtester.py`, `src/paper_trading/paper_portfolio.py`, `src/learning/learner.py`.
- Интеграция: `MainWindow` получает `Backtester`, `PaperPortfolio`, `Learner` через DI.

## Требования
- **UI-фреймворк**: PyQt5 (QMainWindow, QTableWidget, QTextEdit, QPushButton, QDateEdit).
- **Таблица метрик** (вкладка "Обучение"):
  - Колонки: Стратегия (Backtest/Paper Trading/A/B Test), Win Rate, Sharpe Ratio, Max Drawdown, Accuracy.
  - Обновление: Кнопка "Обновить метрики" вызывает `Backtester.run_backtest`, `PaperPortfolio.get_status`, `Learner.run_ab_test`.
- **Отчёты**:
  - QTextEdit показывает ошибки (`Learner.analyze_errors`) и результаты A/B-теста (`LearningResult`).
  - Экспорт отчётов в CSV.
- **Контракт**: Использует `BacktestResult`, `PaperTradingResult`, `LearningResult` для данных.
- **Оффлайн-режим**: Данные из DuckDB, уведомление при сбое.
- **Ошибки**: Логи в `logs/app_YYYYMMDD.log`, отображение в статусной строке.
- **Тесты**: Проверка сигналов и событий (coverage >80%).
- **Масштаб**: Хук для графиков (Matplotlib) и веб-UI (FastAPI + React).

## Контракт модуля
UI взаимодействует с бэкендом через `Backtester`, `PaperPortfolio`, `Learner`, используя pydantic модели из `Step3.1-Backtesting.md`, `Step3.2-PaperTrading.md`, `Step3.3-Learning.md`:
- `BacktestResult`: win_rate, sharpe_ratio, max_drawdown, trades.
- `PaperTradingResult`: current_capital, positions, closed_trades.
- `LearningResult`: win_rate_rf, accuracy_rf, win_rate_svm, accuracy_svm, best_model, errors.
- Интерфейсы: `BacktesterInterface`, `PaperTradingInterface`, `LearnerInterface`.

## Реализация UI-интеграции
Обновляем `MainWindow` из `src/ui/main_window.py` (из `Step2.4-UIIntegration.md`), чтобы улучшить вкладку "Обучение". Остальные вкладки ("Дашборд", "Портфель", "Логи") остаются без изменений.

### Код
```python
# src/ui/main_window.py
"""Главное окно приложения с UI на PyQt5."""

from PyQt5.QtWidgets import (
    QMainWindow, QTabWidget, QTableWidget, QTableWidgetItem, QPushButton, QVBoxLayout,
    QWidget, QTextEdit, QFileDialog, QFormLayout, QLineEdit, QSpinBox, QDoubleSpinBox,
    QDateEdit, QLabel
)
from PyQt5.QtCore import QDate
from typing import Dict
from src.ai.aggregator import Aggregator
from src.data.database_manager import DatabaseManager
from src.backtesting.backtester import Backtester, BacktestInput
from src.paper_trading.paper_portfolio import PaperPortfolio, PaperTradingInput
from src.learning.learner import Learner, LearningInput
from src.core.models import Recommendation, AnalyzerInput, PortfolioPosition, Log, Quote, BacktestResult, PaperTradingResult, LearningResult
from src.core.exceptions import ProcessingError, DatabaseError, BacktestError, PaperTradingError, LearningError
from src.core.logging import setup_logging
from datetime import date, datetime, timedelta

class MainWindow(QMainWindow):
    def __init__(self, aggregator: Aggregator, db_manager: DatabaseManager, backtester: Backtester, paper_portfolio: PaperPortfolio, learner: Learner):
        """Инициализация главного окна.

        Args:
            aggregator: Модуль для получения рекомендаций.
            db_manager: Модуль для работы с базой данных.
            backtester: Модуль для бэктестинга.
            paper_portfolio: Модуль для paper trading.
            learner: Модуль для самообучения.
        """
        super().__init__()
        self.aggregator = aggregator
        self.db_manager = db_manager
        self.backtester = backtester
        self.paper_portfolio = paper_portfolio
        self.learner = learner
        self.logger = setup_logging()
        self.setWindowTitle("Investment Advisor")
        self.setGeometry(100, 100, 800, 600)
        self._init_ui()

    def _init_ui(self):
        """Инициализация UI: вкладки и элементы."""
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)

        # Вкладки
        self._init_dashboard_tab()
        self._init_portfolio_tab()
        self._init_logs_tab()
        self._init_learning_tab()

        # Статусная строка
        self.status_label = QLabel("Последнее обновление: -")
        self.statusBar().addWidget(self.status_label)

    def _init_dashboard_tab(self):
        """Инициализация вкладки Дашборд."""
        tab = QWidget()
        layout = QVBoxLayout()
        self.dashboard_table = QTableWidget()
        self.dashboard_table.setColumnCount(6)
        self.dashboard_table.setHorizontalHeaderLabels([
            "Тикер", "Сигнал", "Целевая цена", "Стоп-лосс", "Горизонт", "Уверенность"
        ])
        self.dashboard_table.doubleClicked.connect(self._show_details_dialog)
        update_button = QPushButton("Обновить рекомендации")
        update_button.clicked.connect(self._update_dashboard)
        layout.addWidget(self.dashboard_table)
        layout.addWidget(update_button)
        tab.setLayout(layout)
        self.tabs.addTab(tab, "Дашборд")
        self._update_dashboard()

    def _update_dashboard(self):
        """Обновляет таблицу рекомендаций."""
        try:
            input_data = {
                'news': AnalyzerInput(urls=['https://ria.ru/rss'], tickers=['SBER', 'GAZP']),
                'technical': AnalyzerInput(tickers=['SBER', 'GAZP']),
                'risk': AnalyzerInput(tickers=['SBER', 'GAZP'])
            }
            recommendations = self.aggregator.aggregate(input_data)
            self.dashboard_table.setRowCount(len(recommendations))
            for i, (ticker, rec) in enumerate(recommendations.items()):
                self.dashboard_table.setItem(i, 0, QTableWidgetItem(ticker))
                signal = {"buy": "Купить", "sell": "Продать", "hold": "Держать"}.get(rec.signal, "Держать")
                self.dashboard_table.setItem(i, 1, QTableWidgetItem(signal))
                target_price = f"{rec.target_price:.2f}" if rec.target_price else "-"
                self.dashboard_table.setItem(i, 2, QTableWidgetItem(target_price))
                stop_loss = f"{rec.stop_loss:.2f}" if rec.stop_loss else "-"
                self.dashboard_table.setItem(i, 3, QTableWidgetItem(stop_loss))
                self.dashboard_table.setItem(i, 4, QTableWidgetItem(rec.horizon))
                confidence = f"{'🟢' if rec.confidence > 0.8 else '🟠' if rec.confidence > 0.5 else '🔴'} {rec.confidence*100:.0f}%"
                self.dashboard_table.setItem(i, 5, QTableWidgetItem(confidence))
            self.status_label.setText(f"Последнее обновление: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
            self.logger.info("[ui] Дашборд обновлён")
        except ProcessingError as e:
            self.status_label.setText(f"Ошибка: {str(e)}")
            self.logger.error(f"[ui] Ошибка обновления дашборда: {str(e)}")

    def _show_details_dialog(self, index):
        """Показывает диалог детализации рекомендации."""
        ticker = self.dashboard_table.item(index.row(), 0).text()
        try:
            input_data = {
                'news': AnalyzerInput(urls=['https://ria.ru/rss'], tickers=[ticker]),
                'technical': AnalyzerInput(tickers=[ticker]),
                'risk': AnalyzerInput(tickers=[ticker])
            }
            recommendations = self.aggregator.aggregate(input_data)
            rec = recommendations.get(ticker, Recommendation(
                signal="hold", target_price=None, stop_loss=None, horizon="4 недели",
                confidence=0, reason="Нет данных"
            ))
            dialog = QDialog(self)
            dialog.setWindowTitle(f"Детали: {ticker}")
            layout = QFormLayout()
            text_edit = QTextEdit(readOnly=True)
            text_edit.setText(rec.reason)
            layout.addRow("Обоснование:", text_edit)
            layout.addRow(QPushButton("ОК", clicked=dialog.accept))
            dialog.setLayout(layout)
            dialog.exec_()
            self.logger.info(f"[ui] Открыт диалог детализации для {ticker}")
        except ProcessingError as e:
            self.status_label.setText(f"Ошибка: {str(e)}")
            self.logger.error(f"[ui] Ошибка диалога детализации: {str(e)}")

    def _init_portfolio_tab(self):
        """Инициализация вкладки Портфель."""
        tab = QWidget()
        layout = QVBoxLayout()
        self.portfolio_table = QTableWidget()
        self.portfolio_table.setColumnCount(5)
        self.portfolio_table.setHorizontalHeaderLabels([
            "Тикер", "Количество", "Цена покупки", "Дата покупки", "Доходность"
        ])
        import_button = QPushButton("Импорт CSV")
        import_button.clicked.connect(self._import_portfolio)
        add_button = QPushButton("Добавить вручную")
        add_button.clicked.connect(self._add_position_dialog)
        export_button = QPushButton("Экспорт в CSV")
        export_button.clicked.connect(self._export_portfolio)
        update_button = QPushButton("Обновить портфель")
        update_button.clicked.connect(self._update_portfolio)
        layout.addWidget(self.portfolio_table)
        layout.addWidget(import_button)
        layout.addWidget(add_button)
        layout.addWidget(export_button)
        layout.addWidget(update_button)
        tab.setLayout(layout)
        self.tabs.addTab(tab, "Портфель")
        self._update_portfolio()

    def _update_portfolio(self):
        """Обновляет таблицу портфеля."""
        try:
            positions = self.db_manager.load("SELECT * FROM portfolio", PortfolioPosition)
            quotes = self.db_manager.load("SELECT ticker, close FROM quotes WHERE date = (SELECT MAX(date) FROM quotes)", Quote)
            current_prices = {q.ticker: q.close for q in quotes}
            self.portfolio_table.setRowCount(len(positions))
            for i, pos in enumerate(positions):
                self.portfolio_table.setItem(i, 0, QTableWidgetItem(pos.ticker))
                self.portfolio_table.setItem(i, 1, QTableWidgetItem(str(pos.quantity)))
                self.portfolio_table.setItem(i, 2, QTableWidgetItem(f"{pos.purchase_price:.2f}"))
                self.portfolio_table.setItem(i, 3, QTableWidgetItem(pos.purchase_date.strftime("%Y-%m-%d")))
                current_price = current_prices.get(pos.ticker, pos.purchase_price)
                return_pct = ((current_price - pos.purchase_price) / pos.purchase_price * 100) if pos.purchase_price else 0
                self.portfolio_table.setItem(i, 4, QTableWidgetItem(f"{return_pct:.1f}%"))
            self.logger.info("[ui] Портфель обновлён")
        except DatabaseError as e:
            self.status_label.setText(f"Ошибка: {str(e)}")
            self.logger.error(f"[ui] Ошибка обновления портфеля: {str(e)}")

    def _add_position_dialog(self):
        """Диалог для добавления позиции."""
        dialog = QDialog(self)
        dialog.setWindowTitle("Добавить позицию")
        layout = QFormLayout()
        ticker = QLineEdit()
        quantity = QSpinBox(minimum=1)
        price = QDoubleSpinBox(minimum=0.0)
        purchase_date = QDateEdit(QDate.currentDate())
        layout.addRow("Тикер:", ticker)
        layout.addRow("Количество:", quantity)
        layout.addRow("Цена покупки:", price)
        layout.addRow("Дата покупки:", purchase_date)
        save_button = QPushButton("Сохранить", clicked=lambda: self._save_position(ticker.text(), quantity.value(), price.value(), purchase_date.date().toPyDate(), dialog))
        layout.addRow(save_button)
        layout.addRow(QPushButton("Отмена", clicked=dialog.reject))
        dialog.setLayout(layout)
        dialog.exec_()

    def _save_position(self, ticker: str, quantity: int, price: float, purchase_date: date, dialog: QDialog):
        """Сохраняет новую позицию в портфель."""
        try:
            position = PortfolioPosition(ticker=ticker, quantity=quantity, purchase_price=price, purchase_date=purchase_date)
            self.db_manager.save([position], "portfolio")
            self._update_portfolio()
            dialog.accept()
            self.logger.info(f"[ui] Добавлена позиция: {ticker}")
        except DatabaseError as e:
            self.status_label.setText(f"Ошибка: {str(e)}")
            self.logger.error(f"[ui] Ошибка сохранения позиции: {str(e)}")

    def _import_portfolio(self):
        """Импортирует портфель из CSV."""
        file_name, _ = QFileDialog.getOpenFileName(self, "Импорт CSV", "", "CSV Files (*.csv)")
        if file_name:
            try:
                import pandas as pd
                df = pd.read_csv(file_name)
                positions = [PortfolioPosition(**row) for row in df.to_dict('records')]
                self.db_manager.save(positions, "portfolio")
                self._update_portfolio()
                self.logger.info(f"[ui] Импортировано {len(positions)} позиций из {file_name}")
            except Exception as e:
                self.status_label.setText(f"Ошибка импорта: {str(e)}")
                self.logger.error(f"[ui] Ошибка импорта CSV: {str(e)}")

    def _export_portfolio(self):
        """Экспортирует портфель в CSV."""
        file_name, _ = QFileDialog.getSaveFileName(self, "Экспорт CSV", "", "CSV Files (*.csv)")
        if file_name:
            try:
                positions = self.db_manager.load("SELECT * FROM portfolio", PortfolioPosition)
                import pandas as pd
                df = pd.DataFrame([p.dict() for p in positions])
                df.to_csv(file_name, index=False)
                self.logger.info(f"[ui] Экспортирован портфель в {file_name}")
            except DatabaseError as e:
                self.status_label.setText(f"Ошибка экспорта: {str(e)}")
                self.logger.error(f"[ui] Ошибка экспорта CSV: {str(e)}")

    def _init_logs_tab(self):
        """Инициализация вкладки Логи."""
        tab = QWidget()
        layout = QVBoxLayout()
        self.logs_text = QTextEdit(readOnly=True)
        clear_button = QPushButton("Очистить логи")
        clear_button.clicked.connect(self._clear_logs)
        export_button = QPushButton("Экспорт логов")
        export_button.clicked.connect(self._export_logs)
        layout.addWidget(self.logs_text)
        layout.addWidget(clear_button)
        layout.addWidget(export_button)
        tab.setLayout(layout)
        self.tabs.addTab(tab, "Логи")
        self._update_logs()

    def _update_logs(self):
        """Обновляет вкладку Логи."""
        try:
            logs = self.db_manager.load("SELECT * FROM logs ORDER BY timestamp DESC LIMIT 100", Log)
            self.logs_text.setText("\n".join(f"{log.timestamp}: [{log.category}] {log.message}" for log in logs))
            self.logger.info("[ui] Логи обновлены")
        except DatabaseError as e:
            self.status_label.setText(f"Ошибка: {str(e)}")
            self.logger.error(f"[ui] Ошибка обновления логов: {str(e)}")

    def _clear_logs(self):
        """Очищает таблицу логов."""
        try:
            self.db_manager.save([], "logs")  # Пустой список очищает таблицу
            self._update_logs()
            self.logger.info("[ui] Логи очищены")
        except DatabaseError as e:
            self.status_label.setText(f"Ошибка: {str(e)}")
            self.logger.error(f"[ui] Ошибка очистки логов: {str(e)}")

    def _export_logs(self):
        """Экспортирует логи в CSV."""
        file_name, _ = QFileDialog.getSaveFileName(self, "Экспорт логов", "", "CSV Files (*.csv)")
        if file_name:
            try:
                logs = self.db_manager.load("SELECT * FROM logs", Log)
                import pandas as pd
                df = pd.DataFrame([log.dict() for log in logs])
                df.to_csv(file_name, index=False)
                self.logger.info(f"[ui] Экспортированы логи в {file_name}")
            except DatabaseError as e:
                self.status_label.setText(f"Ошибка экспорта: {str(e)}")
                self.logger.error(f"[ui] Ошибка экспорта логов: {str(e)}")

    def _init_learning_tab(self):
        """Инициализация вкладки Обучение."""
        tab = QWidget()
        layout = QVBoxLayout()
        self.learning_table = QTableWidget()
        self.learning_table.setColumnCount(5)
        self.learning_table.setHorizontalHeaderLabels([
            "Стратегия", "Win Rate", "Sharpe Ratio", "Max Drawdown", "Accuracy"
        ])
        self.learning_text = QTextEdit(readOnly=True)
        update_button = QPushButton("Обновить метрики")
        update_button.clicked.connect(self._update_learning)
        export_button = QPushButton("Экспорт отчёта")
        export_button.clicked.connect(self._export_learning_report)
        date_start = QDateEdit(QDate.currentDate().addMonths(-1))
        date_end = QDateEdit(QDate.currentDate())
        date_layout = QFormLayout()
        date_layout.addRow("Дата начала:", date_start)
        date_layout.addRow("Дата окончания:", date_end)
        layout.addLayout(date_layout)
        layout.addWidget(self.learning_table)
        layout.addWidget(self.learning_text)
        layout.addWidget(update_button)
        layout.addWidget(export_button)
        tab.setLayout(layout)
        self.tabs.addTab(tab, "Обучение")
        self._update_learning(date_start=date_start.date().toPyDate(), date_end=date_end.date().toPyDate())

    def _update_learning(self, date_start: date = None, date_end: date = None):
        """Обновляет вкладку Обучение."""
        try:
            date_start = date_start or (date.today() - timedelta(days=30))
            date_end = date_end or date.today()
            self.learning_table.setRowCount(3)  # Backtest, Paper Trading, A/B Test

            # Бэктестинг
            backtest_input = BacktestInput(tickers=['SBER', 'GAZP'], date_range=(date_start, date_end), initial_capital=10000)
            backtest_result = self.backtester.run_backtest(backtest_input)
            self.learning_table.setItem(0, 0, QTableWidgetItem("Backtest"))
            self.learning_table.setItem(0, 1, QTableWidgetItem(f"{backtest_result.win_rate:.2f}"))
            self.learning_table.setItem(0, 2, QTableWidgetItem(f"{backtest_result.sharpe_ratio:.2f}"))
            self.learning_table.setItem(0, 3, QTableWidgetItem(f"{backtest_result.max_drawdown:.2f}%"))
            self.learning_table.setItem(0, 4, QTableWidgetItem("-"))

            # Paper Trading
            paper_input = PaperTradingInput(tickers=['SBER', 'GAZP'], initial_capital=10000)
            if not self.paper_portfolio.is_running:
                self.paper_portfolio.start_trading(paper_input)
            paper_result = self.paper_portfolio.get_status()
            paper_win_rate = sum(1 for t in paper_result.closed_trades if t.profit and t.profit > 0) / len(paper_result.closed_trades) if paper_result.closed_trades else 0
            self.learning_table.setItem(1, 0, QTableWidgetItem("Paper Trading"))
            self.learning_table.setItem(1, 1, QTableWidgetItem(f"{paper_win_rate:.2f}"))
            self.learning_table.setItem(1, 2, QTableWidgetItem("-"))
            self.learning_table.setItem(1, 3, QTableWidgetItem("-"))
            self.learning_table.setItem(1, 4, QTableWidgetItem("-"))

            # A/B-тестирование
            learning_input = LearningInput(tickers=['SBER', 'GAZP'], date_range=(date_start, date_end), model_path=":memory:")
            learning_result = self.learner.run_ab_test(learning_input)
            errors = self.learner.analyze_errors(learning_input)
            self.learning_table.setItem(2, 0, QTableWidgetItem(f"A/B Test ({learning_result.best_model})"))
            self.learning_table.setItem(2, 1, QTableWidgetItem(f"{max(learning_result.win_rate_rf, learning_result.win_rate_svm):.2f}"))
            self.learning_table.setItem(2, 2, QTableWidgetItem("-"))
            self.learning_table.setItem(2, 3, QTableWidgetItem("-"))
            self.learning_table.setItem(2, 4, QTableWidgetItem(f"{max(learning_result.accuracy_rf, learning_result.accuracy_svm):.2f}"))

            # Отчёт в QTextEdit
            report = [
                "=== Отчёт по обучению ===",
                f"Бэктестинг (Win Rate: {backtest_result.win_rate:.2f}, Sharpe: {backtest_result.sharpe_ratio:.2f}, Max Drawdown: {backtest_result.max_drawdown:.2f}%)",
                f"Paper Trading (Win Rate: {paper_win_rate:.2f}, Текущий капитал: {paper_result.current_capital:.2f})",
                f"A/B-тестирование (Лучшая модель: {learning_result.best_model}, RF Accuracy: {learning_result.accuracy_rf:.2f}, SVM Accuracy: {learning_result.accuracy_svm:.2f})",
                "Ошибки:",
                *errors
            ]
            self.learning_text.setText("\n".join(report))
            self.status_label.setText(f"Последнее обновление: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
            self.logger.info("[ui] Вкладка Обучение обновлена")
        except (BacktestError, PaperTradingError, LearningError, DatabaseError) as e:
            self.status_label.setText(f"Ошибка: {str(e)}")
            self.logger.error(f"[ui] Ошибка обновления обучения: {str(e)}")

    def _export_learning_report(self):
        """Экспортирует отчёт по обучению в CSV."""
        file_name, _ = QFileDialog.getSaveFileName(self, "Экспорт отчёта", "", "CSV Files (*.csv)")
        if file_name:
            try:
                data = []
                for row in range(self.learning_table.rowCount()):
                    row_data = {
                        "Strategy": self.learning_table.item(row, 0).text(),
                        "Win Rate": self.learning_table.item(row, 1).text(),
                        "Sharpe Ratio": self.learning_table.item(row, 2).text(),
                        "Max Drawdown": self.learning_table.item(row, 3).text(),
                        "Accuracy": self.learning_table.item(row, 4).text()
                    }
                    data.append(row_data)
                import pandas as pd
                df = pd.DataFrame(data)
                df.to_csv(file_name, index=False)
                self.logger.info(f"[ui] Экспортирован отчёт в {file_name}")
            except Exception as e:
                self.status_label.setText(f"Ошибка экспорта: {str(e)}")
                self.logger.error(f"[ui] Ошибка экспорта отчёта: {str(e)}")
```

### Пояснения к реализации
- **Таблица метрик**:
  - Показывает результаты трёх стратегий: Backtest, Paper Trading, A/B Test.
  - Колонки: Стратегия, Win Rate, Sharpe Ratio, Max Drawdown, Accuracy.
  - Данные: `BacktestResult`, `PaperTradingResult` (Win Rate вычисляется), `LearningResult`.
- **Отчёты**:
  - QTextEdit отображает метрики и ошибки (`Learner.analyze_errors`).
  - Экспорт в CSV через кнопку.
- **Изменения**: Обновлена только вкладка "Обучение" (`_init_learning_tab`, `_update_learning`, `_export_learning_report`), остальные вкладки сохранены из `Step2.4`.
- **Ошибки**: Логируются и отображаются в статусной строке.
- **Оффлайн-режим**: Данные из DuckDB, fallback при сбое — пустая таблица/отчёт.

## Интеграция с другими модулями
- **Backtester**: Вызывает `run_backtest` для метрик:
  ```python
  backtest_result = backtester.run_backtest(BacktestInput(tickers=['SBER', 'GAZP'], date_range=(date_start, date_end), initial_capital=10000))
  ```
- **PaperPortfolio**: Вызывает `get_status` для текущего состояния:
  ```python
  paper_result = paper_portfolio.get_status()
  ```
- **Learner**: Вызывает `run_ab_test` и `analyze_errors`:
  ```python
  learning_result = learner.run_ab_test(LearningInput(tickers=['SBER', 'GAZP'], date_range=(date_start, date_end), model_path=":memory:"))
  errors = learner.analyze_errors(learning_input)
  ```
- **DI**: `MainWindow` получает модули через конструктор:
  ```python
  # src/core/config.py
  def get_main_window() -> MainWindow:
      db_manager = DatabaseManager()
      aggregator = Aggregator(analyzers={
          'news': get_analyzer('basic_news', db_manager),
          'technical': get_analyzer('technical', db_manager),
          'risk': get_analyzer('risk', db_manager)
      }, recommender=get_recommender())
      backtester = Backtester(aggregator=aggregator, db_manager=db_manager)
      paper_portfolio = PaperPortfolio(aggregator=aggregator, db_manager=db_manager)
      learner = Learner(aggregator=aggregator, db_manager=db_manager)
      return MainWindow(aggregator=aggregator, db_manager=db_manager, backtester=backtester, paper_portfolio=paper_portfolio, learner=learner)
  ```

## Тестирование
Тесты в `tests/test_training_ui.py` проверяют таблицу метрик, отчёты и сигналы.

```python
import pytest
from PyQt5.QtWidgets import QApplication
from src.ui.main_window import MainWindow
from src.ai.aggregator import Aggregator
from src.data.database_manager import DatabaseManager
from src.backtesting.backtester import Backtester
from src.paper_trading.paper_portfolio import PaperPortfolio
from src.learning.learner import Learner
from src.core.models import BacktestResult, PaperTradingResult, LearningResult, PaperTrade
from unittest.mock import Mock
from datetime import date

@pytest.fixture
def app():
    return QApplication([])

@pytest.fixture
def main_window(app):
    aggregator = Mock(spec=Aggregator)
    db_manager = Mock(spec=DatabaseManager)
    backtester = Mock(spec=Backtester)
    backtester.run_backtest.return_value = BacktestResult(win_rate=0.6, sharpe_ratio=1.2, max_drawdown=10.0, trades=[])
    paper_portfolio = Mock(spec=PaperPortfolio)
    paper_portfolio.is_running = False
    paper_portfolio.get_status.return_value = PaperTradingResult(current_capital=10000, positions={}, closed_trades=[PaperTrade(ticker="SBER", entry_date=date(2025, 10, 1), exit_date=date(2025, 10, 15), entry_price=300, exit_price=320, quantity=10, profit=200, stop_loss=280)])
    learner = Mock(spec=Learner)
    learner.run_ab_test.return_value = LearningResult(win_rate_rf=0.7, accuracy_rf=0.8, win_rate_svm=0.6, accuracy_svm=0.7, best_model="rf", errors=["Ошибка: SBER убыток"])
    learner.analyze_errors.return_value = ["Ошибка: SBER убыток"]
    return MainWindow(aggregator=aggregator, db_manager=db_manager, backtester=backtester, paper_portfolio=paper_portfolio, learner=learner)

def test_learning_tab_update(main_window):
    main_window._update_learning(date_start=date(2025, 10, 1), date_end=date(2025, 10, 15))
    assert main_window.learning_table.rowCount() == 3
    assert main_window.learning_table.item(0, 0).text() == "Backtest"
    assert main_window.learning_table.item(0, 1).text() == "0.60"
    assert main_window.learning_table.item(0, 2).text() == "1.20"
    assert main_window.learning_table.item(0, 3).text() == "10.00%"
    assert main_window.learning_table.item(2, 0).text() == "A/B Test (rf)"
    assert main_window.learning_table.item(2, 4).text() == "0.80"
    assert "Ошибка: SBER убыток" in main_window.learning_text.toPlainText()

def test_export_learning_report(main_window, tmp_path):
    main_window._update_learning(date_start=date(2025, 10, 1), date_end=date(2025, 10, 15))
    file_name = tmp_path / "report.csv"
    main_window._export_learning_report = lambda: file_name  # Mock QFileDialog
    main_window._export_learning_report()
    import pandas as pd
    df = pd.read_csv(file_name)
    assert len(df) == 3
    assert df.iloc[0]["Strategy"] == "Backtest"
    assert df.iloc[2]["Accuracy"] == "0.80"
```

## Логирование
- Логи сохраняются в `logs/app_YYYYMMDD.log` и таблице `logs` через `DatabaseManager`.
- Категории: `ui`, `error`.
- Пример:
  ```
  2025-10-20 18:30: [ui] Вкладка Обучение обновлена
  2025-10-20 18:31: [ui] Экспортирован отчёт в report.csv
  2025-10-20 18:32: [error] Ошибка обновления обучения: DB error
  ```

## Обработка ошибок
- Исключения (`BacktestError`, `PaperTradingError`, `LearningError`, `DatabaseError`) отображаются в `status_label`.
- Fallback: Пустая таблица или отчёт при ошибках.

## Масштабируемость
- **Графики**: Хук для Matplotlib (кривые доходности, метрики).
- **Веб-UI**: Поддержка FastAPI + React для сериализации результатов.
- **Async**: Добавить QTimer для асинхронных обновлений.

## Следующие шаги
- Реализовать `Step1.2-DataProviders.md` для завершения Фазы 1.
- Добавить графики Matplotlib в `MainWindow` для визуализации метрик.
- Проверить зависимости: `pip install PyQt5 pandas`.