# Шаг 1.3: Реализация хранения данных (DatabaseManager)

## Введение
Этот документ описывает реализацию модуля хранения данных (`DatabaseManager`) для локального сохранения и извлечения данных приложения (котировки, портфель, транзакции, логи) с использованием DuckDB. Модуль следует принципам модульности из `ModularityConcept.md`: чёткий контракт (ABC + pydantic), независимость, Dependency Injection (DI) через factory, простота для MVP с хуками для масштабирования. DuckDB выбран за лёгкость, скорость и SQL-совместимость, что упрощает оффлайн-режим и миграцию на другие базы (например, PostgreSQL) в будущем.

**Цели шага**:
- Создать `DatabaseManager` для работы с DuckDB.
- Определить таблицы: `quotes`, `portfolio`, `transactions`, `logs`.
- Реализовать контракт через ABC (`DatabaseInterface`) с методами `save` и `load`.
- Использовать pydantic для валидации данных.
- Добавить тесты (`pytest`) с mock-данными.
- Обеспечить логирование и обработку ошибок.
- Подготовить к масштабированию (хуки для замены хранилища).

**Место в архитектуре**:
- Модуль: `src/data/database_manager.py`.
- Зависимости: `duckdb`, `pydantic`, `src/core/models.py`, `src/core/logging.py`, `src/core/exceptions.py`.
- Интеграция: `DatabaseManager` инжектируется в `MainWindow`, `DataProvider`, `Aggregator` через DI.

## Требования
- **Хранилище**: DuckDB (локальная файловая база, `data/app.db`).
- **Таблицы**:
  - `quotes`: Котировки (ticker, date, open, close, volume).
  - `portfolio`: Позиции (ticker, quantity, purchase_price, purchase_date).
  - `transactions`: Сделки (ticker, action, quantity, price, date).
  - `logs`: Логи (timestamp, category, message).
- **Контракт**: `save(data: List[Model])` и `load(query: str) -> List[Model]` с pydantic моделями.
- **Оффлайн-режим**: Все данные сохраняются локально, доступны без интернета.
- **Ошибки**: Кастомные исключения (`DatabaseError`), логи в `logs/app_YYYYMMDD.log`.
- **Тесты**: Unit-тесты с mock-данными, coverage >80%.
- **Масштаб**: Хук для замены DuckDB на PostgreSQL/REST.

## Контракт модуля
Модуль реализует `DatabaseInterface` с методами для сохранения и извлечения данных. Вход/выход — через pydantic модели для типизации и валидации.

### Абстрактный класс
```python
from abc import ABC, abstractmethod
from typing import List
from pydantic import BaseModel

class DatabaseInterface(ABC):
    @abstractmethod
    def save(self, data: List[BaseModel], table: str) -> None:
        """Сохраняет данные в указанную таблицу.

        Args:
            data: Список pydantic моделей (Quote, PortfolioPosition и т.д.).
            table: Имя таблицы (quotes, portfolio, transactions, logs).

        Raises:
            DatabaseError: Если ошибка сохранения.
        """
        pass

    @abstractmethod
    def load(self, query: str, model: type[BaseModel]) -> List[BaseModel]:
        """Извлекает данные по SQL-запросу и возвращает список pydantic моделей.

        Args:
            query: SQL-запрос (например, 'SELECT * FROM quotes WHERE ticker = ?').
            model: Тип pydantic модели (Quote, PortfolioPosition и т.д.).

        Returns:
            List[BaseModel]: Список данных в формате pydantic модели.

        Raises:
            DatabaseError: Если ошибка запроса.
        """
        pass
```

### Pydantic модели
Модели определены в `src/core/models.py` (частично из Шага 1.1). Для Шага 1.3 добавляем недостающие:

```python
from pydantic import BaseModel
from datetime import date, datetime
from typing import Literal

class Quote(BaseModel):
    """Котировка акции."""
    ticker: str
    date: date
    open: float
    close: float
    volume: int

class PortfolioPosition(BaseModel):
    """Позиция в портфеле."""
    ticker: str
    quantity: int
    purchase_price: float
    purchase_date: date

class Transaction(BaseModel):
    """Транзакция (покупка/продажа)."""
    ticker: str
    action: Literal["buy", "sell"]
    quantity: int
    price: float
    date: date

class Log(BaseModel):
    """Запись лога."""
    timestamp: datetime
    category: str  # Например, 'data', 'error', 'analyzer'
    message: str
```

