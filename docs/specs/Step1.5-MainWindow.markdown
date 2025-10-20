# Шаг 1.5: Реализация пользовательского интерфейса (MainWindow)

## Введение
Этот документ описывает реализацию пользовательского интерфейса (UI) приложения с использованием PyQt5, включая главное окно (`MainWindow`) и вкладки (Дашборд, Портфель, Логи, Обучение). UI интегрируется с `Aggregator`, `DatabaseManager` и `NewsAnalyzer` через Dependency Injection (DI), следуя упрощённой модульной архитектуре из `ModularityConcept.md`. Фокус на простоте для MVP: минималистичный дизайн, синхронные вызовы, базовые элементы (таблицы, кнопки, диалоги), с хуками для масштабирования (например, добавление графиков или REST). UI отображает рекомендации, управляет портфелем, показывает логи и метрики обучения, обеспечивая оффлайн-режим и обработку ошибок.

**Цели шага**:
- Создать `MainWindow` с вкладками: Дашборд, Портфель, Логи, Обучение.
- Реализовать UI-компоненты: таблицы (QTableWidget), кнопки (QPushButton), диалоги (QDialog).
- Интегрировать с `Aggregator` для отображения рекомендаций и `DatabaseManager` для портфеля/логов.
- Использовать pydantic модели для данных.
- Добавить тесты (`pytest`) для UI (сигналы, события).
- Обеспечить логирование и обработку ошибок.
- Подготовить к масштабированию (например, замена PyQt5 на Qt for Python или веб-UI).

**Место в архитектуре**:
- Модуль: `src/ui/main_window.py`.
- Зависимости: `PyQt5`, `pydantic`, `src/core/models.py`, `src/core/logging.py`, `src/core/exceptions.py`, `src/ai/aggregator.py`, `src/data/database_manager.py`.
- Интеграция: `MainWindow` получает `Aggregator` и `DatabaseManager` через DI.

## Требования
- **UI-фреймворк**: PyQt5 (QMainWindow, QTabWidget, QTableWidget, QPushButton, QDialog).
- **Вкладки**:
  - **Дашборд**: Таблица рекомендаций (тикер, действие, цель, стоп-лосс, срок, уверенность), диалог детализации.
  - **Портфель**: Таблица позиций, импорт/экспорт CSV, ручной ввод.
  - **Логи**: Журнал событий (обновления, ошибки).
  - **Обучение**: Метрики (Win Rate, Sharpe Ratio), отчёты.
- **Контракт**: Использует `AnalyzerOutput` для рекомендаций, `PortfolioPosition` для портфеля, `Log` для логов.
- **Оффлайн-режим**: Данные из DuckDB, уведомление при сбое API.
- **Ошибки**: Логирование в `logs/app_YYYYMMDD.log`, показ ошибок в UI.
- **Тесты**: Проверка сигналов/событий (coverage >80%).
- **Масштаб**: Хук для замены PyQt5 на веб-UI (FastAPI + React).

## Контракт модуля
UI взаимодействует с бэкендом через `Aggregator` и `DatabaseManager`, используя pydantic модели из `src/core/models.py` (определены в `Step1.3-DatabaseManager.md` и `Step1.4-NewsParser.md`):
- `AnalyzerOutput`: Для рекомендаций (score, confidence, reason).
- `PortfolioPosition`: Для позиций (ticker, quantity, purchase_price, purchase_date).
- `Log`: Для логов (timestamp, category, message).
- `Quote`: Для текущих цен (ticker, date, close).

`MainWindow` не имеет собственного ABC, так как это UI-компонент, но зависит от контрактов `Aggregator` и `DatabaseInterface`.

## Реализация MainWindow
`MainWindow` — основное окно приложения, реализующее QMainWindow с вкладками (QTabWidget). Каждая вкладка — отдельный метод для упрощения читаемости.

