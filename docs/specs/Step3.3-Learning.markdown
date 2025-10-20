# Шаг 3.3: Самообучение

## Введение
Этот документ описывает реализацию модуля самообучения (`Learner`) для анализа ошибок предсказаний `Recommender`, повторного обучения модели (`RandomForestClassifier`) и проведения A/B-тестирования RandomForest против SVM (`SVC` из scikit-learn). Модуль следует принципам модульности из `ModularityConcept.md`: чёткий контракт через `LearnerInterface`, pydantic модели, Dependency Injection (DI) через factory, простота для MVP с хуками для масштабирования. Модуль анализирует сделки из `paper_trades`, обновляет модель на основе ошибок и сравнивает производительность двух алгоритмов. Результаты отображаются в UI (`MainWindow`) на вкладке "Обучение".

**Цели шага**:
- Реализовать `Learner` с методами для анализа ошибок, переобучения и A/B-тестирования.
- Использовать pydantic модели для входа (`LearningInput`) и выхода (`LearningResult`).
- Анализировать сделки из `paper_trades` и котировки из `quotes` через `DatabaseManager`.
- Интегрировать с `Aggregator` для генерации исторических рекомендаций.
- Сравнить RandomForest и SVM по метрикам (Win Rate, Accuracy).
- Добавить тесты (`pytest`) с mock-данными.
- Реализовать логирование и обработку ошибок.
- Подготовить к масштабированию (например, MLflow, LSTM).

**Место в архитектуре**:
- Модуль: `src/learning/learner.py`.
- Зависимости: `pandas`, `scikit-learn`, `pydantic`, `src/core/models.py`, `src/core/interfaces.py`, `src/core/logging.py`, `src/core/exceptions.py`, `src/ai/aggregator.py`, `src/data/database_manager.py`.
- Интеграция: `Learner` инжектируется в `MainWindow` через DI.

## Требования
- **Источник данных**: Сделки из `paper_trades`, котировки из `quotes` (DuckDB), рекомендации от `Aggregator`.
- **Анализ ошибок**: Определение ложных сигналов (buy/sell с убытком >5%).
- **Переобучение**: Обновление `RandomForestClassifier` на основе новых данных.
- **A/B-тестирование**: Сравнение RandomForest и SVM по Win Rate и Accuracy.
- **Контракт**:
  - Вход: `LearningInput` (диапазон дат, тикеры, путь к модели).
  - Выход: `LearningResult` (метрики, лучшие параметры, лучшая модель).
- **Оффлайн-режим**: Данные из DuckDB, fallback при отсутствии данных — пустой результат.
- **Ошибки**: Кастомное исключение (`LearningError`), логи в `logs/app_YYYYMMDD.log`.
- **Тесты**: Unit-тесты с mock-данными (coverage >80%).
- **Масштаб**: Хук для MLflow, LSTM, REST.

## Контракт модуля
Модуль реализует `LearnerInterface`, определяющий методы `analyze_errors`, `retrain`, `run_ab_test`. Используются pydantic модели для входа и выхода.

### Абстрактный класс
```python
from abc import ABC, abstractmethod
from typing import Dict, List
from pydantic import BaseModel
from datetime import date

class LearningInput(BaseModel):
    """Входные данные для самообучения."""
    tickers: List[str]  # Список тикеров
    date_range: tuple[date, date]  # Диапазон дат
    model_path: str  # Путь к модели

class LearningResult(BaseModel):
    """Результаты самообучения."""
    win_rate_rf: float  # Win Rate для RandomForest
    accuracy_rf: float  # Accuracy для RandomForest
    win_rate_svm: float  # Win Rate для SVM
    accuracy_svm: float  # Accuracy для SVM
    best_model: str  # Название лучшей модели (rf/svm)
    errors: List[str]  # Список ошибок (ложные сигналы)

class LearnerInterface(ABC):
    @abstractmethod
    def analyze_errors(self, input_data: LearningInput) -> List[str]:
        """Анализирует ошибки предсказаний.

        Args:
            input_data: Входные данные (тикеры, диапазон дат).

        Returns:
            List[str]: Список ложных сигналов.

        Raises:
            LearningError: Если ошибка анализа.
        """
        pass

    @abstractmethod
    def retrain(self, input_data: LearningInput) -> None:
        """Переобучает модель на новых данных.

        Args:
            input_data: Входные данные (тикеры, диапазон дат, путь к модели).

        Raises:
            LearningError: Если ошибка переобучения.
        """
        pass

    @abstractmethod
    def run_ab_test(self, input_data: LearningInput) -> LearningResult:
        """Проводит A/B-тестирование RandomForest vs SVM.

        Args:
            input_data: Входные данные (тикеры, диапазон дат).

        Returns:
            LearningResult: Результаты сравнения моделей.

        Raises:
            LearningError: Если ошибка тестирования.
        """
        pass
```

