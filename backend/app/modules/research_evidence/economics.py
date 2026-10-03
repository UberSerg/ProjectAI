"""Long-only OOS economic research simulator v1 (not Shadow, not broker).

Historical EOD decision at session T, fill at the next eligible session's
official OPEN. Dividends excluded. Return semantic is PRICE_RETURN.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

import pandas as pd

from app.domain.ports.execution import OrderIntent
from app.modules.market.application.split_events import SPLIT_FEED_EVENT_TYPES
from app.modules.research_evidence.economics_metrics import (
    compute_research_metrics,
    cost_drag,
)
from app.modules.simulator.application.calendar import next_trading_day
from app.modules.simulator.application.execution import HistoricalNextOpenAdapter
from app.modules.simulator.application.ledger import PortfolioLedger
from app.modules.simulator.application.market_view import MarketView, quantity_after_ca
from app.modules.simulator.config import CANONICAL_EXECUTION

MODEL_VARIANTS = ("BASE", "FUNDAMENTALS", "EVENTS", "V4_FULL")
ASSUMED_ALL_IN_COST_BPS_PER_SIDE = (0, 10, 30, 50)
REBALANCE_EVERY_N_SESSIONS = 20
TOP_QUANTILE = 0.20
MIN_ELIGIBLE_NAMES = 5
POSITION_SIZING = "FRACTIONAL_RESEARCH_WEIGHTS"
RETURN_SEMANTIC = "PRICE_RETURN"
UNIVERSE_POLICY = "historical_equity_universe_v2"
INITIAL_CAPITAL = 1_000_000.0
CANONICAL_EXECUTION_TIMING = CANONICAL_EXECUTION  # next_open
SKIPPED_BY_BOUNDARY = "SKIPPED_BY_BOUNDARY"

SelectionMode = Literal["strategy_top_quantile", "eligible_universe_equal_weight"]

_PRODUCTION_SOURCES = frozenset(
    {
        "production_candidate",
        "candidate",
        "candidate_v0",
        "candidate_v1",
        "shadow",
        "broker",
    }
)
_IN_SAMPLE = frozenset({"is", "in_sample", "insample", "train", "training", "development_is"})
_OOS = frozenset({"oos", "out_of_sample", "out-of-sample", "development_oos", "final_holdout"})


class EconomicsProvenanceError(ValueError):
    """OOS prediction frame failed the research provenance contract."""


class EconomicsContractError(ValueError):
    """Economic contract cannot be executed honestly."""


def rebalance_decision_dates(
    trading_days: list[date],
    *,
    every_n: int = REBALANCE_EVERY_N_SESSIONS,
) -> list[date]:
    """Predeclared cadence: first session, then every ``every_n`` trading sessions."""
    if every_n <= 0:
        raise EconomicsContractError("rebalance cadence must be positive")
    ordered = sorted(trading_days)
    return ordered[::every_n]


def required_market_date_to(
    decision_dates: list[date],
    trading_days: list[date],
) -> date:
    """Bounded MarketView ``date_to``: +1 session after max decision if the calendar has it.

    OPTION A for loaders: pass a calendar that can see past the last as_of so the
    next official OPEN is in the view. If ``next_trading_day`` is missing, returns
    max(decision) and the simulator applies OPTION B (skip, do not count).
    """
    if not decision_dates:
        raise EconomicsContractError("decision_dates required for market date_to")
    last = max(_as_date(d) for d in decision_dates)
    nxt = next_trading_day(list(trading_days), last)
    return nxt if nxt is not None else last


def _as_date(value: Any) -> date:
    if isinstance(value, date) and not isinstance(value, pd.Timestamp):
        return value
    ts = pd.Timestamp(value)
    return ts.date()


def _col(frame: pd.DataFrame, *names: str) -> str | None:
    lower = {str(c).lower(): str(c) for c in frame.columns}
    for name in names:
        if name.lower() in lower:
            return lower[name.lower()]
    return None


def _series_bool(series: pd.Series) -> pd.Series:
    if series.dtype == bool:
        return series
    mapped = series.map(
        lambda v: str(v).strip().lower() in {"1", "true", "t", "yes", "y"}
        if not isinstance(v, bool)
        else v
    )
    return mapped.astype(bool)


def validate_oos_prediction_frame(
    frame: pd.DataFrame,
    *,
    model_variant: str,
    expected_dataset_values_hash: str | None = None,
    expected_experiment_fingerprint: str | None = None,
    trading_days: list[date] | None = None,
) -> pd.DataFrame:
    """Require OOS provenance; reject production Candidate / in-sample / hash mix."""
    if model_variant not in MODEL_VARIANTS:
        raise EconomicsProvenanceError(f"unsupported model_variant: {model_variant}")
    if frame is None or frame.empty:
        raise EconomicsProvenanceError("prediction frame is empty")

    decision_col = _col(frame, "decision_date", "as_of_date")
    iid_col = _col(frame, "instrument_id")
    pred_col = _col(frame, "y_pred", "prediction_score", "score")
    variant_col = _col(frame, "model_variant", "variant")
    fold_col = _col(frame, "fold_id", "fold")
    cutoff_col = _col(frame, "train_cutoff", "train_end", "train_cutoff_date")
    if not all([decision_col, iid_col, pred_col, variant_col, fold_col, cutoff_col]):
        raise EconomicsProvenanceError(
            "OOS frame requires decision_date (or as_of_date), instrument_id, "
            "y_pred, model_variant, fold_id, train_cutoff"
        )

    out = pd.DataFrame(
        {
            "decision_date": frame[decision_col].map(_as_date),
            "instrument_id": frame[iid_col].astype(int),
            "y_pred": pd.to_numeric(frame[pred_col], errors="coerce"),
            "model_variant": frame[variant_col].astype(str).str.upper(),
            "fold_id": frame[fold_col].astype(str),
            "train_cutoff": frame[cutoff_col].map(_as_date),
        }
    )
    out["ticker"] = (
        frame[_col(frame, "ticker", "symbol")].astype(str)
        if _col(frame, "ticker", "symbol")
        else out["instrument_id"].astype(str)
    )
    is_oos_col = _col(frame, "is_oos")
    split_col = _col(frame, "split", "sample_split")
    if is_oos_col is not None:
        out["is_oos"] = _series_bool(frame[is_oos_col])
    elif split_col is not None:
        out["split"] = frame[split_col].astype(str).str.lower().str.strip()
        out["is_oos"] = out["split"].isin(_OOS)
    else:
        raise EconomicsProvenanceError("OOS provenance required: is_oos or split")

    prod_col = _col(frame, "is_production_candidate")
    if prod_col is not None:
        out["is_production_candidate"] = _series_bool(frame[prod_col])
    src_col = _col(frame, "prediction_source", "source")
    if src_col is not None:
        out["prediction_source"] = frame[src_col].astype(str).str.lower().str.strip()
    uni_col = _col(frame, "universe_policy")
    if uni_col is not None:
        out["universe_policy"] = frame[uni_col].astype(str).str.strip()
    hash_col = _col(frame, "dataset_values_hash")
    if hash_col is not None:
        out["dataset_values_hash"] = frame[hash_col].astype(str)
    fp_col = _col(frame, "experiment_fingerprint")
    if fp_col is not None:
        out["experiment_fingerprint"] = frame[fp_col].astype(str)
    exec_col = _col(frame, "execution_date")
    if exec_col is not None:
        out["execution_date"] = frame[exec_col].map(
            lambda v: None if pd.isna(v) else _as_date(v)
        )

    out = out.loc[out["model_variant"] == model_variant].copy()
    if out.empty:
        raise EconomicsProvenanceError(f"no OOS rows for model_variant={model_variant}")

    if "split" in out.columns:
        if out["split"].isin(_IN_SAMPLE).any():
            raise EconomicsProvenanceError("in-sample predictions are not allowed")
        if not out["split"].isin(_OOS).all():
            raise EconomicsProvenanceError("split provenance is not exclusively OOS")
    if not bool(out["is_oos"].all()):
        raise EconomicsProvenanceError("in-sample predictions are not allowed")

    if "is_production_candidate" in out.columns and bool(out["is_production_candidate"].any()):
        raise EconomicsProvenanceError("production Candidate predictions mixed in")
    if "prediction_source" in out.columns and out["prediction_source"].isin(_PRODUCTION_SOURCES).any():
        raise EconomicsProvenanceError("production Candidate predictions mixed in")

    if "universe_policy" in out.columns:
        uni = out["universe_policy"]
        bad = uni[~uni.eq("") & ~uni.eq(UNIVERSE_POLICY)]
        if len(bad):
            raise EconomicsProvenanceError(
                "universe_policy must be historical_equity_universe_v2 "
                "(current-active shortcut is forbidden)"
            )

    if "dataset_values_hash" in out.columns:
        hashes = out["dataset_values_hash"].dropna().astype(str).unique().tolist()
        hashes = [h for h in hashes if h.lower() != "nan"]
        if expected_dataset_values_hash is not None:
            if any(h != expected_dataset_values_hash for h in hashes) or not hashes:
                raise EconomicsProvenanceError("dataset_values_hash mismatch")
        elif len(hashes) > 1:
            raise EconomicsProvenanceError("mismatched dataset hashes in prediction frame")
    elif expected_dataset_values_hash is not None:
        raise EconomicsProvenanceError("dataset_values_hash mismatch")

    if "experiment_fingerprint" in out.columns:
        fps = out["experiment_fingerprint"].dropna().astype(str).unique().tolist()
        fps = [f for f in fps if f.lower() != "nan"]
        if expected_experiment_fingerprint is not None:
            if any(f != expected_experiment_fingerprint for f in fps) or not fps:
                raise EconomicsProvenanceError("experiment fingerprint mismatch")
        elif len(fps) > 1:
            raise EconomicsProvenanceError("mismatched experiment fingerprints in prediction frame")
    elif expected_experiment_fingerprint is not None:
        raise EconomicsProvenanceError("experiment fingerprint mismatch")

    if "execution_date" in out.columns and trading_days:
        for decision, exec_day in zip(out["decision_date"], out["execution_date"], strict=True):
            if exec_day is None:
                continue
            if exec_day <= decision:
                raise EconomicsProvenanceError(
                    "execution_date must be strictly after decision_date (no same-close execution)"
                )
            expected = next_trading_day(trading_days, decision)
            if expected is None or exec_day != expected:
                raise EconomicsProvenanceError(
                    "execution_date must be the next eligible trading session "
                    "(no future-open in signal)"
                )
    if out["y_pred"].isna().any():
        raise EconomicsProvenanceError("prediction scores contain nulls")
    leaked = out["train_cutoff"] > out["decision_date"]
    if bool(leaked.any()):
        raise EconomicsProvenanceError("train_cutoff after decision_date is not point-in-time")
    return out.reset_index(drop=True)


def select_equal_weight_targets(
    day_frame: pd.DataFrame,
    *,
    mode: SelectionMode,
    top_quantile: float = TOP_QUANTILE,
    min_eligible_names: int = MIN_ELIGIBLE_NAMES,
) -> dict[int, float]:
    """Rank by OOS prediction only. Thin cross-section → empty (stay in cash)."""
    if day_frame.empty:
        return {}
    n = int(day_frame["instrument_id"].nunique())
    if mode == "eligible_universe_equal_weight":
        if n <= 0:
            return {}
        weight = 1.0 / n
        return {int(iid): weight for iid in sorted(day_frame["instrument_id"].unique())}

    if n < min_eligible_names:
        return {}
    ranked = day_frame.sort_values(
        ["y_pred", "instrument_id"],
        ascending=[False, True],
        kind="mergesort",
    )
    ranked = ranked.drop_duplicates(subset=["instrument_id"], keep="first")
    k = max(1, int(math.ceil(n * top_quantile)))
    picked = ranked.head(k)
    weight = 1.0 / k
    return {int(iid): weight for iid in picked["instrument_id"].tolist()}


def _official_open(market: MarketView, instrument_id: int, day: date) -> float | None:
    px = market.open_price(instrument_id, day)
    if px is None or px <= 0:
        return None
    return float(px)


def _apply_mechanical_ca(ledger: PortfolioLedger, market: MarketView, day: date) -> None:
    """SPLIT / REVERSE_SPLIT quantity scaling only. No dividend cash. RAW prices unchanged."""
    for iid, pos in list(ledger.positions.items()):
        for action in market.ca_on(iid, day):
            if action.event_type not in SPLIT_FEED_EVENT_TYPES:
                continue
            before_qty = pos.quantity
            after_qty = quantity_after_ca(before_qty, action.factor)
            ledger.set_position(iid, pos.ticker, after_qty)
            ledger.ca_events.append(
                {
                    "date": day.isoformat(),
                    "instrument_id": iid,
                    "ticker": pos.ticker,
                    "event_type": action.event_type,
                    "factor": str(action.factor),
                    "quantity_before": before_qty,
                    "quantity_after": after_qty,
                }
            )


def _ticker(market: MarketView, iid: int, fallback: str | None = None) -> str:
    return market.tickers.get(iid) or fallback or str(iid)


@dataclass
class _PendingRebalance:
    decision_date: date
    execution_date: date
    targets: dict[int, float]
    tickers: dict[int, str]


@dataclass
class _RunState:
    ledger: PortfolioLedger
    adapter: HistoricalNextOpenAdapter = field(default_factory=HistoricalNextOpenAdapter)
    pending: _PendingRebalance | None = None
    forced_exits: dict[int, tuple[str, date]] = field(default_factory=dict)
    unavailable: list[dict[str, Any]] = field(default_factory=list)
    unresolved: list[dict[str, Any]] = field(default_factory=list)
    last_mark: dict[int, float] = field(default_factory=dict)
    eligible_by_day: dict[date, set[int]] = field(default_factory=dict)


def _mark_closes(
    market: MarketView,
    state: _RunState,
    day: date,
) -> dict[int, float | None]:
    closes: dict[int, float | None] = {}
    for iid in state.ledger.positions:
        px = market.close_price(iid, day)
        if px is not None and px > 0:
            state.last_mark[iid] = float(px)
            closes[iid] = float(px)
        else:
            closes[iid] = state.last_mark.get(iid)
    return closes


def _record_unavailable(
    state: _RunState,
    *,
    day: date,
    iid: int,
    ticker: str,
    reason: str,
    decision_date: date | None = None,
) -> None:
    state.unavailable.append(
        {
            "status": "EXECUTION_PRICE_UNAVAILABLE",
            "date": day.isoformat(),
            "instrument_id": iid,
            "ticker": ticker,
            "reason": reason,
            "decision_date": decision_date.isoformat() if decision_date else None,
        }
    )


def _fill_intent(
    state: _RunState,
    market: MarketView,
    intent: OrderIntent,
    *,
    all_in_bps: float,
) -> bool:
    if intent.execution_date <= intent.decision_date:
        raise EconomicsContractError(
            "execution_date must be strictly after decision_date "
            f"(decision={intent.decision_date}, execution={intent.execution_date})"
        )
    raw_open = _official_open(market, intent.instrument_id, intent.execution_date)
    if raw_open is None:
        _record_unavailable(
            state,
            day=intent.execution_date,
            iid=intent.instrument_id,
            ticker=intent.ticker,
            reason="official OPEN missing; close was not used",
            decision_date=intent.decision_date,
        )
        return False
    fill = state.adapter.fill(
        intent,
        raw_open=raw_open,
        commission_bps=all_in_bps,
        slippage_bps=0.0,
    )
    if fill is None:
        _record_unavailable(
            state,
            day=intent.execution_date,
            iid=intent.instrument_id,
            ticker=intent.ticker,
            reason="adapter rejected fill without substituting close",
            decision_date=intent.decision_date,
        )
        return False
    if fill.side == "BUY":
        cost = fill.notional + fill.commission
        if cost > state.ledger.cash + 1e-6:
            if fill.fill_price <= 0 or state.ledger.cash <= 0:
                return False
            affordable = state.ledger.cash / (
                fill.fill_price * (1.0 + all_in_bps / 10_000.0)
            )
            if affordable <= 1e-12:
                return False
            scaled = OrderIntent(
                decision_date=intent.decision_date,
                execution_date=intent.execution_date,
                instrument_id=intent.instrument_id,
                ticker=intent.ticker,
                side=intent.side,
                target_weight=intent.target_weight,
                target_notional=affordable * fill.fill_price,
                quantity=affordable,
                reason=intent.reason + "|cash_scaled",
                prediction_date=intent.prediction_date,
                predicted_return_20d=intent.predicted_return_20d,
                rank=intent.rank,
                policy_name=intent.policy_name,
                fold_id=intent.fold_id,
                metadata=dict(intent.metadata or {}),
            )
            fill = state.adapter.fill(
                scaled,
                raw_open=raw_open,
                commission_bps=all_in_bps,
                slippage_bps=0.0,
            )
            if fill is None:
                return False
            cost = fill.notional + fill.commission
        state.ledger.cash -= cost
        new_qty = state.ledger.position_qty(fill.instrument_id) + fill.quantity
        state.ledger.set_position(fill.instrument_id, fill.ticker, new_qty)
        state.last_mark[fill.instrument_id] = fill.raw_open
    else:
        state.ledger.cash += fill.notional - fill.commission
        new_qty = state.ledger.position_qty(fill.instrument_id) - fill.quantity
        state.ledger.set_position(fill.instrument_id, fill.ticker, new_qty)
    state.ledger.fills.append(fill)
    if abs(state.ledger.cash) < 1e-8:
        state.ledger.cash = 0.0
    if state.ledger.cash < -1e-6:
        raise EconomicsContractError(
            f"leverage/negative cash after fill on {intent.execution_date}: {state.ledger.cash}"
        )
    return True


def _note_forced_exit(
    state: _RunState,
    iid: int,
    ticker: str,
    original_decision_date: date,
) -> None:
    if iid not in state.forced_exits:
        state.forced_exits[iid] = (ticker, original_decision_date)


def _execute_targets(
    state: _RunState,
    market: MarketView,
    *,
    day: date,
    decision_date: date,
    targets: dict[int, float],
    tickers: dict[int, str],
    all_in_bps: float,
) -> None:
    if sum(targets.values()) > 1.0 + 1e-9:
        raise EconomicsContractError("target weights exceed 1.0 (leverage forbidden)")

    marked_mv = 0.0
    opens: dict[int, float] = {}
    held = set(state.ledger.positions.keys())
    universe = held | set(targets.keys())
    for iid in universe:
        px = _official_open(market, iid, day)
        if px is None:
            continue
        opens[iid] = px
        qty = state.ledger.position_qty(iid)
        if qty:
            marked_mv += qty * px
            state.last_mark[iid] = px
    nav = state.ledger.cash + marked_mv
    if nav <= 0:
        return

    sells: list[OrderIntent] = []
    buys: list[OrderIntent] = []
    for iid in sorted(universe):
        ticker = _ticker(market, iid, tickers.get(iid))
        target_w = float(targets.get(iid, 0.0))
        qty = state.ledger.position_qty(iid)
        px = opens.get(iid)
        if px is None:
            _record_unavailable(
                state,
                day=day,
                iid=iid,
                ticker=ticker,
                reason="official OPEN missing; close was not used",
                decision_date=decision_date,
            )
            if qty > 0 and target_w <= 0:
                _note_forced_exit(state, iid, ticker, decision_date)
            continue
        target_value = nav * target_w
        current_value = qty * px
        delta = target_value - current_value
        if abs(delta) < 1e-8:
            continue
        if delta < 0:
            sell_qty = min(qty, abs(delta) / px) if qty > 0 else 0.0
            if sell_qty <= 1e-12:
                continue
            sells.append(
                OrderIntent(
                    decision_date=decision_date,
                    execution_date=day,
                    instrument_id=iid,
                    ticker=ticker,
                    side="SELL",
                    target_weight=target_w,
                    target_notional=abs(delta),
                    quantity=sell_qty,
                    reason="research_rebalance",
                    metadata={"position_sizing": POSITION_SIZING},
                )
            )
        else:
            buy_qty = delta / px
            if buy_qty <= 1e-12:
                continue
            buys.append(
                OrderIntent(
                    decision_date=decision_date,
                    execution_date=day,
                    instrument_id=iid,
                    ticker=ticker,
                    side="BUY",
                    target_weight=target_w,
                    target_notional=delta,
                    quantity=buy_qty,
                    reason="research_rebalance",
                    metadata={"position_sizing": POSITION_SIZING},
                )
            )

    for intent in sells + buys:
        state.ledger.orders.append(intent)
        _fill_intent(state, market, intent, all_in_bps=all_in_bps)


def _try_forced_exits(
    state: _RunState,
    market: MarketView,
    day: date,
    *,
    all_in_bps: float,
) -> None:
    for iid, (ticker, original_decision_date) in list(state.forced_exits.items()):
        qty = state.ledger.position_qty(iid)
        if qty <= 1e-12:
            state.forced_exits.pop(iid, None)
            continue
        if day <= original_decision_date:
            continue
        px = _official_open(market, iid, day)
        if px is None:
            _record_unavailable(
                state,
                day=day,
                iid=iid,
                ticker=ticker,
                reason="delist/exit OPEN missing; close was not used",
                decision_date=original_decision_date,
            )
            continue
        intent = OrderIntent(
            decision_date=original_decision_date,
            execution_date=day,
            instrument_id=iid,
            ticker=ticker,
            side="SELL",
            target_weight=0.0,
            target_notional=qty * px,
            quantity=qty,
            reason="forced_exit",
            metadata={"position_sizing": POSITION_SIZING},
        )
        state.ledger.orders.append(intent)
        if _fill_intent(state, market, intent, all_in_bps=all_in_bps):
            state.forced_exits.pop(iid, None)


def _limitations(*, include_imoex: bool, imoex_skipped: str | None) -> list[str]:
    items = [
        "Historical OOS research simulation, not a live or broker backtest.",
        "Return semantic is PRICE_RETURN; dividends are excluded (not Total Return).",
        "RAW unadjusted session prices; mechanical SPLIT/REVERSE_SPLIT scale quantity only.",
        "Costs are ASSUMED_ALL_IN_COST_BPS_PER_SIDE research scenarios, not actual Sber/broker fees.",
        "Slippage exists only inside those assumed all-in scenarios; no order-book.",
        "Position sizing is FRACTIONAL_RESEARCH_WEIGHTS (no lot/tick realism).",
        "Cash earns 0; long-only; no leverage; no shorts.",
        "Rebalance every 20 trading sessions is predeclared and was not optimized.",
        "Eligible names come from the OOS prediction frame (historical_equity_universe_v2 contract); "
        "current-active universe is not used.",
        "Missing official OPEN is EXECUTION_PRICE_UNAVAILABLE; close is never a substitute fill.",
        "Delists are not backdated; missing valid exit is UNRESOLVED_EXIT / PARTIAL.",
        "Terminal next-open policy is OPTION B: if the next execution session is outside "
        "the preloaded MarketView, the rebalance is SKIPPED_BY_BOUNDARY and is not counted. "
        "Loaders may use required_market_date_to() (OPTION A, +1 session only) so that OPEN exists.",
        "Held names without a session mark are carried at last observed raw price for NAV only.",
    ]
    if imoex_skipped:
        items.append(f"IMOEX omitted: {imoex_skipped}")
    elif include_imoex:
        items.append("IMOEX is an optional price-index overlay, not the primary investable benchmark.")
    return items


def _assumptions_blob(*, all_in_bps: int) -> dict[str, Any]:
    return {
        "execution_timing": CANONICAL_EXECUTION_TIMING,
        "decision": "EOD at session T",
        "fill": "next eligible trading session official OPEN",
        "position_sizing": POSITION_SIZING,
        "rebalance_every_n_sessions": REBALANCE_EVERY_N_SESSIONS,
        "top_quantile": TOP_QUANTILE,
        "min_eligible_names": MIN_ELIGIBLE_NAMES,
        "long_only": True,
        "leverage": False,
        "shorts": False,
        "cash_return": 0.0,
        "dividends": "excluded",
        "return_semantic": RETURN_SEMANTIC,
        "universe_policy": UNIVERSE_POLICY,
        "assumed_all_in_cost_bps_per_side": all_in_bps,
        "cost_note": "research assumption, not actual Sber fee",
        "corporate_actions": "mechanical SPLIT/REVERSE_SPLIT quantity only; RAW prices",
        "terminal_next_open_policy": "OPTION_B_SKIPPED_BY_BOUNDARY",
        "terminal_next_open_note": (
            "Skip (do not count) a rebalance when next_trading_day is None. "
            "required_market_date_to() is OPTION A: bounded +1 session after max decision."
        ),
        "forced_exit_dates": (
            "original EOD decision_date; fill at a later official OPEN as execution_date; "
            "execution_date > decision_date always, including retries"
        ),
    }


def _wording(assumptions: dict[str, Any]) -> str:
    return (
        "Historical OOS research simulation under assumptions "
        f"execution={assumptions['execution_timing']}, "
        f"rebalance_every={assumptions['rebalance_every_n_sessions']} sessions, "
        f"top_quantile={assumptions['top_quantile']}, "
        f"min_eligible_names={assumptions['min_eligible_names']}, "
        f"all_in_cost_bps_per_side={assumptions['assumed_all_in_cost_bps_per_side']}, "
        f"return_semantic={assumptions['return_semantic']}, "
        "dividends=excluded, long_only, no leverage, FRACTIONAL_RESEARCH_WEIGHTS."
    )


def _imoex_overlay(market: MarketView, start: date, end: date) -> dict[str, Any]:
    if market.imoex_id is None:
        return {
            "included": False,
            "skipped_reason": "no IMOEX instrument in preloaded market view",
        }
    days = [d for d in market.trading_days if start <= d <= end]
    if not days:
        return {"included": False, "skipped_reason": "empty simulation window"}
    missing = [d for d in days if market.imoex_close(d) is None]
    if missing:
        return {
            "included": False,
            "skipped_reason": (
                "IMOEX history is not cleanly aligned with the research session calendar"
            ),
        }
    first = market.imoex_close(days[0])
    last = market.imoex_close(days[-1])
    if first is None or last is None or first <= 0:
        return {"included": False, "skipped_reason": "IMOEX prices unusable"}
    return {
        "included": True,
        "benchmark_type": "IMOEX_PRICE_INDEX_OPTIONAL",
        "note": "INDEX overlay — not the primary eligible-universe equal-weight benchmark",
        "total_price_return": last / first - 1.0,
        "date_from": days[0].isoformat(),
        "date_to": days[-1].isoformat(),
        "dividend_treatment": "price index; dividends excluded",
    }


def run_research_economics(
    *,
    predictions: pd.DataFrame,
    market: MarketView,
    model_variant: str,
    all_in_cost_bps_per_side: int = 0,
    expected_dataset_values_hash: str | None = None,
    expected_experiment_fingerprint: str | None = None,
    initial_capital: float = INITIAL_CAPITAL,
    include_sharpe_rf0_research: bool = False,
    selection_mode: SelectionMode = "strategy_top_quantile",
) -> dict[str, Any]:
    """Run one variant under one assumed all-in cost. Settings do not depend on the model."""
    if CANONICAL_EXECUTION_TIMING != "next_open":
        raise EconomicsContractError("research execution must remain next_open")
    if all_in_cost_bps_per_side < 0:
        raise EconomicsContractError("cost bps cannot be negative")

    frame = validate_oos_prediction_frame(
        predictions,
        model_variant=model_variant,
        expected_dataset_values_hash=expected_dataset_values_hash,
        expected_experiment_fingerprint=expected_experiment_fingerprint,
        trading_days=list(market.trading_days),
    )
    trading_days = list(market.trading_days)
    if not trading_days:
        raise EconomicsContractError("market view has no preloaded trading days")

    pred_dates = set(frame["decision_date"].tolist())
    scheduled_rebalance_days = [
        d for d in rebalance_decision_dates(trading_days) if d <= max(pred_dates)
    ]
    executed_rebalance_days: list[date] = []
    skipped_rebalance_dates: list[date] = []
    terminal_rebalance_without_execution_session: str | None = None
    state = _RunState(ledger=PortfolioLedger(cash=float(initial_capital), peak_nav=float(initial_capital)))
    by_day = {d: g.copy() for d, g in frame.groupby("decision_date", sort=False)}
    for d, g in by_day.items():
        state.eligible_by_day[d] = set(int(i) for i in g["instrument_id"].tolist())

    last_targets: dict[int, float] = {}
    for day in trading_days:
        _apply_mechanical_ca(state.ledger, market, day)
        if state.pending is not None and state.pending.execution_date == day:
            _execute_targets(
                state,
                market,
                day=day,
                decision_date=state.pending.decision_date,
                targets=state.pending.targets,
                tickers=state.pending.tickers,
                all_in_bps=float(all_in_cost_bps_per_side),
            )
            last_targets = dict(state.pending.targets)
            state.pending = None
        elif state.pending is not None and day > state.pending.execution_date:
            raise EconomicsContractError("pending rebalance execution date was skipped")
        _try_forced_exits(
            state, market, day, all_in_bps=float(all_in_cost_bps_per_side)
        )
        state.ledger.record_snapshot(day, _mark_closes(market, state, day))

        if day not in scheduled_rebalance_days:
            continue
        exec_day = next_trading_day(trading_days, day)
        if exec_day is None:
            skipped_rebalance_dates.append(day)
            terminal_rebalance_without_execution_session = SKIPPED_BY_BOUNDARY
            continue
        day_frame = by_day.get(day)
        if day_frame is None or day_frame.empty:
            targets: dict[int, float] = {}
            tickers: dict[int, str] = {}
        else:
            targets = select_equal_weight_targets(day_frame, mode=selection_mode)
            tickers = {
                int(r.instrument_id): str(r.ticker)
                for r in day_frame.itertuples(index=False)
            }
        dropped = set(last_targets) | set(state.ledger.positions)
        eligible_now = set(targets)
        for iid in dropped - eligible_now:
            if state.ledger.position_qty(iid) > 1e-12:
                _note_forced_exit(state, iid, _ticker(market, iid), day)
        state.pending = _PendingRebalance(
            decision_date=day,
            execution_date=exec_day,
            targets=targets,
            tickers=tickers,
        )
        executed_rebalance_days.append(day)
        state.ledger.rebalance_count += 1
        if day in pred_dates and exec_day <= day:
            raise EconomicsContractError("same-session execution is forbidden")

    if state.pending is not None:
        for iid in set(state.pending.targets) | set(state.ledger.positions):
            if state.ledger.position_qty(iid) > 1e-12 and iid not in state.pending.targets:
                state.unresolved.append(
                    {
                        "status": "UNRESOLVED_EXIT",
                        "instrument_id": iid,
                        "ticker": _ticker(market, iid),
                        "reason": "pending flatten never reached an official OPEN",
                        "decision_date": state.pending.decision_date.isoformat(),
                    }
                )
        state.pending = None

    for iid, (ticker, original_decision_date) in list(state.forced_exits.items()):
        if state.ledger.position_qty(iid) > 1e-12:
            state.unresolved.append(
                {
                    "status": "UNRESOLVED_EXIT",
                    "instrument_id": iid,
                    "ticker": ticker,
                    "reason": "no valid official OPEN exit after delist/drop; exit was not invented",
                    "decision_date": original_decision_date.isoformat(),
                }
            )

    metrics = compute_research_metrics(
        state.ledger,
        initial_capital=initial_capital,
        include_sharpe_rf0_research=include_sharpe_rf0_research,
    )
    metrics["unavailable_executions"] = len(state.unavailable)
    metrics["unresolved_exits"] = len(state.unresolved)
    metrics["gross_exposure_end"] = (
        state.ledger.snapshots[-1].gross_exposure if state.ledger.snapshots else 0.0
    )
    if metrics["gross_exposure_end"] > 1.0 + 1e-6:
        raise EconomicsContractError("gross exposure > 1 (leverage forbidden)")

    start = state.ledger.snapshots[0].as_of if state.ledger.snapshots else trading_days[0]
    end = state.ledger.snapshots[-1].as_of if state.ledger.snapshots else trading_days[-1]
    imoex = _imoex_overlay(market, start, end)
    assumptions = _assumptions_blob(all_in_bps=int(all_in_cost_bps_per_side))
    status = "PARTIAL" if state.unresolved else "COMPLETE"
    return {
        "status": status,
        "wording": _wording(assumptions),
        "model_variant": model_variant,
        "selection_mode": selection_mode,
        "assumptions": assumptions,
        "limitations": _limitations(
            include_imoex=bool(imoex.get("included")),
            imoex_skipped=None if imoex.get("included") else str(imoex.get("skipped_reason")),
        ),
        "metrics": metrics,
        "imoex": imoex,
        "unavailable_execution_events": list(state.unavailable),
        "unresolved_exit_events": list(state.unresolved),
        "ca_events": list(state.ledger.ca_events),
        "n_fills": len(state.ledger.fills),
        "final_cash": state.ledger.cash,
        "final_nav": metrics["end_nav"],
        "ledger": state.ledger,
        "rebalance_dates": [d.isoformat() for d in executed_rebalance_days],
        "skipped_rebalance_dates": [d.isoformat() for d in skipped_rebalance_dates],
        "terminal_rebalance_without_execution_session": (
            terminal_rebalance_without_execution_session
        ),
        "terminal_next_open_policy": "OPTION_B_SKIPPED_BY_BOUNDARY",
    }


def run_research_economics_cost_grid(
    *,
    predictions: pd.DataFrame,
    market: MarketView,
    model_variant: str,
    expected_dataset_values_hash: str | None = None,
    expected_experiment_fingerprint: str | None = None,
    initial_capital: float = INITIAL_CAPITAL,
    include_sharpe_rf0_research: bool = False,
) -> dict[str, Any]:
    """Same economic contract at 0/10/30/50 bps plus eligible-universe equal-weight bench."""
    common = dict(
        predictions=predictions,
        market=market,
        model_variant=model_variant,
        expected_dataset_values_hash=expected_dataset_values_hash,
        expected_experiment_fingerprint=expected_experiment_fingerprint,
        initial_capital=initial_capital,
        include_sharpe_rf0_research=include_sharpe_rf0_research,
    )
    strategy: dict[int, dict[str, Any]] = {}
    benchmark: dict[int, dict[str, Any]] = {}
    for bps in ASSUMED_ALL_IN_COST_BPS_PER_SIDE:
        strategy[bps] = run_research_economics(
            **common,
            all_in_cost_bps_per_side=bps,
            selection_mode="strategy_top_quantile",
        )
        benchmark[bps] = run_research_economics(
            **common,
            all_in_cost_bps_per_side=bps,
            selection_mode="eligible_universe_equal_weight",
        )

    def _ret(blob: dict[str, Any]) -> float | None:
        return blob["metrics"].get("cumulative_price_return")

    net = {bps: _ret(strategy[bps]) for bps in ASSUMED_ALL_IN_COST_BPS_PER_SIDE}
    gross = net[0]
    drags = {
        bps: cost_drag(gross_return=gross, net_return=net[bps])
        for bps in ASSUMED_ALL_IN_COST_BPS_PER_SIDE
        if bps > 0
    }
    statuses = {strategy[bps]["status"] for bps in strategy}
    status = "PARTIAL" if "PARTIAL" in statuses else "COMPLETE"
    assumptions = dict(strategy[0]["assumptions"])
    assumptions["assumed_all_in_cost_bps_per_side"] = list(ASSUMED_ALL_IN_COST_BPS_PER_SIDE)
    return {
        "status": status,
        "wording": _wording(assumptions),
        "model_variant": model_variant,
        "assumptions": assumptions,
        "limitations": strategy[0]["limitations"],
        "gross": strategy[0]["metrics"],
        "net_by_cost_bps": {
            bps: strategy[bps]["metrics"] for bps in ASSUMED_ALL_IN_COST_BPS_PER_SIDE
        },
        "cost_drag_vs_0bps": drags,
        "primary_benchmark": {
            "type": "eligible_universe_equal_weight",
            "same_rebalance_dates": True,
            "same_next_open": True,
            "same_ca_handling": True,
            "net_by_cost_bps": {
                bps: benchmark[bps]["metrics"] for bps in ASSUMED_ALL_IN_COST_BPS_PER_SIDE
            },
        },
        "imoex": strategy[0]["imoex"],
        "rebalance_dates": strategy[0]["rebalance_dates"],
        "skipped_rebalance_dates": strategy[0]["skipped_rebalance_dates"],
        "terminal_rebalance_without_execution_session": strategy[0][
            "terminal_rebalance_without_execution_session"
        ],
        "terminal_next_open_policy": strategy[0]["terminal_next_open_policy"],
        "unavailable_executions": strategy[0]["metrics"]["unavailable_executions"],
        "unresolved_exits": strategy[0]["metrics"]["unresolved_exits"],
        "_strategy_runs": strategy,
        "_benchmark_runs": benchmark,
    }


def run_all_model_variants(
    *,
    predictions: pd.DataFrame,
    market: MarketView,
    expected_dataset_values_hash: str | None = None,
    expected_experiment_fingerprint: str | None = None,
    initial_capital: float = INITIAL_CAPITAL,
    include_sharpe_rf0_research: bool = False,
) -> dict[str, Any]:
    """Identical economic settings for BASE / FUNDAMENTALS / EVENTS / V4_FULL."""
    settings = {
        "rebalance_every_n_sessions": REBALANCE_EVERY_N_SESSIONS,
        "top_quantile": TOP_QUANTILE,
        "min_eligible_names": MIN_ELIGIBLE_NAMES,
        "costs_bps": list(ASSUMED_ALL_IN_COST_BPS_PER_SIDE),
        "execution_timing": CANONICAL_EXECUTION_TIMING,
        "position_sizing": POSITION_SIZING,
        "return_semantic": RETURN_SEMANTIC,
        "universe_policy": UNIVERSE_POLICY,
    }
    variants: dict[str, Any] = {}
    for variant in MODEL_VARIANTS:
        variants[variant] = run_research_economics_cost_grid(
            predictions=predictions,
            market=market,
            model_variant=variant,
            expected_dataset_values_hash=expected_dataset_values_hash,
            expected_experiment_fingerprint=expected_experiment_fingerprint,
            initial_capital=initial_capital,
            include_sharpe_rf0_research=include_sharpe_rf0_research,
        )
    return {
        "wording": (
            "Historical OOS research simulation under assumptions X/Y/Z "
            "applied identically to BASE, FUNDAMENTALS, EVENTS, and V4_FULL."
        ),
        "economic_settings": settings,
        "variants": variants,
    }
