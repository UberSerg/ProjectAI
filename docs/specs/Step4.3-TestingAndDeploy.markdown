# Шаг 4.3: Полное тестирование и деплой

## Введение
Этот документ описывает финальный шаг Фазы 4 — полное тестирование и деплой приложения для среднесрочного инвестирования на MOEX. Реализация включает end-to-end (E2E) тесты для проверки интеграции всех модулей (`DataProvider`, `DatabaseManager`, `Aggregator`, `Backtester`, `PaperPortfolio`, `Learner`, `MainWindow`), сборку исполняемого файла с помощью PyInstaller и контейнеризацию с использованием Docker. Работа следует принципам `ModularityConcept.md`: чёткие контракты (ABC + pydantic), Dependency Injection (DI), минимальные изменения в существующих модулях, логирование, тесты (`pytest`, `pytest-asyncio`) с покрытием >80% и подготовка к масштабированию (например, CI/CD, облачный деплой).

**Цели шага**:
- Реализовать E2E тесты для проверки полного цикла: загрузка котировок (`DataProvider`), сохранение в DuckDB (`DatabaseManager`), агрегация (`Aggregator`), бэктестинг (`Backtester`), бумажная торговля (`PaperPortfolio`), обучение (`Learner`) и отображение в UI (`MainWindow`).
- Собрать приложение в исполняемый файл с помощью PyInstaller для Windows/Linux/macOS.
- Создать Docker-образ для воспроизводимого деплоя с поддержкой оффлайн-режима.
- Добавить тесты для проверки сборки и контейнера.
- Реализовать логирование и обработку ошибок.
- Подготовить к масштабированию (CI/CD, облачный деплой).

**Место в архитектуре**:
- Модули: `tests/e2e/test_e2e.py`, `scripts/build.py`, `Dockerfile`, `docker-compose.yml`.
- Зависимости: `pytest`, `pytest-asyncio`, `pytest-qt`, `pyinstaller`, `docker`, `torch`, `mlflow`, `tinkoff-invest-client`, `aiohttp`, `pydantic`, `duckdb`, `src/core/*`, `src/data/*`, `src/ai/*`, `src/backtesting/*`, `src/paper_trading/*`, `src/learning/*`, `src/ui/*`, `src/optimization/*`.
- Интеграция: E2E тесты используют DI через `src/core/config.py`; PyInstaller и Docker интегрируются с `MainWindow`.

## Требования
- **E2E тесты**:
  - Проверять полный цикл: загрузка котировок (`TinkoffProvider` → `DatabaseManager`), агрегация, бэктестинг, бумажная торговля, обучение (LSTM) и отображение в UI.
  - Использовать `pytest` и `pytest-qt` для тестирования PyQt UI.
  - Покрытие >80% (включая unit-тесты из предыдущих шагов).
  - Mock для внешних API (Tinkoff, MOEX, yfinance).
- **PyInstaller**:
  - Собрать исполняемый файл (`investment_advisor.exe` для Windows, аналогично для Linux/macOS).
  - Включить зависимости (`torch`, `mlflow`, `duckdb`) и ресурсы (`data/app.db`, `models/`).
  - Создать скрипт `scripts/build.py` для автоматизации сборки.
- **Docker**:
  - Создать `Dockerfile` для контейнеризации приложения.
  - Использовать `docker-compose.yml` для запуска с MLflow и DuckDB.
  - Поддерживать оффлайн-режим (локальная база DuckDB).
- **Ошибки**: Кастомное исключение (`DeployError`), логи в `logs/app_YYYYMMDD.log`.
- **Тесты**: Unit-тесты для проверки сборки и контейнера.
- **Масштаб**: Хуки для CI/CD (GitHub Actions), облачного деплоя (AWS/GCP).

## Контракт модуля
E2E тесты используют существующие интерфейсы (`DataProviderInterface`, `DatabaseInterface`, `LearnerInterface`, etc.) из `Step4.1` и `Step4.2`. PyInstaller и Docker взаимодействуют с `MainWindow` как точкой входа.

### Абстрактные классы
Уже определены в `Step4.1` и `Step4.2`. Новые интерфейсы не требуются.

### Pydantic модели
Используем модели из `Step1.1` и `Step4.2` (`Quote`, `LearningInput`, `LearningResult`, etc.) без изменений.

## Реализация тестирования и деплоя

### End-to-End тесты
E2E тесты проверяют полный цикл работы приложения.

