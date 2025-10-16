# Step1.1-SetupAndModels.md: Настройка проекта и типизация данных

## Цель
Настроить окружение для разработки desktop-приложения для среднесрочного инвестирования на MOEX с AI-советником. Создать структуру репозитория, установить зависимости, реализовать базовые pydantic-модели (`Quote`, `Recommendation`, `PortfolioPosition`, `Transaction`, `LogEntry`, `AnalyzerInput`, `AnalyzerOutput`) для типизации данных и написать тесты (unit, coverage >80%). Этот шаг обеспечивает основу для модульной архитектуры, соответствующей `ModularityConcept.md`, с хуками для масштабируемости (ORM, новые поля).

## Действия
1. **Создать структуру репозитория**:
   - Папки: `src/`, `tests/`, `docs/specs/`, `logs/`, `models/`, `scripts/`.
   - Инициализировать Git: `git init`, создать `.gitignore`.
2. **Установить Python и зависимости**:
   - Python 3.9+.
   - Создать виртуальное окружение: `python -m venv venv`.
   - Установить зависимости: `pip install pydantic pytest requests pandas duckdb pyqt5 scikit-learn pandas_ta feedparser schedule joblib`.
   - Сохранить: `pip freeze > requirements.txt`.
3. **Реализовать pydantic-модели**:
   - Файл: `src/core/models.py`.
   - Модели: `Quote`, `Recommendation`, `PortfolioPosition`, `Transaction`, `LogEntry`, `AnalyzerInput`, `AnalyzerOutput`.
   - Валидация: Проверки на положительные цены, корректные действия, диапазоны уверенности.
4. **Настроить логирование**:
   - Файл: `src/core/logging_setup.py`.
   - Формат: `%(asctime)s [%(levelname)s] [%(module)s] %(message)s`.
   - Ротация: Ежедневно в `logs/app_YYYYMMDD.log`.
5. **Написать тесты**:
   - Файл: `tests/test_models.py`.
   - Unit-тесты: Проверка валидации pydantic, корректности полей.
   - Coverage: >80% с `pytest-cov`.
6. **Документировать и коммитить**:
   - Commit: `git commit -m "feat: setup project and pydantic models"`.
   - Ветка: `feature/phase1-setup`.
   - Обновить этот файл с кодом и тестами.

## Код
### 1. Структура репозитория
```bash
investment_advisor/
├── src/
│   ├── core/
│   │   ├── __init__.py
│   │   ├── models.py
│   │   └── logging_setup.py
│   ├── data/
│   │   └── __init__.py
│   ├── analysis/
│   │   └── __init__.py
│   ├── ai/
│   │   └── __init__.py
│   ├── ui/
│   │   └── __init__.py
├── tests/
│   ├── __init__.py
│   └── test_models.py
├── docs/
│   └── specs/
│       └── Step1.1-SetupAndModels.md
├── logs/
│   └── .gitignore
├── models/
│   └── .gitignore
├── scripts/
│   └── __init__.py
├── requirements.txt
└── .gitignore
```

**.gitignore**:
```
venv/
__pycache__/
*.pyc
logs/
models/
*.db
```

### 2. Зависимости
**requirements.txt**:
```
pydantic>=2.0
pytest>=7.0
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
```

Установка:
```bash
python -m venv venv
source venv/bin/activate  # или venv\Scripts\activate на Windows
pip install -r requirements.txt
```