**Правила для моделей**:
- Поля: Обязательные — required, опциональные — `None`.
- Валидация: Базовая (например, `quantity > 0`, `price >= 0`).
- Сериализация: Автоматическая через pydantic (JSON, CSV).

## Реализация DatabaseManager
Модуль `DatabaseManager` реализует `DatabaseInterface`, используя DuckDB для локального хранения.

### Код
```python
# src/data/database_manager.py
"""Модуль для работы с локальной базой данных DuckDB."""

import duckdb
from typing import List, Type
from pydantic import BaseModel
from src.core.exceptions import DatabaseError
from src.core.logging import setup_logging

class DatabaseManager(DatabaseInterface):
    def __init__(self, db_path: str = "data/app.db"):
        """Инициализация DatabaseManager.

        Args:
            db_path: Путь к файлу DuckDB (data/app.db).
        """
        self.logger = setup_logging()
        self.db_path = db_path
        self._init_tables()

    def _init_tables(self) -> None:
        """Создаёт таблицы в DuckDB, если они не существуют."""
        try:
            with duckdb.connect(self.db_path) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS quotes (
                        ticker VARCHAR,
                        date DATE,
                        open DOUBLE,
                        close DOUBLE,
                        volume INTEGER
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS portfolio (
                        ticker VARCHAR,
                        quantity INTEGER,
                        purchase_price DOUBLE,
                        purchase_date DATE
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS transactions (
                        ticker VARCHAR,
                        action VARCHAR,
                        quantity INTEGER,
                        price DOUBLE,
                        date DATE
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS logs (
                        timestamp TIMESTAMP,
                        category VARCHAR,
                        message VARCHAR
                    )
                """)
                self.logger.info("[database] Таблицы инициализированы")
        except Exception as e:
            self.logger.error(f"[database] Ошибка инициализации таблиц: {str(e)}")
            raise DatabaseError(f"Не удалось инициализировать таблицы: {str(e)}")

    def save(self, data: List[BaseModel], table: str) -> None:
        """Сохраняет данные в указанную таблицу.

        Args:
            data: Список pydantic моделей.
            table: Имя таблицы (quotes, portfolio, transactions, logs).

        Raises:
            DatabaseError: Если ошибка сохранения.
        """
        if not data:
            self.logger.info(f"[database] Нет данных для сохранения в {table}")
            return
        try:
            with duckdb.connect(self.db_path) as conn:
                # Преобразуем pydantic модели в список словарей
                data_dicts = [item.dict() for item in data]
                # Используем pandas для вставки (упрощает работу с DuckDB)
                import pandas as pd
                df = pd.DataFrame(data_dicts)
                conn.register("temp_table", df)
                conn.execute(f"INSERT INTO {table} SELECT * FROM temp_table")
                self.logger.info(f"[database] Сохранено {len(data)} записей в {table}")
        except Exception as e:
            self.logger.error(f"[database] Ошибка сохранения в {table}: {str(e)}")
            raise DatabaseError(f"Ошибка сохранения в {table}: {str(e)}")

    def load(self, query: str, model: Type[BaseModel]) -> List[BaseModel]:
        """Извлекает данные по SQL-запросу и возвращает pydantic модели.

        Args:
            query: SQL-запрос (например, 'SELECT * FROM quotes WHERE ticker = ?').
            model: Тип pydantic модели (Quote, PortfolioPosition и т.д.).

        Returns:
            List[BaseModel]: Список данных в формате pydantic модели.
        """
        try:
            with duckdb.connect(self.db_path) as conn:
                result = conn.execute(query).fetchall()
                columns = [desc[0] for desc in conn.description]
                data_dicts = [dict(zip(columns, row)) for row in result]
                data = [model(**item) for item in data_dicts]
                self.logger.info(f"[database] Загружено {len(data)} записей по запросу: {query[:50]}...")
                return data
        except Exception as e:
            self.logger.error(f"[database] Ошибка загрузки: {str(e)}")
            raise DatabaseError(f"Ошибка выполнения запроса: {str(e)}")
```