### Код
```python
# src/ui/main_window.py
"""Главное окно приложения с UI на PyQt5."""

from PyQt5.QtWidgets import (
    QMainWindow, QTabWidget, QTableWidget, QTableWidgetItem, QPushButton, QVBoxLayout,
    QWidget, QTextEdit, QFileDialog, QDialog, QFormLayout, QLineEdit, QSpinBox,
    QDoubleSpinBox, QDateEdit, QLabel
)
from PyQt5.QtCore import QDate
from typing import Dict, List
from src.ai.aggregator import Aggregator
from src.data.database_manager import DatabaseManager
from src.core.models import AnalyzerOutput, PortfolioPosition, Log, Quote
from src.core.exceptions import ProcessingError, DatabaseError
from src.core.logging import setup_logging
from datetime import date, datetime

class MainWindow(QMainWindow):
    def __init__(self, aggregator: Aggregator, db_manager: DatabaseManager):
        """Инициализация главного окна.

        Args:
            aggregator: Модуль для получения рекомендаций.
            db_manager: Модуль для работы с базой данных.
        """
        super().__init__()
        self.aggregator = aggregator
        self.db_manager = db_manager
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
            "Тикер", "Действие", "Цель", "Стоп-лосс", "Срок", "Уверенность"
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
                'news': AnalyzerInput(urls=['https://ria.ru/rss'], tickers=['SBER', 'GAZP'])
            }
            outputs = self.aggregator.aggregate(input_data)
            self.dashboard_table.setRowCount(len(outputs.get('news', {})))
            for i, (ticker, output) in enumerate(outputs.get('news', {}).items()):
                self.dashboard_table.setItem(i, 0, QTableWidgetItem(ticker))
                action = "Купить" if output.score > 0 else "Продать" if output.score < 0 else "Держать"
                self.dashboard_table.setItem(i, 1, QTableWidgetItem(action))
                self.dashboard_table.setItem(i, 2, QTableWidgetItem("-"))  # Цель: позже
                self.dashboard_table.setItem(i, 3, QTableWidgetItem("-"))  # Стоп-лосс: позже
                self.dashboard_table.setItem(i, 4, QTableWidgetItem("4 недели"))  # Фиксировано
                confidence = f"{'🟢' if output.confidence > 0.8 else '🟠' if output.confidence > 0.5 else '🔴'} {output.confidence*100:.0f}%"
                self.dashboard_table.setItem(i, 5, QTableWidgetItem(confidence))
            self.status_label.setText(f"Последнее обновление: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
            self.logger.info("[ui] Дашборд обновлён")
        except ProcessingError as e:
            self.status_label.setText(f"Ошибка: {str(e)}")
            self.logger.error(f"[ui] Ошибка обновления дашборда: {str(e)}")

    def _show_details_dialog(self, index):
        """Показывает диалог детализации рекомендации."""
        ticker = self.dashboard_table.item(index.row(), 0).text()
        outputs = self.aggregator.aggregate({
            'news': AnalyzerInput(urls=['https://ria.ru/rss'], tickers=[ticker])
        })
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Детали: {ticker}")
        layout = QFormLayout()
        reason = outputs.get('news', {}).get(ticker, AnalyzerOutput(score=0, confidence=0, reason="Нет данных"))
        layout.addRow("Обоснование:", QTextEdit(reason.reason, readOnly=True))
        layout.addRow(QPushButton("ОК", clicked=dialog.accept))
        dialog.setLayout(layout)
        dialog.exec_()

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
        self.learning_table.setColumnCount(4)
        self.learning_table.setHorizontalHeaderLabels(["Стратегия", "Win Rate", "Sharpe Ratio", "Max Drawdown"])
        self.learning_text = QTextEdit(readOnly=True)
        update_button = QPushButton("Обновить метрики")
        update_button.clicked.connect(self._update_learning)
        layout.addWidget(self.learning_table)
        layout.addWidget(self.learning_text)
        layout.addWidget(update_button)
        tab.setLayout(layout)
        self.tabs.addTab(tab, "Обучение")
        self._update_learning()

    def _update_learning(self):
        """Обновляет вкладку Обучение (заглушка для MVP)."""
        self.learning_table.setRowCount(1)
        self.learning_table.setItem(0, 0, QTableWidgetItem("Моментум"))
        self.learning_table.setItem(0, 1, QTableWidgetItem("N/A"))  # Метрики позже
        self.learning_table.setItem(0, 2, QTableWidgetItem("N/A"))
        self.learning_table.setItem(0, 3, QTableWidgetItem("N/A"))
        self.learning_text.setText("Метрики обучения недоступны в MVP")
        self.logger.info("[ui] Вкладка Обучение обновлена")
```