### 3. Pydantic-модели
**src/core/models.py**:
```python
from pydantic import BaseModel, validator
from datetime import date, datetime
from typing import Literal, Dict, List, Optional

class Quote(BaseModel):
    """Котировка актива за день."""
    ticker: str
    date: date
    open: float
    close: float
    high: float
    low: float
    volume: int

    @validator('open', 'close', 'high', 'low')
    def check_positive(cls, v):
        if v <= 0:
            raise ValueError("Price must be positive")
        return v

    @validator('volume')
    def check_non_negative(cls, v):
        if v < 0:
            raise ValueError("Volume must be non-negative")
        return v

class Recommendation(BaseModel):
    """Рекомендация по активу."""
    ticker: str
    action: Literal["buy", "sell", "hold"]
    target_price: float
    stop_loss: float
    horizon: str  # e.g., "4 weeks"
    confidence: float  # 0..1
    reason: str
    timestamp: datetime

    @validator('confidence')
    def check_confidence(cls, v):
        if not 0 <= v <= 1:
            raise ValueError("Confidence must be between 0 and 1")
        return v

    @validator('target_price', 'stop_loss')
    def check_positive(cls, v):
        if v <= 0:
            raise ValueError("Price must be positive")
        return v

class PortfolioPosition(BaseModel):
    """Позиция в портфеле."""
    ticker: str
    quantity: int
    purchase_price: float
    purchase_date: date
    current_price: Optional[float] = None
    return_pct: Optional[float] = None  # Доходность в %

    @validator('quantity', 'purchase_price')
    def check_positive(cls, v):
        if v <= 0:
            raise ValueError("Quantity and purchase price must be positive")
        return v

class Transaction(BaseModel):
    """Транзакция в портфеле."""
    ticker: str
    action: Literal["buy", "sell"]
    quantity: int
    price: float
    date: date
    timestamp: datetime

    @validator('quantity', 'price')
    def check_positive(cls, v):
        if v <= 0:
            raise ValueError("Quantity and price must be positive")
        return v

class LogEntry(BaseModel):
    """Запись лога."""
    timestamp: datetime
    level: Literal["INFO", "WARNING", "ERROR"]
    module: str
    message: str

class AnalyzerInput(BaseModel):
    """Входные данные для анализаторов."""
    urls: List[str] = []
    tickers: List[str]

    @validator('tickers')
    def check_tickers(cls, v):
        if not v:
            raise ValueError("Tickers list cannot be empty")
        return v

class AnalyzerOutput(BaseModel):
    """Выходные данные анализаторов."""
    score: float  # -1..1
    confidence: float  # 0..1
    reason: str
    metadata: Dict[str, str] = {}

    @validator('score')
    def check_score(cls, v):
        if not -1 <= v <= 1:
            raise ValueError("Score must be between -1 and 1")
        return v

    @validator('confidence')
    def check_confidence(cls, v):
        if not 0 <= v <= 1:
            raise ValueError("Confidence must be between 0 and 1")
        return v
```

### 4. Логирование
**src/core/logging_setup.py**:
```python
import logging
from logging.handlers import TimedRotatingFileHandler
import os
from datetime import datetime

def setup_logging() -> logging.Logger:
    """Настраивает логирование с ротацией по дням.

    Returns:
        logging.Logger: Логгер с настроенным форматом и ротацией.
    """
    logger = logging.getLogger("InvestmentAdvisor")
    logger.setLevel(logging.INFO)

    if not logger.handlers:
        os.makedirs("logs", exist_ok=True)
        handler = TimedRotatingFileHandler(
            filename=f"logs/app_{datetime.now().strftime('%Y%m%d')}.log",
            when="midnight",
            interval=1,
            backupCount=30
        )
        formatter = logging.Formatter("%(asctime)s [%(levelname)s] [%(module)s] %(message)s")
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger
```

