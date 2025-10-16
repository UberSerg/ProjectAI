# Step1.2-DataProviders.md: Универсальный API (DataProvider)

## Цель
Реализовать универсальный API для получения финансовых данных (котировок) с использованием абстрактного базового класса (`DataProvider`) и конкретных реализаций (`MoexProvider`, `FallbackProvider` с yfinance). API возвращает данные в формате `List[Quote]` (pydantic-модель из `Step1.1-SetupAndModels.md`), поддерживает оффлайн-режим через DuckDB (подготовка к Шагу 1.3), обеспечивает логирование и тестирование (unit, integration, coverage >80%). Реализация соответствует модульному подходу (`ModularityConcept.md`) с Dependency Injection (DI) и хуками для масштабируемости (asyncio, Tinkoff API).

## Действия
1. **Определить ABC `DataProvider`**:
   - Создать интерфейс `DataProvider` с методом `fetch_quotes(tickers, start_date, end_date) -> List[Quote]`.
   - Реализовать в `src/data/providers.py`.
2. **Реализовать `MoexProvider`**:
   - Использовать MOEX ISS API для получения котировок (OHLCV: open, high, low, close, volume).
   - Обрабатывать ошибки (HTTP 503, rate limits) с fallback на `FallbackProvider`.
3. **Реализовать `FallbackProvider`**:
   - Использовать yfinance для получения котировок, если MOEX API недоступен.
   - Валидировать данные через pydantic (`Quote`).
4. **Настроить DI**:
   - Добавить factory в `src/core/config.py` для выбора провайдера (`moex` или `yfinance`).
   - Поддержка `config.yaml` для переключения провайдеров.
5. **Логирование**:
   - Использовать `setup_logging` из `src/core/logging_setup.py`.
   - Логировать запросы, ошибки, fallback в `logs/app_YYYYMMDD.log`.
6. **Тестирование**:
   - Unit-тесты: Проверка `fetch_quotes` с mock-данными.
   - Integration-тесты: Проверка контракта `List[Quote]` и fallback.
   - Coverage: >80% с `pytest-cov`.
7. **Документировать и коммитить**:
   - Commit: `git commit -m "feat: add DataProvider and MoexProvider"`.
   - Ветка: `feature/phase1-dataproviders`.