### Пояснения к реализации
- **UI-компоненты**:
  - **Дашборд**: Таблица рекомендаций, обновление через `Aggregator`, диалог детализации по двойному клику.
  - **Портфель**: Таблица позиций, импорт/экспорт CSV, диалог для ручного ввода.
  - **Логи**: QTextEdit для отображения логов, кнопки очистки/экспорта.
  - **Обучение**: Заглушка (таблица и текст), метрики будут в Фазе 3.
- **Интеграция**:
  - `Aggregator` предоставляет рекомендации (`Dict[str, AnalyzerOutput]`).
  - `DatabaseManager` загружает/сохраняет позиции и логи.
- **Ошибки**: Логируются, отображаются в статусной строке.
- **Оффлайн-режим**: Данные из DuckDB, fallback при сбое API.

## Интеграция с другими модулями
- **Aggregator**: Вызывает `aggregate` для рекомендаций:
  ```python
  outputs = aggregator.aggregate({'news': AnalyzerInput(urls=['https://ria.ru/rss'], tickers=['SBER', 'GAZP'])})
  ```
- **DatabaseManager**: Используется для портфеля (`load("SELECT * FROM portfolio", PortfolioPosition)`) и логов (`save([Log(...), ...], "logs")`).
- **DI**: `MainWindow` получает зависимости через конструктор:
  ```python
  # src/core/config.py
  def get_main_window() -> MainWindow:
      db_manager = DatabaseManager()
      aggregator = Aggregator(analyzers={'news': get_analyzer('basic_news')})
      return MainWindow(aggregator=aggregator, db_manager=db_manager)
  ```

## Тестирование
Тесты в `tests/test_main_window.py` проверяют UI-компоненты и сигналы.

```python
import pytest
from PyQt5.QtWidgets import QApplication
from src.ui.main_window import MainWindow
from src.ai.aggregator import Aggregator
from src.data.database_manager import DatabaseManager
from unittest.mock import Mock

@pytest.fixture
def app():
    return QApplication([])

@pytest.fixture
def main_window(app):
    aggregator = Mock(spec=Aggregator)
    aggregator.aggregate.return_value = {
        'news': {
            'SBER': AnalyzerOutput(score=0.5, confidence=0.5, reason="5 упоминаний")
        }
    }
    db_manager = DatabaseManager(db_path=":memory:")
    return MainWindow(aggregator=aggregator, db_manager=db_manager)

def test_dashboard_update(main_window):
    main_window._update_dashboard()
    assert main_window.dashboard_table.rowCount() == 1
    assert main_window.dashboard_table.item(0, 0).text() == "SBER"
    assert "🟠" in main_window.dashboard_table.item(0, 5).text()

def test_portfolio_update(main_window):
    main_window.db_manager.save([
        PortfolioPosition(ticker="SBER", quantity=100, purchase_price=300.0, purchase_date=date(2025, 10, 15))
    ], "portfolio")
    main_window._update_portfolio()
    assert main_window.portfolio_table.rowCount() == 1
    assert main_window.portfolio_table.item(0, 0).text() == "SBER"
```

## Логирование
- Логи сохраняются в `logs/app_YYYYMMDD.log` и таблице `logs` через `DatabaseManager`.
- Категории: `ui`, `error`.
- Пример:
  ```
  2025-10-20 18:30: [ui] Дашборд обновлён
  2025-10-20 18:31: [error] Ошибка импорта CSV: File not found
  ```

## Обработка ошибок
- Исключения (`ProcessingError`, `DatabaseError`) отображаются в `status_label`.
- Fallback: Пустые таблицы/заглушки при ошибках.

## Масштабируемость
- **Замена UI**: Хук для перехода на веб-UI (FastAPI + React) с теми же pydantic моделями.
- **Расширение**: Добавление графиков (Matplotlib) или новых вкладок через QTabWidget.
- **Async**: В будущем добавить QTimer для асинхронных обновлений.

## Следующие шаги
- Реализовать `DataProvider` (Шаг 1.2) для загрузки котировок.
- Перейти к Фазе 2: Технический анализ (Шаг 2.1).
- Проверить зависимости: `pip install PyQt5`.