### 5. Тесты
**tests/test_models.py**:
```python
import pytest
from src.core.models import Quote, Recommendation, PortfolioPosition, Transaction, LogEntry, AnalyzerInput, AnalyzerOutput
from datetime import date, datetime

def test_quote_validation():
    """Тестирует валидацию модели Quote."""
    quote = Quote(
        ticker="SBER",
        date=date(2025, 10, 15),
        open=300.0,
        close=310.0,
        high=315.0,
        low=295.0,
        volume=1000
    )
    assert quote.close == 310.0
    with pytest.raises(ValueError, match="Price must be positive"):
        Quote(ticker="SBER", date=date(2025, 10, 15), open=-1.0, close=310.0, high=315.0, low=295.0, volume=1000)
    with pytest.raises(ValueError, match="Volume must be non-negative"):
        Quote(ticker="SBER", date=date(2025, 10, 15), open=300.0, close=310.0, high=315.0, low=295.0, volume=-100)

def test_recommendation_validation():
    """Тестирует валидацию модели Recommendation."""
    rec = Recommendation(
        ticker="SBER",
        action="buy",
        target_price=320.0,
        stop_loss=300.0,
        horizon="4 weeks",
        confidence=0.85,
        reason="RSI=75, mentions=10",
        timestamp=datetime(2025, 10, 15, 14, 22)
    )
    assert rec.action == "buy"
    with pytest.raises(ValueError, match="Confidence must be between 0 and 1"):
        Recommendation(
            ticker="SBER",
            action="buy",
            target_price=320.0,
            stop_loss=300.0,
            horizon="4 weeks",
            confidence=1.5,
            reason="RSI=75",
            timestamp=datetime.now()
        )

def test_portfolio_position_validation():
    """Тестирует валидацию модели PortfolioPosition."""
    pos = PortfolioPosition(
        ticker="SBER",
        quantity=100,
        purchase_price=300.0,
        purchase_date=date(2025, 10, 1),
        current_price=315.0,
        return_pct=5.0
    )
    assert pos.quantity == 100
    with pytest.raises(ValueError, match="Quantity and purchase price must be positive"):
        PortfolioPosition(ticker="SBER", quantity=-10, purchase_price=300.0, purchase_date=date(2025, 10, 1))

def test_transaction_validation():
    """Тестирует валидацию модели Transaction."""
    trans = Transaction(
        ticker="SBER",
        action="buy",
        quantity=100,
        price=300.0,
        date=date(2025, 10, 15),
        timestamp=datetime(2025, 10, 15, 14, 22)
    )
    assert trans.price == 300.0
    with pytest.raises(ValueError, match="Quantity and price must be positive"):
        Transaction(ticker="SBER", action="buy", quantity=0, price=300.0, date=date(2025, 10, 15), timestamp=datetime.now())

def test_log_entry():
    """Тестирует модель LogEntry."""
    log = LogEntry(
        timestamp=datetime(2025, 10, 15, 14, 22),
        level="INFO",
        module="core",
        message="Setup completed"
    )
    assert log.module == "core"

def test_analyzer_input_validation():
    """Тестирует валидацию модели AnalyzerInput."""
    input_data = AnalyzerInput(urls=["https://example.com"], tickers=["SBER", "GAZP"])
    assert input_data.tickers == ["SBER", "GAZP"]
    with pytest.raises(ValueError, match="Tickers list cannot be empty"):
        AnalyzerInput(urls=["https://example.com"], tickers=[])

def test_analyzer_output_validation():
    """Тестирует валидацию модели AnalyzerOutput."""
    output = AnalyzerOutput(score=0.7, confidence=0.85, reason="RSI=75", metadata={"source": "RSS"})
    assert output.score == 0.7
    with pytest.raises(ValueError, match="Score must be between -1 and 1"):
        AnalyzerOutput(score=1.5, confidence=0.85, reason="RSI=75")
    with pytest.raises(ValueError, match="Confidence must be between 0 and 1"):
        AnalyzerOutput(score=0.7, confidence=1.5, reason="RSI=75")
```

Запуск тестов:
```bash
pytest tests/test_models.py --cov=src/core --cov-report=html
```

### 6. Commit
```bash
git init
git add .
git commit -m "feat: setup project and pydantic models"
git branch feature/phase1-setup
```

## Масштабируемость
- **Модели**: Pydantic-модели готовы для ORM (SQLAlchemy) — добавляйте optional поля (e.g., `sentiment: Optional[float]`).
- **Логирование**: Переход на ELK Stack для продакшена.
- **Тестирование**: Интеграционные тесты с DuckDB в Шаге 1.3.
- **Git**: CI/CD через GitHub Actions (pytest, black) в Шаге 1.2.

## Проблемы и решения
- **Проблема**: Отсутствие API ключей для MOEX/yfinance.
  - Решение: Использовать публичные данные или mock для тестов.
- **Проблема**: Низкий coverage в тестах.
  - Решение: Добавить тесты для всех валидаторов pydantic.
- **Проблема**: Конфликты зависимостей.
  - Решение: Фиксировать версии в `requirements.txt`.

## Уточняющие вопросы
- Какие тикеры использовать для тестов (e.g., SBER, GAZP)?
- Нужно ли добавить другие модели (e.g., `NewsMention`)?
- Есть ли специфичные версии библиотек (e.g., `pydantic==2.5.0`)?
- Логировать в консоль дополнительно к файлам?

## Следующие шаги
- Перейти к Шагу 1.2: Реализовать `DataProvider` (`docs/specs/Step1.2-DataProviders.md`).
- Проверить `requirements.txt` на конфликты перед следующим шагом.
- Обновить `.gitignore`, если появятся новые файлы (e.g., DuckDB).