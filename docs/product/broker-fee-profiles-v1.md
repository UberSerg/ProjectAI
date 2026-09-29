# Broker Fee Profiles V1

Status: **schema + pure Fee Engine** (Personal wiring done; Shadow V3 uses FeeEngine
end-to-end for gate / lot-plan / fill).

## What it is

Versioned broker tariff profiles and matchable fee rules for estimating
**broker commission only** (not exchange fees, not slippage).

| Entity | Role |
|--------|------|
| `FeeProfile` | Versioned tariff snapshot (`builtin` / `read_only` for Sber) |
| `FeeRule` | Match market / side / instrument / turnover tier → % and/or fixed |
| `BrokerAccount` | User-facing broker book pointing at a profile (no credentials) |
| `FeeEngine` | Pure domain estimator: `estimate_fee(context) → KNOWN \| UNKNOWN` |

## Built-in: Sber Investment

- Broker: СберИнвестиции / tariff Инвестиционный
- Source: https://www.sberbank.ru/ru/person/investments/broker_service/tarifs
- Note: `User-provided tariff snapshot, 2026-09-29`
- Default MOEX online (`SBER_MOEX_ONLINE_DEFAULT`): **0.3%** of clean turnover
  (NKD excluded; exchange fees separate)
- Temporary zero broker fee for verified УК Первая BPIF **SBFR** only:
  2026-08-04 … 2026-12-31; turnover excluded
- Do **not** guess zero fee for SBMM / SBRB / FLOW without verified manager

### Date asymmetry (intentional)

| Rule | `valid_from` | `valid_to` | Rationale |
|------|--------------|------------|-----------|
| `SBER_MOEX_ONLINE_DEFAULT` | **2026-09-29** | unbounded | Snapshot known_at — we do not claim the 0.3% generic rate was verified before the user-provided tariff page date |
| `SBER_SBFR_ZERO_TEMP` | 2026-08-04 | 2026-12-31 | Manager-verified temporary window for SBFR only |

Consequence:

- On `2026-09-01`, **SBER** (generic) → `UNKNOWN` (no fake 0%).
- On `2026-09-01`, **SBFR** → `KNOWN` amount `0` (temp override still active).
- After `2026-12-31`, SBFR falls back to generic **only if** `as_of >= 2026-09-29`;
  otherwise still `UNKNOWN`.

In-memory `sber_investment_builtin_rules()` mirrors the migration seed.

## FeeEngine call shape

```python
from datetime import date
from decimal import Decimal
from app.modules.portfolio.domain.fee_engine import (
    FeeEngine,
    FeeEstimateContext,
    sber_investment_builtin_rules,
)

engine = FeeEngine(sber_investment_builtin_rules())
est = engine.estimate_fee(
    FeeEstimateContext(
        as_of=date(2026, 9, 29),
        side="BUY",
        notional=Decimal("100000"),  # clean, ex-NKD
        nkd=Decimal("0"),
        market="MOEX",
        instrument_symbol="SBER",
        broker_account_day_turnover=Decimal("0"),  # shared across portfolios on same account
    )
)
# est.status == KNOWN | UNKNOWN
# est.amount is Decimal when KNOWN; None when UNKNOWN (never fake zero)
# est.fee_rule_id / est.explanation / est.exclude_from_turnover
```

## Provenance on operations

`personal_operations.commission_source`: `NONE` | `MANUAL` | `PROFILE_ESTIMATE` (nullable for legacy rows).

Existing portfolios keep `broker_account_id = NULL`.

Shadow V3 orders/fills snapshot `fee_profile_code`, `fee_profile_version`, `fee_date`,
estimated/actual fee, and matched rule id/code in metadata.

## Migration

`20260929_0026` — additive / reversible. Tariff dates for the builtin seed may be
edited in place while the revision is unmerged (version 1.0.0, no new migration).

## Out of scope (this stub)

- UI broker selector polish
- Exchange fees / NKD modelling beyond clean-notional contract
