# Шаг 2.3: Реализация модуля рекомендаций (Recommender)

## Введение
Этот документ описывает реализацию модуля рекомендаций (`Recommender`) для формирования сигналов (buy/sell/hold) на основе выходных данных анализаторов (`NewsAnalyzer`, `TechnicalAnalyzer`, `RiskAnalyzer`) с использованием `RandomForestClassifier` из scikit-learn. Модуль следует принципам модульности из `ModularityConcept.md`: чёткий контракт через `RecommenderInterface` и pydantic модели, независимость, Dependency Injection (DI) через factory, простота для MVP с хуками для масштабирования. Рекомендации формируются на горизонте 2–8 недель и интегрируются с `Aggregator` для отображения в UI (`MainWindow`).

**Цели шага**:
- Создать `Recommender` для генерации сигналов (buy/sell/hold).
- Реализовать контракт через `RecommenderInterface` с методом `generate`, возвращающим `Dict[str, Recommendation]`.
- Использовать pydantic модели для входа (`AnalyzerOutput`) и выхода (`Recommendation`).
- Интегрировать с `Aggregator` для получения оценок анализаторов.
- Добавить тесты (`pytest`) с mock-данными.
- Реализовать логирование и обработку ошибок.
- Подготовить к масштабированию (например, переход на PyTorch или LSTM).

**Место в архитектуре**:
- Модуль: `src/ai/recommender.py`.
- Зависимости: `scikit-learn`, `pydantic`, `src/core/models.py`, `src/core/interfaces.py`, `src/core/logging.py`, `src/core/exceptions.py`, `src/ai/aggregator.py`.
- Интеграция: `Recommender` инжектируется в `Aggregator` через `config.yaml`.

## Требования
- **Источник данных**: Выходные данные анализаторов (`AnalyzerOutput`) через `Aggregator`.
- **Модель**: `RandomForestClassifier` для предсказания сигналов (buy/sell/hold).
- **Features**: Оценки (`score`) и уверенности (`confidence`) от `NewsAnalyzer`, `TechnicalAnalyzer`, `RiskAnalyzer`.
- **Контракт**:
  - Вход: `Dict[str, Dict[str, AnalyzerOutput]]` (результаты анализаторов по тикерам).
  - Выход: `Dict[str, Recommendation]` (сигнал, целевая цена, стоп-лосс, срок, уверенность, обоснование).
- **Оффлайн-режим**: Модель обучается локально, использует данные из DuckDB.
- **Ошибки**: Кастомное исключение (`ProcessingError`), логи в `logs/app_YYYYMMDD.log`.
- **Тесты**: Unit-тесты с mock-данными (coverage >80%).
- **Масштаб**: Хук для PyTorch (LSTM), MLflow для трекинга.

## Контракт модуля
Модуль реализует `RecommenderInterface`, определяющий метод `generate` для формирования рекомендаций. Используются pydantic модели из `src/core/models.py`.

### Абстрактный класс
```python
from abc import ABC, abstractmethod
from typing import Dict
from pydantic import BaseModel
from datetime import date

class Recommendation(BaseModel):
    """Рекомендация для тикера."""
    signal: str  # buy/sell/hold
    target_price: float | None  # Целевая цена
    stop_loss: float | None  # Стоп-лосс
    horizon: str  # Срок (например, "4 недели")
    confidence: float  # Уверенность (0..1)
    reason: str  # Обоснование

class RecommenderInterface(ABC):
    @abstractmethod
    def generate(self, analyzer_outputs: Dict[str, Dict[str, AnalyzerOutput]]) -> Dict[str, Recommendation]:
        """Генерирует рекомендации на основе выходов анализаторов.

        Args:
            analyzer_outputs: Выходы анализаторов (news, technical, risk) по тикерам.

        Returns:
            Dict[ticker, Recommendation]: Рекомендации для тикеров.

        Raises:
            ProcessingError: Если ошибка генерации.
        """
        pass
```

**Правила для контракта**:
- Метод: Только `generate` (sync, без async для MVP).
- Вход: `analyzer_outputs` — словарь с результатами анализаторов (`news`, `technical`, `risk`).
- Выход: `Dict[str, Recommendation]` с сигналом, целевой ценой, стоп-лоссом, сроком, уверенностью и обоснованием.
- Исключения: `ProcessingError` для ошибок обработки.
- Backward-compatibility: Новые поля в `Recommendation` — optional.

## Реализация Recommender
Модуль `Recommender` реализует `RecommenderInterface`, использует `RandomForestClassifier` для предсказания сигналов на основе оценок анализаторов. Для MVP:
- **Features**: `score` и `confidence` от каждого анализатора (6 фич: news_score, news_confidence, technical_score, technical_confidence, risk_score, risk_confidence).
- **Labels**: Buy (>5% роста), Sell (<-5% падения), Hold (иначе).
- **Обучение**: Локально на исторических данных (3 года, заглушка для MVP).
- **Вывод**: Сигнал, целевая цена (заглушка), стоп-лосс (из `RiskAnalyzer`), срок (фиксировано 4 недели), уверенность (усреднённая).