**Правила для контракта**:
- Методы: `analyze_errors`, `retrain`, `run_ab_test` (sync для MVP).
- Вход: `LearningInput` с тикерами, диапазоном дат, путём к модели.
- Выход: `LearningResult` с метриками (Win Rate, Accuracy) и лучшей моделью.
- Исключения: `LearningError` для ошибок обработки.
- Backward-compatibility: Новые поля в `LearningResult` — optional.

## Реализация Learner
Модуль `Learner` реализует `LearnerInterface`, анализирует ошибки из `paper_trades`, переобучает `RandomForestClassifier` и проводит A/B-тестирование RandomForest против SVM. Для MVP:
- **Анализ ошибок**: Ложные сигналы — сделки с убытком >5%.
- **Переобучение**: Обновление RandomForest на основе данных `paper_trades` и котировок.
- **A/B-тестирование**: Сравнение RandomForest и SVM на исторических данных (Win Rate, Accuracy).
- **Данные**: Сделки из `paper_trades`, котировки из `quotes`, рекомендации от `Aggregator`.

### Код
```python
# src/learning/learner.py
"""Модуль для самообучения и A/B-тестирования."""

import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.svm import SVC
from sklearn.metrics import accuracy_score
from typing import List
from src.core.interfaces import LearnerInterface, LearningInput, LearningResult
from src.core.models import PaperTrade, Quote, Recommendation, AnalyzerInput
from src.core.exceptions import LearningError
from src.core.logging import setup_logging
from src.data.database_manager import DatabaseManager
from src.ai.aggregator import Aggregator
from joblib import load, dump
from datetime import date, timedelta

class Learner(LearnerInterface):
    def __init__(self, aggregator: Aggregator, db_manager: DatabaseManager):
        """Инициализация модуля самообучения.

        Args:
            aggregator: Модуль для получения рекомендаций.
            db_manager: Модуль для доступа к данным.
        """
        self.aggregator = aggregator
        self.db_manager = db_manager
        self.logger = setup_logging()

    def analyze_errors(self, input_data: LearningInput) -> List[str]:
        """Анализирует ошибки предсказаний.

        Args:
            input_data: Входные данные (тикеры, диапазон дат).

        Returns:
            List[str]: Список ложных сигналов.

        Raises:
            LearningError: Если ошибка анализа.
        """
        try:
            self.logger.info(f"[learner] Анализ ошибок для {input_data.tickers}, диапазон {input_data.date_range}")
            trades = self.db_manager.load(
                f"SELECT * FROM paper_trades WHERE ticker IN ({','.join(f"'{t}'" for t in input_data.tickers)}) AND entry_date >= '{input_data.date_range[0]}' AND entry_date <= '{input_data.date_range[1]}'",
                PaperTrade
            )
            errors = []
            for trade in trades:
                if trade.profit and trade.profit < -0.05 * trade.quantity * trade.entry_price:
                    errors.append(f"Ложный сигнал для {trade.ticker} ({trade.entry_date}): убыток {trade.profit:.2f}")
            self.logger.info(f"[learner] Найдено {len(errors)} ошибок")
            return errors
        except Exception as e:
            self.logger.error(f"[learner] Ошибка анализа: {str(e)}")
            raise LearningError(f"Ошибка анализа ошибок: {str(e)}")

    def retrain(self, input_data: LearningInput) -> None:
        """Переобучает модель на новых данных.

        Args:
            input_data: Входные данные (тикеры, диапазон дат, путь к модели).

        Raises:
            LearningError: Если ошибка переобучения.
        """
        try:
            self.logger.info(f"[learner] Переобучение модели для {input_data.tickers}")
            trades = self.db_manager.load(
                f"SELECT * FROM paper_trades WHERE ticker IN ({','.join(f"'{t}'" for t in input_data.tickers)}) AND entry_date >= '{input_data.date_range[0]}' AND entry_date <= '{input_data.date_range[1]}'",
                PaperTrade
            )
            if not trades:
                raise LearningError("Нет данных для переобучения")

            # Собираем фичи и метки
            X, y = [], []
            for trade in trades:
                # Получаем рекомендации для даты входа
                recommendations = self.aggregator.aggregate({
                    'news': AnalyzerInput(urls=['https://ria.ru/rss'], tickers=[trade.ticker]),
                    'technical': AnalyzerInput(tickers=[trade.ticker]),
                    'risk': AnalyzerInput(tickers=[trade.ticker])
                })
                rec = recommendations.get(trade.ticker, Recommendation(signal="hold", target_price=None, stop_loss=None, horizon="4 недели", confidence=0, reason="Нет данных"))
                features = [
                    rec.score if rec.reason != "Нет данных" else 0,
                    rec.confidence,
                    recommendations.get(trade.ticker, {}).get('technical', AnalyzerOutput(score=0, confidence=0, reason="")).score,
                    recommendations.get(trade.ticker, {}).get('technical', AnalyzerOutput(score=0, confidence=0, reason="")).confidence,
                    recommendations.get(trade.ticker, {}).get('risk', AnalyzerOutput(score=0, confidence=0, reason="")).score,
                    recommendations.get(trade.ticker, {}).get('risk', AnalyzerOutput(score=0, confidence=0, reason="")).confidence
                ]
                label = "buy" if trade.profit and trade.profit > 0 else "sell" if trade.profit and trade.profit < 0 else "hold"
                X.append(features)
                y.append(label)

            # Переобучение RandomForest
            model = RandomForestClassifier(n_estimators=100, random_state=42)
            model.fit(X, y)
            dump(model, input_data.model_path)
            self.logger.info(f"[learner] Модель сохранена в {input_data.model_path}")
        except Exception as e:
            self.logger.error(f"[learner] Ошибка переобучения: {str(e)}")
            raise LearningError(f"Ошибка переобучения: {str(e)}")

    def run_ab_test(self, input_data: LearningInput) -> LearningResult:
        """Проводит A/B-тестирование RandomForest vs SVM.

        Args:
            input_data: Входные данные (тикеры, диапазон дат).

        Returns:
            LearningResult: Результаты сравнения моделей.

        Raises:
            LearningError: Если ошибка тестирования.
        """
        try:
            self.logger.info(f"[learner] A/B-тестирование для {input_data.tickers}")
            trades = self.db_manager.load(
                f"SELECT * FROM paper_trades WHERE ticker IN ({','.join(f"'{t}'" for t in input_data.tickers)}) AND entry_date >= '{input_data.date_range[0]}' AND entry_date <= '{input_data.date_range[1]}'",
                PaperTrade
            )
            if not trades:
                return LearningResult(win_rate_rf=0, accuracy_rf=0, win_rate_svm=0, accuracy_svm=0, best_model="none", errors=[])

            # Собираем данные
            X, y_true = [], []
            for trade in trades:
                recommendations = self.aggregator.aggregate({
                    'news': AnalyzerInput(urls=['https://ria.ru/rss'], tickers=[trade.ticker]),
                    'technical': AnalyzerInput(tickers=[trade.ticker]),
                    'risk': AnalyzerInput(tickers=[trade.ticker])
                })
                rec = recommendations.get(trade.ticker, Recommendation(signal="hold", target_price=None, stop_loss=None, horizon="4 недели", confidence=0, reason="Нет данных"))
                features = [
                    rec.score if rec.reason != "Нет данных" else 0,
                    rec.confidence,
                    recommendations.get(trade.ticker, {}).get('technical', AnalyzerOutput(score=0, confidence=0, reason="")).score,
                    recommendations.get(trade.ticker, {}).get('technical', AnalyzerOutput(score=0, confidence=0, reason="")).confidence,
                    recommendations.get(trade.ticker, {}).get('risk', AnalyzerOutput(score=0, confidence=0, reason="")).score,
                    recommendations.get(trade.ticker, {}).get('risk', AnalyzerOutput(score=0, confidence=0, reason="")).confidence
                ]
                label = "buy" if trade.profit and trade.profit > 0 else "sell" if trade.profit and trade.profit < 0 else "hold"
                X.append(features)
                y_true.append(label)

            # RandomForest
            rf_model = RandomForestClassifier(n_estimators=100, random_state=42)
            rf_model.fit(X, y_true)
            y_pred_rf = rf_model.predict(X)
            win_rate_rf = sum(1 for t, p in zip(trades, y_pred_rf) if (p == "buy" and t.profit and t.profit > 0) or (p == "sell" and t.profit and t.profit < 0)) / len(trades) if trades else 0
            accuracy_rf = accuracy_score(y_true, y_pred_rf)

            # SVM
            svm_model = SVC(kernel='rbf', random_state=42)
            svm_model.fit(X, y_true)
            y_pred_svm = svm_model.predict(X)
            win_rate_svm = sum(1 for t, p in zip(trades, y_pred_svm) if (p == "buy" and t.profit and t.profit > 0) or (p == "sell" and t.profit and t.profit < 0)) / len(trades) if trades else 0
            accuracy_svm = accuracy_score(y_true, y_pred_svm)

            # Лучшая модель
            best_model = "rf" if accuracy_rf >= accuracy_svm else "svm"
            if best_model == "rf":
                dump(rf_model, input_data.model_path)
            else:
                dump(svm_model, input_data.model_path)

            errors = self.analyze_errors(input_data)
            result = LearningResult(
                win_rate_rf=win_rate_rf,
                accuracy_rf=accuracy_rf,
                win_rate_svm=win_rate_svm,
                accuracy_svm=accuracy_svm,
                best_model=best_model,
                errors=errors
            )
            self.logger.info(f"[learner] A/B-тест: RF Win Rate={win_rate_rf:.2f}, SVM Win Rate={win_rate_svm:.2f}, Лучшая модель={best_model}")
            return result
        except Exception as e:
            self.logger.error(f"[learner] Ошибка A/B-тестирования: {str(e)}")
            raise LearningError(f"Ошибка A/B-тестирования: {str(e)}")
```