```python
# tests/e2e/test_e2e.py
"""End-to-end тесты для приложения."""

import pytest
import asyncio
from unittest.mock import patch, Mock
from PyQt5.QtCore import QTimer
from src.ui.main_window import MainWindow
from src.core.config import get_main_window
from src.core.models import Quote, LearningInput, BacktestInput, PaperTradingInput
from datetime import date, timedelta
from pytestqt.qtbot import QtBot

@pytest.fixture
def main_window(qtbot: QtBot):
    """Фикстура для MainWindow."""
    window = get_main_window()
    qtbot.addWidget(window)
    return window

@pytest.fixture
def mock_data_provider():
    """Mock для DataProvider."""
    provider = Mock()
    provider.fetch_quotes.return_value = [
        Quote(ticker="SBER", date=date(2025, 10, 15), open=300.0, close=310.0, high=315.0, low=295.0, volume=1000)
    ]
    return provider

@pytest.mark.asyncio
async def test_e2e_full_cycle(qtbot: QtBot, main_window: MainWindow, mock_data_provider):
    """Проверяет полный цикл работы приложения."""
    with patch("src.core.config.get_data_provider", return_value=mock_data_provider):
        # Инициализация
        assert main_window.tabs.count() == 4  # Dashboard, Portfolio, Logs, Learning

        # Загрузка котировок
        quotes = await main_window.db_manager.load("SELECT * FROM quotes", Quote)
        assert len(quotes) == 0  # База пуста изначально
        await main_window.data_provider.fetch_quotes(["SBER"], date(2025, 10, 1), date(2025, 10, 15))
        await main_window.db_manager.save(mock_data_provider.fetch_quotes(["SBER"], date(2025, 10, 1), date(2025, 10, 15)), "quotes")
        quotes = await main_window.db_manager.load("SELECT * FROM quotes WHERE ticker = 'SBER'", Quote)
        assert len(quotes) == 1
        assert quotes[0].close == 310.0

        # Бэктестинг
        backtest_input = BacktestInput(tickers=["SBER"], date_range=(date(2025, 10, 1), date(2025, 10, 15)), initial_capital=10000)
        backtest_result = await main_window.backtester.run_backtest(backtest_input)
        assert backtest_result.win_rate >= 0

        # Paper Trading
        paper_input = PaperTradingInput(tickers=["SBER"], initial_capital=10000)
        main_window.paper_portfolio.start_trading(paper_input)
        paper_result = await main_window.paper_portfolio.get_status()
        assert paper_result.current_capital >= 0

        # A/B-тестирование и LSTM
        learning_input = LearningInput(tickers=["SBER"], date_range=(date(2025, 10, 1), date(2025, 10, 15)), model_path=":memory:")
        learning_result = await main_window.learner.run_ab_test(learning_input)
        assert learning_result.best_model in ["rf", "svm", "lstm"]
        forecast = await main_window.learner.predict_price("SBER", (date(2025, 10, 1), date(2025, 10, 15)))
        assert isinstance(forecast, float)

        # Проверка UI
        qtbot.waitUntil(lambda: main_window.learning_table.rowCount() == 3, timeout=5000)
        assert main_window.learning_table.item(2, 0).text().startswith("A/B Test")
        assert float(main_window.learning_table.item(2, 4).text()) >= 0  # Accuracy
        assert float(main_window.learning_table.item(2, 5).text()) >= 0  # MSE LSTM

        # Логирование MLflow
        with patch("mlflow.start_run"):
            main_window.mlflow_logger.log_experiment(
                "E2E Test", {"accuracy": 0.8}, {"tickers": "SBER"}, []
            )
```

### PyInstaller сборка
Скрипт для сборки исполняемого файла.

```python
# scripts/build.py
"""Скрипт для сборки приложения с PyInstaller."""

import PyInstaller.__main__
import os
import sys
from datetime import datetime

def build_app():
    """Собирает приложение в исполняемый файл."""
    output_dir = f"dist/investment_advisor_{datetime.now().strftime('%Y%m%d')}"
    spec = [
        "--name=investment_advisor",
        "--onedir",
        f"--add-data=data/app.db{os.pathsep}data",
        f"--add-data=models{os.pathsep}models",
        f"--add-data=logs{os.pathsep}logs",
        "--hidden-import=torch",
        "--hidden-import=mlflow",
        "--hidden-import=tinkoff.invest",
        "--hidden-import=pydantic",
        "--hidden-import=duckdb",
        "--hidden-import=aiohttp",
        "--hidden-import=pandas",
        "--hidden-import=numpy",
        "--hidden-import=sklearn",
        "--hidden-import=pandas_ta",
        "--hidden-import=feedparser",
        "--hidden-import=schedule",
        "--hidden-import=joblib",
        f"--distpath={output_dir}",
        "src/main.py"
    ]
    try:
        PyInstaller.__main__.run(spec)
        print(f"Сборка завершена: {output_dir}/investment_advisor")
    except Exception as e:
        print(f"Ошибка сборки: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    build_app()
```

**Точка входа**:
```python
# src/main.py
"""Точка входа для приложения."""

from src.ui.main_window import MainWindow
from src.core.config import get_main_window
from PyQt5.QtWidgets import QApplication
import sys

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = get_main_window()
    window.show()
    sys.exit(app.exec_())
```

### Docker контейнеризация
Создаём `Dockerfile` и `docker-compose.yml` для воспроизводимого окружения.