## Код
### 1. DataProvider и реализации
**src/data/providers.py**:
```python
from abc import ABC, abstractmethod
from typing import List
from datetime import date
import requests
import yfinance as yf
import pandas as pd
import logging
from src.core.models import Quote
from src.core.logging_setup import setup_logging

logger = setup_logging()

class DataProvider(ABC):
    """Абстрактный интерфейс для получения финансовых данных."""
    @abstractmethod
    def fetch_quotes(self, tickers: List[str], start_date: date, end_date: date) -> List[Quote]:
        """Получает котировки для указанных тикеров за период.

        Args:
            tickers: Список тикеров (e.g., ['SBER', 'GAZP']).
            start_date: Начальная дата.
            end_date: Конечная дата.

        Returns:
            List[Quote]: Список котировок в формате pydantic.
        """
        pass

class MoexProvider(DataProvider):
    """Провайдер данных с MOEX ISS API."""
    def fetch_quotes(self, tickers: List[str], start_date: date, end_date: date) -> List[Quote]:
        """Получает котировки с MOEX ISS API.

        Args:
            tickers: Список тикеров.
            start_date: Начальная дата.
            end_date: Конечная дата.

        Returns:
            List[Quote]: Котировки в формате pydantic.

        Raises:
            ProcessingError: Если API недоступен или данные некорректны.
        """
        quotes = []
        base_url = "http://iss.moex.com/iss/history/engines/stock/markets/shares/boards/TQBR/securities"
        for ticker in tickers:
            url = f"{base_url}/{ticker}/candles.json?from={start_date}&till={end_date}&interval=24"
            try:
                logger.info(f"[data] Fetching MOEX data for {ticker}")
                response = requests.get(url, timeout=10)
                response.raise_for_status()
                data = response.json().get("history", {}).get("data", [])
                for row in data:
                    quote = Quote(
                        ticker=ticker,
                        date=date.fromisoformat(row[1]),
                        open=row[2],
                        high=row[3],
                        low=row[4],
                        close=row[5],
                        volume=int(row[6])
                    )
                    quotes.append(quote)
            except (requests.RequestException, ValueError) as e:
                logger.error(f"[data] MOEX API failed for {ticker}: {str(e)}, switching to fallback")
                return FallbackProvider().fetch_quotes(tickers, start_date, end_date)
        logger.info(f"[data] Fetched {len(quotes)} quotes from MOEX for {tickers}")
        return quotes

class FallbackProvider(DataProvider):
    """Провайдер данных с yfinance как fallback."""
    def fetch_quotes(self, tickers: List[str], start_date: date, end_date: date) -> List[Quote]:
        """Получает котировки с yfinance.

        Args:
            tickers: Список тикеров (e.g., ['SBER.ME', 'GAZP.ME']).
            start_date: Начальная дата.
            end_date: Конечная дата.

        Returns:
            List[Quote]: Котировки в формате pydantic.
        """
        quotes = []
        for ticker in [f"{t}.ME" for t in tickers]:  # MOEX tickers require .ME for yfinance
            try:
                logger.info(f"[data] Fetching yfinance data for {ticker}")
                df = yf.download(ticker, start=start_date, end=end_date, interval="1d")
                for index, row in df.iterrows():
                    quote = Quote(
                        ticker=ticker.replace(".ME", ""),
                        date=index.date(),
                        open=row["Open"],
                        high=row["High"],
                        low=row["Low"],
                        close=row["Close"],
                        volume=int(row["Volume"])
                    )
                    quotes.append(quote)
            except Exception as e:
                logger.error(f"[data] yfinance failed for {ticker}: {str(e)}")
                continue
        logger.info(f"[data] Fetched {len(quotes)} quotes from yfinance for {tickers}")
        return quotes

class ProcessingError(Exception):
    """Исключение для ошибок обработки данных."""
    pass
```

### 2. Dependency Injection
**src/core/config.py**:
```python
from src.data.providers import DataProvider, MoexProvider, FallbackProvider
from typing import Dict

def get_data_provider(provider_type: str) -> DataProvider:
    """Фабрика для получения экземпляра DataProvider.

    Args:
        provider_type: Тип провайдера ('moex' или 'yfinance').

    Returns:
        DataProvider: Экземпляр провайдера данных.

    Raises:
        ValueError: Если тип провайдера неизвестен.
    """
    providers: Dict[str, type] = {
        "moex": MoexProvider,
        "yfinance": FallbackProvider
    }
    if provider_type not in providers:
        raise ValueError(f"Unknown provider type: {provider_type}")
    return providers[provider_type]()
```

**config.yaml** (создать в корне проекта):
```yaml
data_provider: moex
```