### Пояснения к реализации
- **Анализ ошибок**: Ложные сигналы определяются как сделки с убытком >5% от начальной стоимости.
- **Переобучение**: RandomForest обучается на фичах из `Aggregator` (score/confidence анализаторов) и метках (buy/sell/hold) на основе прибыли сделок.
- **A/B-тестирование**: Сравнивает RandomForest и SVM по Win Rate (доля прибыльных сделок) и Accuracy (совпадение предсказаний с реальными исходами).
- **Данные**: Сделки из `paper_trades`, рекомендации от `Aggregator`, котировки из `quotes`.
- **Ошибки**: Логируются, при сбое возвращается `LearningResult` с нулевыми метриками.
- **Оффлайн-режим**: Используются данные из DuckDB.

## Интеграция с другими модулями
- **Aggregator**: Генерирует рекомендации для анализа ошибок и обучения:
  ```python
  recommendations = aggregator.aggregate({
      'news': AnalyzerInput(urls=['https://ria.ru/rss'], tickers=[trade.ticker]),
      'technical': AnalyzerInput(tickers=[trade.ticker]),
      'risk': AnalyzerInput(tickers=[trade.ticker])
  })
  ```
- **DatabaseManager**: Загружает сделки и котировки:
  ```python
  trades = db_manager.load("SELECT * FROM paper_trades WHERE ticker IN (...)", PaperTrade)
  ```