```dockerfile
# Dockerfile
FROM python:3.9-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ src/
COPY data/ data/
COPY models/ models/
COPY logs/ logs/
COPY config.yaml .

ENV PYTHONUNBUFFERED=1
ENV QT_LOGGING_RULES="qt5ct.debug=false"

CMD ["python", "src/main.py"]
```

```yaml
# docker-compose.yml
version: "3.8"
services:
  app:
    build: .
    volumes:
      - ./data:/app/data
      - ./models:/app/models
      - ./logs:/app/logs
      - ./mlruns:/app/mlruns
    environment:
      - TINKOFF_TOKEN=${TINKOFF_TOKEN}
    ports:
      - "5000:5000"  # Для MLflow UI
  mlflow:
    image: ghcr.io/mlflow/mlflow:latest
    volumes:
      - ./mlruns:/mlruns
    ports:
      - "5000:5000"
    command: mlflow server --host 0.0.0.0 --port 5000 --backend-store-uri file:///mlruns
```

**requirements.txt** (обновлённый):
```
pydantic>=2.0
pytest>=7.0
pytest-asyncio>=0.21
pytest-qt>=4.0
pytest-cov>=4.0
requests>=2.28
pandas>=1.5
duckdb>=0.8
pyqt5>=5.15
scikit-learn>=1.2
pandas_ta>=0.3
feedparser>=6.0
schedule>=1.1
joblib>=1.2
yfinance>=0.2
aiohttp>=3.8
torch>=2.0
mlflow>=2.0
tinkoff-invest-client>=0.1
pyinstaller>=5.0
```

## Интеграция с другими модулями
- **E2E тесты**:
  - Используют DI через `get_main_window`:
    ```python
    window = get_main_window()
    ```
  - Проверяют весь цикл: `DataProvider` → `DatabaseManager` → `Aggregator` → `Backtester` → `PaperPortfolio` → `Learner` → `MainWindow`.
- **PyInstaller**:
  - Собирает `MainWindow` как точку входа с зависимостями и ресурсами.
- **Docker**:
  - Включает `data/app.db`, `models/`, `logs/`, `mlruns/` через volumes.
  - Запускает MLflow сервер для просмотра экспериментов.

## Тестирование
Тесты в `tests/e2e/test_e2e.py` проверяют интеграцию всех модулей. Дополнительные тесты для сборки и Docker.

```python
# tests/test_deploy.py
"""Тесты для сборки и контейнеризации."""

import pytest
import os
import subprocess

def test_pyinstaller_build():
    """Проверяет сборку PyInstaller."""
    result = subprocess.run(["python", "scripts/build.py"], capture_output=True, text=True)
    assert result.returncode == 0
    assert os.path.exists(f"dist/investment_advisor_{datetime.now().strftime('%Y%m%d')}/investment_advisor")
    assert "Ошибка сборки" not in result.stderr

def test_docker_build():
    """Проверяет сборку Docker-образа."""
    result = subprocess.run(["docker", "build", "-t", "investment_advisor:test", "."], capture_output=True, text=True)
    assert result.returncode == 0
    assert "Successfully built" in result.stdout
```

Запуск тестов:
```bash
pytest tests/e2e/test_e2e.py tests/test_deploy.py --cov=src --cov-report=html
```

## Логирование
- Логи сохраняются в `logs/app_YYYYMMDD.log` и таблице `logs`.
- Категории: `e2e`, `deploy`, `error`.
- Пример:
  ```
  2025-10-20 19:40: [e2e] Успешное выполнение E2E теста
  2025-10-20 19:41: [deploy] Сборка PyInstaller завершена: dist/investment_advisor_20251020
  2025-10-20 19:42: [error] Ошибка Docker: No space left on device
  ```

## Обработка ошибок
- Кастомное исключение:
  ```python
  # src/core/exceptions.py
  class DeployError(Exception):
      """Ошибка деплоя."""
      pass
  ```
- Fallback: При ошибке сборки/контейнеризации логируем и завершаем с кодом 1.

## Масштабируемость
- **CI/CD**: Настроить GitHub Actions для автотестов и деплоя.
- **Облако**: Развернуть Docker-образ на AWS ECS/GCP Cloud Run.
- **Мониторинг**: Добавить Prometheus для метрик производительности.

## Установка и запуск
1. **Сборка PyInstaller**:
   ```bash
   pip install -r requirements.txt
   python scripts/build.py
   ./dist/investment_advisor_20251020/investment_advisor
   ```
2. **Запуск Docker**:
   ```bash
   export TINKOFF_TOKEN=your_token
   docker-compose up --build
   ```
3. **MLflow UI**:
   ```bash
   open http://localhost:5000
   ```

## Следующие шаги
- Настроить GitHub Actions для CI/CD.
- Добавить мониторинг с Prometheus/Grafana.
- Проверить зависимости: `pip install pytest-qt pyinstaller`.