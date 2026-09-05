# Будущая экономическая цель

После доказательства качества прогнозов система сможет сравнивать expected return с
релевантным hurdle, распределять капитал между `EQUITY_ALPHA`, `FIXED_INCOME` и `CASH`,
затем применять отдельный Risk Manager и сменный Execution Adapter.

Эта последовательность не объединяет prediction, allocation, risk и execution. Следующие
этапы требуют walk-forward проверки, Candidate → Champion, shadow/signal режима и отдельного
решения о реальных деньгах. V0 не реализует брокера, налоги, dividend engine, RL или автономию.