### Код
```python
# src/ai/recommender.py
"""Модуль для генерации рекомендаций с RandomForest."""

import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from typing import Dict
from src.core.interfaces import AnalyzerInterface, AnalyzerOutput, AnalyzerInput
from src.core.models import Recommendation
from src.core.exceptions import ProcessingError
from src.core.logging import setup_logging
from joblib import load, dump
from datetime import date

class Recommender(RecommenderInterface):
    def __init__(self, model_path: str = "models/rf_v1.pkl"):
        """Инициализация рекомендера.

        Args:
            model_path: Путь к сохранённой модели RandomForest.
        """
        self.model_path = model_path
        self.logger = setup_logging()
        try:
            self.model = load(model_path)
        except FileNotFoundError:
            self.model = RandomForestClassifier(n_estimators=100, random_state=42)
            self._train_model()  # Заглушка для обучения
            dump(self.model, model_path)
        self.logger.info("[recommender] Модель инициализирована")

    def _train_model(self):
        """Заглушка для обучения модели на исторических данных."""
        # В MVP используем синтетические данные, в Фазе 3 — реальные
        X = pd.DataFrame([
            [0.5, 0.5, 0.3, 0.5, -0.5, 0.5],  # Пример: buy
            [-0.5, 0.5, -0.3, 0.5, -0.5, 0.5],  # Пример: sell
            [0, 0.5, 0, 0.5, 0, 0.5]  # Пример: hold
        ], columns=['news_score', 'news_confidence', 'technical_score', 'technical_confidence', 'risk_score', 'risk_confidence'])
        y = ['buy', 'sell', 'hold']
        self.model.fit(X, y)
        self.logger.info("[recommender] Модель обучена (заглушка)")

    def generate(self, analyzer_outputs: Dict[str, Dict[str, AnalyzerOutput]]) -> Dict[str, Recommendation]:
        """Генерирует рекомендации на основе выходов анализаторов.

        Args:
            analyzer_outputs: Выходы анализаторов (news, technical, risk).

        Returns:
            Dict[ticker, Recommendation]: Рекомендации для тикеров.

        Raises:
            ProcessingError: Если ошибка генерации.
        """
        try:
            self.logger.info("[recommender] Генерация рекомендаций")
            recommendations = {}
            for ticker in set().union(*(outputs.keys() for outputs in analyzer_outputs.values())):
                # Собираем фичи
                features = []
                reasons = []
                confidences = []
                stop_loss = None
                for analyzer in ['news', 'technical', 'risk']:
                    output = analyzer_outputs.get(analyzer, {}).get(ticker, AnalyzerOutput(score=0, confidence=0, reason="Нет данных"))
                    features.extend([output.score, output.confidence])
                    if output.reason != "Нет данных":
                        reasons.append(f"{analyzer}: {output.reason}")
                    confidences.append(output.confidence)
                    if analyzer == 'risk' and output.score != 0:
                        stop_loss = float(output.reason.split("Стоп-лосс: ")[1].split(" ")[0]) if "Стоп-лосс" in output.reason else None
                # Предсказание
                X = pd.DataFrame([features], columns=[
                    'news_score', 'news_confidence', 'technical_score', 'technical_confidence', 'risk_score', 'risk_confidence'
                ])
                signal = self.model.predict(X)[0]
                confidence = sum(confidences) / max(len(confidences), 1)
                reason = "; ".join(reasons) if reasons else "Нет значимых сигналов"
                recommendations[ticker] = Recommendation(
                    signal=signal,
                    target_price=None,  # Заглушка, до Шага 3
                    stop_loss=stop_loss,
                    horizon="4 недели",  # Фиксировано для MVP
                    confidence=confidence,
                    reason=reason
                )
            self.logger.info(f"[recommender] Сгенерировано {len(recommendations)} рекомендаций")
            return recommendations
        except Exception as e:
            self.logger.error(f"[recommender] Ошибка генерации: {str(e)}")
            raise ProcessingError(f"Ошибка генерации рекомендаций: {str(e)}")
```

### Пояснения к реализации
- **Модель**: `RandomForestClassifier` предсказывает сигналы (buy/sell/hold) на основе 6 фич: `score` и `confidence` от трёх анализаторов.
- **Обучение**: Заглушка с синтетическими данными для MVP. В Фазе 3 — обучение на исторических данных (3 года, TimeSeriesSplit).
- **Рекомендация**:
  - `signal`: Выход модели (buy/sell/hold).
  - `target_price`: Заглушка (None), будет добавлена в Фазе 3.
  - `stop_loss`: Извлекается из `RiskAnalyzer` (если доступно).
  - `horizon`: Фиксировано "4 недели" для MVP.
  - `confidence`: Среднее от `confidence` анализаторов.
  - `reason`: Объединяет обоснования анализаторов.
