# Future Learning Loop

Self-learning does **not** mean an LLM rewriting production prompts/code.

Planned loop:

```text
New observations
  -> Training Dataset
  -> Train Candidate
  -> Backtest
  -> Walk-forward validation
  -> Candidate vs Champion
  -> Approve / Reject
```

Foundation already includes:

- `learning.model_registry` table
- `ModelRecord` / `ModelStatus` domain types
- Celery worker/scheduler processes for future jobs

Virtual portfolio only — no real broker trading in MVP path.