- **MainWindow**: Отображает `LearningResult` (Win Rate, Accuracy, лучшая модель) на вкладке "Обучение".
- **DI**: `Learner` инжектируется в `MainWindow`:
  ```python
  # src/core/config.py
  def get_learner(db_manager: DatabaseManager) -> LearnerInterface:
      aggregator = Aggregator(analyzers={
          'news': get_analyzer('basic_news', db_manager),
          'technical': get_analyzer('technical', db_manager),
          'risk': get_analyzer('risk', db_manager)
      }, recommender=get_recommender())
      return Learner(aggregator=aggregator, db_manager=db_manager)
  ```

## Тестирование
Тесты в `tests/test_learner.py` проверяют анализ ошибок, переобучение и A/B-тестирование.

```python
import pytest
from unittest.mock import Mock
from src.learning.learner import Learner, LearningInput, LearningResult
from src.core.exceptions import LearningError
from src.core.models import PaperTrade, Recommendation
from datetime import date

@pytest.fixture
def db_manager():
    db = Mock()
    db.load.return_value = [
        PaperTrade(ticker="SBER", entry_date=date(2025, 10, 1), exit_date=date(2025, 10, 15),
                   entry_price=300, exit_price=280, quantity=10, profit=-200, stop_loss=280)
    ]
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
def learner(db_manager, aggregator):
    return Learner(aggregator=aggregator, db_manager=db_manager)

def test_analyze_errors(learner, db_manager):
    input_data = LearningInput(tickers=['SBER'], date_range=(date(2025, 10, 1), date(2025, 10, 30)), model_path=":memory:")
    errors = learner.analyze_errors(input_data)
    assert len(errors) == 1
    assert "Ложный сигнал" in errors[0]
    assert "SBER" in errors[0]

def test_retrain(learner, db_manager, aggregator):
    input_data = LearningInput(tickers=['SBER'], date_range=(date(2025, 10, 1), date(2025, 10, 30)), model_path=":memory:")
    learner.retrain(input_data)
    assert db_manager.load.called

def test_ab_test(learner, db_manager, aggregator):
    input_data = LearningInput(tickers=['SBER'], date_range=(date(2025, 10, 1), date(2025, 10, 30)), model_path=":memory:")
    result = learner.run_ab_test(input_data)
    assert isinstance(result, LearningResult)
    assert result.best_model in ["rf", "svm"]
    assert 0 <= result.win_rate_rf <= 1
    assert 0 <= result.accuracy_rf <= 1
    assert 0 <= result.win_rate_svm <= 1
    assert 0 <= result.accuracy_svm <= 1

def test_learning_error(learner, db_manager):
    db_manager.load.side_effect = Exception("DB error")
    input_data = LearningInput(tickers=['SBER'], date_range=(date(2025, 10, 1), date(2025, 10, 30)), model_path=":memory:")
    with pytest.raises(LearningError):
        learner.analyze_errors(input_data)
```