- **Сохранение**: Модель сохраняется в `models/rf_v1.pkl` через `joblib`.
- **Ошибки**: Логируются, при сбое возвращается пустой словарь.

## Интеграция с другими модулями
- **Aggregator**: Передаёт `analyzer_outputs` в `Recommender.generate`:
  ```python
  # src/ai/aggregator.py
  class Aggregator:
      def __init__(self, analyzers: Dict[str, AnalyzerInterface], recommender: RecommenderInterface):
          self.analyzers = analyzers
          self.recommender = recommender

      def aggregate(self, inputs: Dict[str, AnalyzerInput]) -> Dict[str, Recommendation]:
          outputs = {name: analyzer.process(inputs.get(name, AnalyzerInput(tickers=[]))) for name, analyzer in self.analyzers.items()}
          return self.recommender.generate(outputs)
  ```
- **DI**: `Recommender` инжектируется через factory:
  ```python
  # src/core/config.py
  def get_recommender() -> RecommenderInterface:
      return Recommender(model_path="models/rf_v1.pkl")
  ```
  ```python
  aggregator = Aggregator(analyzers={
      'news': get_analyzer('basic_news', db_manager),
      'technical': get_analyzer('technical', db_manager),
      'risk': get_analyzer('risk', db_manager)
  }, recommender=get_recommender())
  ```
- **MainWindow**: Отображает рекомендации в таблице Дашборда (`signal`, `stop_loss`, `confidence`, `reason`).

## Тестирование
Тесты в `tests/test_recommender.py` проверяют генерацию рекомендаций и обработку ошибок.

```python
import pytest
from unittest.mock import Mock
from src.ai.recommender import Recommender, Recommendation
from src.core.exceptions import ProcessingError
from src.core.interfaces import AnalyzerOutput

@pytest.fixture
def recommender():
    return Recommender(model_path=":memory:")  # Временный путь для тестов

def test_recommender_success(recommender):
    analyzer_outputs = {
        'news': {'SBER': AnalyzerOutput(score=0.5, confidence=0.5, reason="5 упоминаний")},
        'technical': {'SBER': AnalyzerOutput(score=0.3, confidence=0.5, reason="RSI=75")},
        'risk': {'SBER': AnalyzerOutput(score=-0.5, confidence=0.5, reason="Стоп-лосс: 280.0")}
    }
    recommendations = recommender.generate(analyzer_outputs)
    assert isinstance(recommendations, Dict)
    assert 'SBER' in recommendations
    assert isinstance(recommendations['SBER'], Recommendation)
    assert recommendations['SBER'].signal in ['buy', 'sell', 'hold']
    assert recommendations['SBER'].confidence > 0
    assert "Стоп-лосс: 280.0" in recommendations['SBER'].reason
    assert recommendations['SBER'].stop_loss == 280.0

def test_recommender_no_data(recommender):
    analyzer_outputs = {'news': {}, 'technical': {}, 'risk': {}}
    recommendations = recommender.generate(analyzer_outputs)
    assert recommendations == {}

def test_recommender_error(recommender):
    analyzer_outputs = {'news': Exception("Invalid data")}
    with pytest.raises(ProcessingError):
        recommender.generate(analyzer_outputs)
```

## Логирование
- Логи сохраняются в `logs/app_YYYYMMDD.log` и таблице `logs` через `DatabaseManager`.
- Категории: `recommender`, `error`.
- Пример:
  ```
  2025-10-20 18:30: [recommender] Генерация рекомендаций
  2025-10-20 18:31: [error] Ошибка генерации: Invalid data
  ```

## Обработка ошибок
- Кастомное исключение:
  ```python
  # src/core/exceptions.py
  class ProcessingError(Exception):
      """Ошибка обработки данных в анализаторах или рекомендере."""
      pass
  ```
- Fallback: При ошибке возвращается пустой словарь рекомендаций.

## Масштабируемость
- **Новая модель**: Новый подкласс `LSTMRecommender` с PyTorch:
  ```python
  class LSTMRecommender(RecommenderInterface):
      def generate(self, analyzer_outputs: Dict[str, Dict[str, AnalyzerOutput]]) -> Dict[str, Recommendation]:
          # Логика с LSTM
          return {ticker: Recommendation(signal="buy", target_price=None, stop_loss=None, horizon="4 недели", confidence=0.9, reason="LSTM prediction") for ticker in analyzer_outputs.get('news', {})}
  ```
  Смена в `config.yaml`: `recommender: lstm`.
- **MLflow**: Трекинг метрик (Win Rate, Sharpe) в Фазе 3.
- **Async**: В будущем добавить `async def generate` для асинхронных вызовов.
- **Микро-сервисы**: Переход на REST (FastAPI) с JSON-сериализацией `Recommendation`.

## Следующие шаги
- Реализовать `DataProvider` (Шаг 1.2) для загрузки котировок.
- Перейти к Фазе 3, Шаг 3.1 (Backtesting).
- Проверить зависимости: `pip install scikit-learn joblib`.