### Схемы таблиц
- **quotes**:
  ```sql
  CREATE TABLE quotes (
      ticker VARCHAR,          -- Тикер (например, SBER)
      date DATE,              -- Дата котировки
      open DOUBLE,            -- Цена открытия
      close DOUBLE,           -- Цена закрытия
      volume INTEGER          -- Объём торгов
  )
  ```
- **portfolio**:
  ```sql
  CREATE TABLE portfolio (
      ticker VARCHAR,          -- Тикер
      quantity INTEGER,        -- Количество акций
      purchase_price DOUBLE,   -- Цена покупки
      purchase_date DATE       -- Дата покупки
  )
  ```
- **transactions**:
  ```sql
  CREATE TABLE transactions (
      ticker VARCHAR,          -- Тикер
      action VARCHAR,          -- Действие (buy/sell)
      quantity INTEGER,        -- Количество
      price DOUBLE,            -- Цена сделки
      date DATE                -- Дата сделки
  )
  ```
- **logs**:
  ```sql
  CREATE TABLE logs (
      timestamp TIMESTAMP,     -- Время записи
      category VARCHAR,        -- Категория (data, error, analyzer)
      message VARCHAR          -- Сообщение
  )
```

## Интеграция с другими модулями
- **DataProvider**: Вызывает `DatabaseManager.save(quotes, "quotes")` для сохранения котировок.
- **MainWindow**: Использует `DatabaseManager.load("SELECT * FROM portfolio", PortfolioPosition)` для отображения портфеля.
- **Aggregator**: Сохраняет логи через `DatabaseManager.save(logs, "logs")`.
- **DI**: `DatabaseManager` инжектируется через factory:
  ```python
  # src/core/config.py
  def get_database_manager() -> DatabaseInterface:
      return DatabaseManager(db_path="data/app.db")
  ```

## Тестирование
Тесты в `tests/test_database_manager.py` проверяют сохранение/загрузку и обработку ошибок.

```python
import pytest
from src.data.database_manager import DatabaseManager
from src.core.models import Quote
from src.core.exceptions import DatabaseError
from datetime import date

@pytest.fixture
def db_manager():
    return DatabaseManager(db_path=":memory:")  # In-memory DuckDB для тестов

def test_save_and_load_quotes(db_manager):
    quotes = [
        Quote(ticker="SBER", date=date(2025, 10, 15), open=300.0, close=310.0, volume=1000),
        Quote(ticker="GAZP", date=date(2025, 10, 15), open=150.0, close=155.0, volume=500)
    ]
    db_manager.save(quotes, "quotes")
    loaded = db_manager.load("SELECT * FROM quotes WHERE ticker = 'SBER'", Quote)
    assert len(loaded) == 1
    assert loaded[0].ticker == "SBER"
    assert loaded[0].close == 310.0

def test_save_empty_data(db_manager):
    db_manager.save([], "quotes")  # Не должно вызвать ошибку
    loaded = db_manager.load("SELECT * FROM quotes", Quote)
    assert len(loaded) == 0

def test_load_invalid_query(db_manager):
    with pytest.raises(DatabaseError):
        db_manager.load("SELECT * FROM nonexistent", Quote)
```

## Логирование
- Логи сохраняются в `logs/app_YYYYMMDD.log` и в таблице `logs`.
- Категории: `database`, `error`.
- Пример:
  ```
  2025-10-20 18:30: [database] Сохранено 2 записей в quotes
  2025-10-20 18:31: [error] Ошибка загрузки: Table not found
  ```

## Обработка ошибок
- Кастомное исключение:
  ```python
  # src/core/exceptions.py
  class DatabaseError(Exception):
      """Ошибка работы с базой данных."""
      pass
  ```
- Fallback: При ошибке сохранения/загрузки логируем и бросаем `DatabaseError`.

## Масштабируемость
- **Замена хранилища**: Реализовать новый подкласс `DatabaseInterface` (например, `PostgresDatabase`) с тем же контрактом.
- **Хук для async**: В будущем добавить `async def save_async` и `async def load_async` для asyncio.
- **Микро-сервисы**: Переход на REST (FastAPI) с JSON сериализацией pydantic моделей.
- **Схемы**: Таблицы совместимы с SQL (PostgreSQL, SQLite).

## Следующие шаги
- Интегрировать `DatabaseManager` в `DataProvider` (Шаг 1.2).
- Реализовать `NewsAnalyzer` (Шаг 1.4).
- Проверить зависимости: `pip install duckdb pandas`.