## Логирование
- Логи сохраняются в `logs/app_YYYYMMDD.log` и таблице `logs` через `DatabaseManager`.
- Категории: `learner`, `error`.
- Пример:
  ```
  2025-10-20 18:30: [learner] Анализ ошибок для ['SBER']
  2025-10-20 18:31: [learner] Переобучение модели для ['SBER']
  2025-10-20 18:32: [error] Ошибка A/B-тестирования: DB error
  ```

## Обработка ошибок
- Кастомное исключение:
  ```python
  # src/core/exceptions.py
  class LearningError(Exception):
      """Ошибка самообучения."""
      pass
  ```
- Fallback: При ошибке возвращается `LearningResult` с нулевыми метриками.

## Масштабируемость
- **MLflow**: Трекинг метрик и моделей в Фазе 3.4.
- **LSTM**: Поддержка PyTorch для сложных моделей.
- **Async**: Добавить `async def retrain` для асинхронного обучения.
- **REST**: Поддержка FastAPI для сериализации `LearningResult`.

## Следующие шаги
- Интегрировать результаты в `MainWindow` (вкладка "Обучение") в Шаге 3.4.
- Перейти к Шагу 3.4 (`TrainingUI`).
- Проверить зависимости: `pip install pandas scikit-learn joblib`.