### 3. Тесты
**tests/test_providers.py**:
```python
import pytest
from src.data.providers import DataProvider, MoexProvider, FallbackProvider
from src.core.models import Quote
from datetime import date, datetime
from unittest.mock import patch
import pandas as pd

@pytest.fixture
def mock_moex_response():
    """Mock ответ MOEX API."""
    return {
        "history": {
            "data": [
                [0, "2025-10-15", 300.0, 315.0, 295.0, 310.0, 1000],
                [1, "2025-10-14", 295.0, 305.0, 290.0, 300.0, 800]
            ]
        }
    }

@pytest.fixture
def mock_yfinance_data():
    """Mock данные yfinance."""
    return pd.DataFrame({
        "Open": [300.0, 295.0],
        "High": [315.0, 305.0],
        "Low": [295.0, 290.0],
        "Close": [310.0, 300.0],
        "Volume": [1000, 800]
    }, index=[pd.Timestamp("2025-10-15"), pd.Timestamp("2025-10-14")])

def test_moex_provider(mock_moex_response):
    """Тестирует MoexProvider с mock-данными."""
    with patch("requests.get") as mock_get:
        mock_get.return_value.json.return_value = mock_moex_response
        provider = MoexProvider()
        quotes = provider.fetch_quotes(["SBER"], date(2025, 10, 14), date(2025, 10, 15))
        assert len(quotes) == 2
        assert isinstance(quotes[0], Quote)
        assert quotes[0].ticker == "SBER"
        assert quotes[0].close == 310.0
        assert quotes[0].date == date(2025, 10, 15)

def test_fallback_provider(mock_yfinance_data):
    """Тестирует FallbackProvider с mock-данными."""
    with patch("yfinance.download") as mock_download:
        mock_download.return_value = mock_yfinance_data
        provider = FallbackProvider()
        quotes = provider.fetch_quotes(["SBER"], date(2025, 10, 14), date(2025, 10, 15))
        assert len(quotes) == 2
        assert isinstance(quotes[0], Quote)
        assert quotes[0].ticker == "SBER"
        assert quotes[0].close == 310.0
        assert quotes[0].date == date(2025, 10, 15)

def test_moex_fallback_on_error(mock_moex_response, mock_yfinance_data):
    """Тестирует переход на FallbackProvider при сбое MOEX."""
    with patch("requests.get") as mock_get, patch("yfinance.download") as mock_download:
        mock_get.side_effect = requests.RequestException("HTTP 503")
        mock_download.return_value = mock_yfinance_data
        provider = MoexProvider()
        quotes = provider.fetch_quotes(["SBER"], date(2025, 10, 14), date(2025, 10, 15))
        assert len(quotes) == 2
        assert quotes[0].ticker == "SBER"
        assert quotes[0].close == 310.0

def test_data_provider_contract():
    """Проверяет контракт DataProvider."""
    provider = MoexProvider()
    assert isinstance(provider, DataProvider)
    assert hasattr(provider, "fetch_quotes")
```

Запуск тестов:
```bash
pytest tests/test_providers.py --cov=src/data --cov-report=html
```

### 4. Commit
```bash
git add src/data/providers.py src/core/config.py tests/test_providers.py config.yaml
git commit -m "feat: add DataProvider and MoexProvider"
git branch feature/phase1-dataproviders
```

## Масштабируемость
- **Async**: Добавить `async def fetch_quotes` с `aiohttp` для реал-тайм (Фаза 4).
- **Tinkoff API**: Реализовать `TinkoffProvider` через DI (`config.yaml: data_provider: tinkoff`).
- **Cloud**: Хранить котировки в PostgreSQL/S3 (Шаг 1.3).
- **Caching**: Использовать DuckDB для оффлайн-режима (Шаг 1.3).

## Проблемы и решения
- **Проблема**: MOEX API возвращает HTTP 503 или rate limit.
  - Решение: Fallback на yfinance, логировать ошибку.
- **Проблема**: yfinance может не поддерживать все MOEX тикеры.
  - Решение: Проверять тикеры в `config.yaml` (e.g., `tickers: ['SBER', 'GAZP']`).
- **Проблема**: Низкий coverage.
  - Решение: Добавить тесты для edge cases (пустой ответ API, некорректные даты).

## Уточняющие вопросы
- Какие тикеры использовать для тестов (e.g., SBER, GAZP)?
- Есть ли API ключ для MOEX или Tinkoff?
- Нужен ли `TinkoffProvider` в этом шаге?
- Какие даты для тестов (e.g., 2025-10-01 до 2025-10-15)?
- Логировать в консоль дополнительно к файлам?

## Следующие шаги
- Перейти к Шагу 1.3: Реализовать `DatabaseManager` (`docs/specs/Step1.3-DatabaseManager.md`).
- Проверить `requirements.txt` на новые зависимости (e.g., `yfinance`, `aiohttp`).
- Добавить тикеры в `config.yaml` для продакшена.