"""Pure sell/review gate for Shadow Realism V3.

Rank exit-band breach is a REVIEW TRIGGER only — never an automatic SELL.
ROTATE requires expected-return edge covering sell+buy fees, slippage, and
``min_net_rotation_edge_bps``. Domain stays free of FastAPI/SQLAlchemy.

Sell permission invariant: no SELL without explicit gate authorization.
HOLD / REVIEW_HOLD / DATA_HOLD keep current weight (no mechanical trim) and
``sell_allowed=False``. Callers should pass entry-eligible replacements
(rank <= k_entry); the gate also filters by ``params.k_entry`` when set.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from app.modules.shadow.domain.fee_estimate import BrokerFeeEstimator

# Structured action codes (bounded — do not invent overlapping categories).
HOLD = "HOLD"
REVIEW_HOLD = "REVIEW_HOLD"
ROTATE = "ROTATE"
EXIT_TO_CASH = "EXIT_TO_CASH"
RISK_REDUCE = "RISK_REDUCE"
RISK_EXIT = "RISK_EXIT"
DATA_HOLD = "DATA_HOLD"

EXPECTED_RETURN = "EXPECTED_RETURN"

_NO_SELL_ACTIONS = frozenset({HOLD, REVIEW_HOLD, DATA_HOLD})
_FULL_SELL_ACTIONS = frozenset({ROTATE, RISK_EXIT, EXIT_TO_CASH})

_BPS = Decimal("10000")


@dataclass(frozen=True, slots=True)
class HeldName:
    instrument_id: int
    ticker: str
    quantity: float
    current_weight: float
    rank: int | None
    prediction_semantic: str
    expected_return: float | None
    signal_as_of: date | None
    price: float | None
    avg_entry: float | None = None
    unrealized_pnl: float | None = None
    in_exit_band: bool = True
    signal_stale: bool = False
    review_trigger: bool = False


@dataclass(frozen=True, slots=True)
class PolicyTarget:
    instrument_id: int
    ticker: str
    target_weight: float
    rank: int | None
    prediction_semantic: str
    expected_return: float | None
    action: str | None
    price: float | None = None
    signal_as_of: date | None = None
    signal_stale: bool = False


@dataclass(frozen=True, slots=True)
class ReplacementCandidate:
    instrument_id: int
    ticker: str
    rank: int | None
    prediction_semantic: str
    expected_return: float | None
    price: float | None
    signal_as_of: date | None = None
    signal_stale: bool = False


@dataclass(frozen=True, slots=True)
class SellGateParams:
    slippage_bps: float = 0.0
    min_net_rotation_edge_bps: float = 0.0
    fee_profile_code: str | None = None
    fee_profile_id: int | None = None
    k_entry: int | None = None
    exposure_cap: float = 1.0
    as_of: date | None = None


@dataclass(frozen=True, slots=True)
class FinalTarget:
    instrument_id: int
    ticker: str
    target_weight: float
    action: str
    rank: int | None = None
    predicted_return_20d: float | None = None
    policy: str | None = None
    gate_action: str | None = None
    rotate_from: int | None = None
    rotate_to: int | None = None


@dataclass(frozen=True, slots=True)
class SellPermission:
    """Per held-instrument sell authorization emitted by the V3 gate."""

    instrument_id: int
    ticker: str
    sell_allowed: bool
    action: str
    reason: str | None = None
    max_sell_units: Decimal | None = None
    max_sell_fraction: float | None = None
    rotate_to: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "instrument_id": self.instrument_id,
            "ticker": self.ticker,
            "sell_allowed": self.sell_allowed,
            "action": self.action,
            "reason": self.reason,
            "max_sell_units": (
                float(self.max_sell_units) if self.max_sell_units is not None else None
            ),
            "max_sell_fraction": self.max_sell_fraction,
            "rotate_to": self.rotate_to,
        }


@dataclass(frozen=True, slots=True)
class CandidateDecisionTrace:
    """Bounded structured facts for ShadowDecision metadata — no chain-of-thought."""

    instrument_id: int
    ticker: str
    decision_action: str
    reason_codes: tuple[str, ...] = ()
    limitation_codes: tuple[str, ...] = ()
    signal_as_of: str | None = None
    rank: int | None = None
    eligible_count: int | None = None
    prediction_semantic: str | None = None
    predicted_value: float | None = None
    held_before: bool = False
    quantity_before: float | None = None
    current_weight: float | None = None
    avg_entry: float | None = None
    current_mark: float | None = None
    unrealized_pnl: float | None = None
    in_exit_band: bool | None = None
    review_trigger: bool = False
    candidate_target_weight: float | None = None
    replacement_instrument_id: int | None = None
    replacement_ticker: str | None = None
    gross_expected_edge: float | None = None
    sell_fee_estimate: float | None = None
    buy_fee_estimate: float | None = None
    slippage_estimate: float | None = None
    net_edge: float | None = None
    min_net_rotation_edge_bps: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class SellGateResult:
    targets: tuple[FinalTarget, ...]
    traces: tuple[CandidateDecisionTrace, ...]
    permissions: tuple[SellPermission, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)


def _frac_bps(bps: float | Decimal) -> Decimal:
    return Decimal(str(bps)) / _BPS


def _edge_costs(
    *,
    sell_fee: Decimal,
    buy_fee: Decimal,
    sell_notional: Decimal,
    buy_notional: Decimal,
    slippage_bps: float,
    min_net_rotation_edge_bps: float,
) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    """Return (sell_fee_frac, buy_fee_frac, slip_frac, margin_frac) in return units."""
    sell_frac = (sell_fee / sell_notional) if sell_notional > 0 else Decimal("0")
    buy_frac = (buy_fee / buy_notional) if buy_notional > 0 else Decimal("0")
    # Slippage separate from broker fee — both sides of the rotation.
    slip_frac = _frac_bps(slippage_bps) * Decimal("2")
    margin_frac = _frac_bps(min_net_rotation_edge_bps)
    return sell_frac, buy_frac, slip_frac, margin_frac


def _best_replacement(
    candidates: Sequence[ReplacementCandidate],
    *,
    exclude_ids: set[int],
    k_entry: int | None,
) -> ReplacementCandidate | None:
    """Pick best entry-eligible replacement. Rank must be <= k_entry when set."""
    eligible = [
        c
        for c in candidates
        if int(c.instrument_id) not in exclude_ids
        and c.expected_return is not None
        and str(c.prediction_semantic) == EXPECTED_RETURN
        and not c.signal_stale
        and (
            k_entry is None
            or (c.rank is not None and int(c.rank) <= int(k_entry))
        )
    ]
    if not eligible:
        return None
    return sorted(
        eligible,
        key=lambda c: (-float(c.expected_return or 0.0), int(c.instrument_id)),
    )[0]


def _permission_for(
    h: HeldName,
    *,
    action: str,
    reason: str | None,
    rotate_to: int | None = None,
    exposure_cap: float = 1.0,
) -> SellPermission:
    if action in _NO_SELL_ACTIONS:
        return SellPermission(
            instrument_id=int(h.instrument_id),
            ticker=h.ticker,
            sell_allowed=False,
            action=action,
            reason=reason,
            rotate_to=None,
        )
    if action == RISK_REDUCE:
        cap = max(0.0, float(exposure_cap))
        # May sell down to current_weight * exposure_cap.
        max_frac = max(0.0, 1.0 - cap) if float(h.current_weight) > 0 else 1.0
        max_units = None
        if max_frac > 0 and h.quantity > 0:
            max_units = Decimal(str(h.quantity)) * Decimal(str(max_frac))
        return SellPermission(
            instrument_id=int(h.instrument_id),
            ticker=h.ticker,
            sell_allowed=True,
            action=action,
            reason=reason or RISK_REDUCE,
            max_sell_units=max_units,
            max_sell_fraction=max_frac if max_frac > 0 else 0.0,
            rotate_to=None,
        )
    if action in _FULL_SELL_ACTIONS:
        sell_reason = reason
        if action == ROTATE and rotate_to is not None and not sell_reason:
            sell_reason = f"ROTATE_TO_{rotate_to}"
        return SellPermission(
            instrument_id=int(h.instrument_id),
            ticker=h.ticker,
            sell_allowed=True,
            action=action,
            reason=sell_reason or action,
            max_sell_units=None,
            max_sell_fraction=None,
            rotate_to=rotate_to,
        )
    # Unknown / conservative: block sells.
    return SellPermission(
        instrument_id=int(h.instrument_id),
        ticker=h.ticker,
        sell_allowed=False,
        action=action,
        reason=reason,
    )


def apply_sell_gate(
    *,
    held: Sequence[HeldName],
    policy_targets: Sequence[PolicyTarget],
    replacement_candidates: Sequence[ReplacementCandidate],
    params: SellGateParams,
    fee_estimator: BrokerFeeEstimator,
    risk_forced: Mapping[int, str] | None = None,
    eligible_count: int | None = None,
    policy_name: str | None = None,
) -> SellGateResult:
    """Filter policy targets through economic sell/review gate (V3 only).

    Retained HOLD/REVIEW_HOLD/DATA_HOLD keep **current** weight so the lot
    planner has no mechanical trim signal; ``sell_allowed=False`` is the hard
    guard. ROTATE sell proceeds may fund the buy; retained A capital cannot
    fund B. Replacement candidates outside ``k_entry`` are ignored.
    """
    risk_forced = dict(risk_forced or {})
    policy_by_id = {int(t.instrument_id): t for t in policy_targets}
    policy_ids = set(policy_by_id)
    held_by_id = {int(h.instrument_id): h for h in held}
    held_ids = set(held_by_id)

    traces: list[CandidateDecisionTrace] = []
    permissions: list[SellPermission] = []
    retained_ids: set[int] = set()
    exit_ids: set[int] = set()
    rotate_pairs: dict[int, int] = {}  # A -> B
    rotate_to: set[int] = set()
    action_by_id: dict[int, str] = {}

    # Held names still selected by policy → HOLD (within exit band or re-entered).
    for iid in sorted(held_ids & policy_ids):
        h = held_by_id[iid]
        pt = policy_by_id[iid]
        force = risk_forced.get(iid)
        if force == RISK_EXIT:
            exit_ids.add(iid)
            action_by_id[iid] = RISK_EXIT
            traces.append(
                _trace_held(
                    h,
                    action=RISK_EXIT,
                    reason_codes=("RISK_FORCED_EXIT",),
                    eligible_count=eligible_count,
                    candidate_target_weight=0.0,
                )
            )
            permissions.append(
                _permission_for(h, action=RISK_EXIT, reason=RISK_EXIT, exposure_cap=params.exposure_cap)
            )
            continue
        if force == RISK_REDUCE:
            # Keep in set; exposure_cap applied later on weights.
            retained_ids.add(iid)
            action_by_id[iid] = RISK_REDUCE
            traces.append(
                _trace_held(
                    h,
                    action=RISK_REDUCE,
                    reason_codes=("RISK_FORCED_REDUCE",),
                    eligible_count=eligible_count,
                    candidate_target_weight=float(h.current_weight) * float(params.exposure_cap),
                )
            )
            permissions.append(
                _permission_for(
                    h,
                    action=RISK_REDUCE,
                    reason=RISK_REDUCE,
                    exposure_cap=params.exposure_cap,
                )
            )
            continue
        retained_ids.add(iid)
        action_by_id[iid] = HOLD
        traces.append(
            _trace_held(
                h,
                action=HOLD,
                reason_codes=("WITHIN_POLICY_SELECTION",),
                eligible_count=eligible_count,
                candidate_target_weight=float(h.current_weight),
            )
        )
        permissions.append(
            _permission_for(
                h,
                action=HOLD,
                reason="WITHIN_POLICY_SELECTION",
                exposure_cap=params.exposure_cap,
            )
        )

    # Reviewed = held but dropped by rank hysteresis (exit-band breach etc.).
    reviewed_ids = held_ids - policy_ids
    for iid in sorted(reviewed_ids):
        h = held_by_id[iid]
        force = risk_forced.get(iid)
        if force == RISK_EXIT:
            exit_ids.add(iid)
            action_by_id[iid] = RISK_EXIT
            traces.append(
                _trace_held(
                    h,
                    action=RISK_EXIT,
                    reason_codes=("RISK_FORCED_EXIT", "REVIEW_TRIGGER"),
                    eligible_count=eligible_count,
                    candidate_target_weight=0.0,
                    review_trigger=True,
                )
            )
            permissions.append(
                _permission_for(h, action=RISK_EXIT, reason=RISK_EXIT, exposure_cap=params.exposure_cap)
            )
            continue
        if force == RISK_REDUCE:
            retained_ids.add(iid)
            action_by_id[iid] = RISK_REDUCE
            traces.append(
                _trace_held(
                    h,
                    action=RISK_REDUCE,
                    reason_codes=("RISK_FORCED_REDUCE", "REVIEW_TRIGGER"),
                    eligible_count=eligible_count,
                    candidate_target_weight=float(h.current_weight) * float(params.exposure_cap),
                    review_trigger=True,
                )
            )
            permissions.append(
                _permission_for(
                    h,
                    action=RISK_REDUCE,
                    reason=RISK_REDUCE,
                    exposure_cap=params.exposure_cap,
                )
            )
            continue
        if force == EXIT_TO_CASH:
            exit_ids.add(iid)
            action_by_id[iid] = EXIT_TO_CASH
            traces.append(
                _trace_held(
                    h,
                    action=EXIT_TO_CASH,
                    reason_codes=("EXPLICIT_EXIT_TO_CASH", "REVIEW_TRIGGER"),
                    eligible_count=eligible_count,
                    candidate_target_weight=0.0,
                    review_trigger=True,
                )
            )
            permissions.append(
                _permission_for(
                    h,
                    action=EXIT_TO_CASH,
                    reason=EXIT_TO_CASH,
                    exposure_cap=params.exposure_cap,
                )
            )
            continue

        # Rank breach alone is NOT a sell — evaluate economics.
        # exclude_ids includes rotate_to so multiple reviewed cannot pile into same B.
        decision = _evaluate_reviewed(
            h,
            replacement_candidates=replacement_candidates,
            exclude_ids=held_ids | rotate_to,
            params=params,
            fee_estimator=fee_estimator,
            eligible_count=eligible_count,
        )
        traces.append(decision.trace)
        action_by_id[iid] = decision.action
        if decision.action in {REVIEW_HOLD, DATA_HOLD, HOLD}:
            retained_ids.add(iid)
            permissions.append(
                _permission_for(
                    h,
                    action=decision.action,
                    reason=(
                        decision.trace.limitation_codes[0]
                        if decision.trace.limitation_codes
                        else decision.action
                    ),
                    exposure_cap=params.exposure_cap,
                )
            )
        elif decision.action == ROTATE and decision.replacement_id is not None:
            exit_ids.add(iid)
            rotate_pairs[iid] = decision.replacement_id
            rotate_to.add(decision.replacement_id)
            repl = next(
                (
                    c
                    for c in replacement_candidates
                    if int(c.instrument_id) == int(decision.replacement_id)
                ),
                None,
            )
            reason = f"ROTATE_TO_{repl.ticker}" if repl is not None else f"ROTATE_TO_{decision.replacement_id}"
            permissions.append(
                _permission_for(
                    h,
                    action=ROTATE,
                    reason=reason,
                    rotate_to=decision.replacement_id,
                    exposure_cap=params.exposure_cap,
                )
            )
        elif decision.action in {RISK_EXIT, EXIT_TO_CASH}:
            exit_ids.add(iid)
            permissions.append(
                _permission_for(
                    h,
                    action=decision.action,
                    reason=decision.action,
                    exposure_cap=params.exposure_cap,
                )
            )
        else:
            retained_ids.add(iid)
            permissions.append(
                _permission_for(
                    h,
                    action=decision.action,
                    reason=decision.action,
                    exposure_cap=params.exposure_cap,
                )
            )

    # Build final instrument set: retained holds + rotate destinations + new enters
    # that fit remaining capacity without consuming retained-A capital.
    final_ids: set[int] = set(retained_ids) | set(rotate_to)
    k_entry = params.k_entry
    if k_entry is None:
        k_entry = max(len(policy_ids), len(final_ids))

    # Prefer policy ENTER order by rank ascending (better first).
    # Additive only — retained A capital must not fund these buys.
    enter_candidates = sorted(
        [t for t in policy_targets if int(t.instrument_id) not in held_ids],
        key=lambda t: (int(t.rank) if t.rank is not None else 10**9, int(t.instrument_id)),
    )
    remaining = max(0, int(k_entry) - len(final_ids))
    enter_ids: set[int] = set()
    for t in enter_candidates:
        if remaining <= 0:
            break
        iid = int(t.instrument_id)
        if iid in final_ids or iid in exit_ids:
            continue
        # Additive enter only with free capacity — retained A does not fund this buy.
        final_ids.add(iid)
        enter_ids.add(iid)
        remaining -= 1
        traces.append(
            CandidateDecisionTrace(
                instrument_id=iid,
                ticker=t.ticker,
                decision_action=str(t.action or "ENTER"),
                reason_codes=("POLICY_ENTER_FREE_CAPACITY",),
                signal_as_of=t.signal_as_of.isoformat() if t.signal_as_of else None,
                rank=t.rank,
                eligible_count=eligible_count,
                prediction_semantic=t.prediction_semantic,
                predicted_value=t.expected_return,
                held_before=False,
                candidate_target_weight=None,
            )
        )

    cap = float(params.exposure_cap)
    if cap < 0:
        cap = 0.0

    # Fixed weights for retained no-sell / risk-reduce names (no equal-weight trim).
    fixed_weights: dict[int, float] = {}
    for iid in retained_ids:
        h = held_by_id[iid]
        act = action_by_id.get(iid, HOLD)
        if act == RISK_REDUCE:
            fixed_weights[iid] = float(h.current_weight) * cap
        else:
            # HOLD / REVIEW_HOLD / DATA_HOLD — keep current weight.
            fixed_weights[iid] = float(h.current_weight)

    fixed_sum = sum(fixed_weights.values())
    free_ids = sorted(final_ids - set(fixed_weights))
    remaining_budget = max(0.0, cap - fixed_sum)
    free_w = (remaining_budget / len(free_ids)) if free_ids else 0.0

    ticker_by_id: dict[int, str] = {}
    for h in held:
        ticker_by_id[int(h.instrument_id)] = h.ticker
    for t in policy_targets:
        ticker_by_id[int(t.instrument_id)] = t.ticker
    for c in replacement_candidates:
        ticker_by_id[int(c.instrument_id)] = c.ticker

    rotate_from_by_to = {b: a for a, b in rotate_pairs.items()}
    targets: list[FinalTarget] = []
    n = len(final_ids)
    for iid in sorted(final_ids):
        pt = policy_by_id.get(iid)
        h = held_by_id.get(iid)
        gate_action = HOLD
        if iid in rotate_to:
            gate_action = ROTATE
        elif h is not None and iid in action_by_id:
            gate_action = action_by_id[iid]
        elif force := risk_forced.get(iid):
            gate_action = force
        elif pt is not None:
            gate_action = str(pt.action or HOLD)

        if iid in fixed_weights:
            weight = fixed_weights[iid]
        else:
            weight = free_w

        expected = None
        if pt is not None and pt.prediction_semantic == EXPECTED_RETURN:
            expected = pt.expected_return
        elif h is not None and h.prediction_semantic == EXPECTED_RETURN:
            expected = h.expected_return

        targets.append(
            FinalTarget(
                instrument_id=iid,
                ticker=ticker_by_id.get(iid, str(iid)),
                target_weight=weight,
                action=str(pt.action if pt is not None else gate_action),
                rank=(pt.rank if pt is not None else (h.rank if h else None)),
                predicted_return_20d=expected,
                policy=policy_name,
                gate_action=gate_action,
                rotate_from=rotate_from_by_to.get(iid),
                rotate_to=rotate_pairs.get(iid),
            )
        )

    meta = {
        "sell_gate": "V3",
        "retained": sorted(retained_ids),
        "exited": sorted(exit_ids),
        "rotations": {str(a): b for a, b in rotate_pairs.items()},
        "final_n": n,
        "fixed_weight_sum": fixed_sum,
        "free_weight": free_w,
        "exposure_cap": cap,
        "k_entry": k_entry,
        "sell_permissions": {str(p.instrument_id): p.to_dict() for p in permissions},
    }
    return SellGateResult(
        targets=tuple(targets),
        traces=tuple(traces),
        permissions=tuple(permissions),
        metadata=meta,
    )


@dataclass(frozen=True, slots=True)
class _ReviewedDecision:
    action: str
    replacement_id: int | None
    trace: CandidateDecisionTrace


def _evaluate_reviewed(
    h: HeldName,
    *,
    replacement_candidates: Sequence[ReplacementCandidate],
    exclude_ids: set[int],
    params: SellGateParams,
    fee_estimator: BrokerFeeEstimator,
    eligible_count: int | None,
) -> _ReviewedDecision:
    review = True

    if h.signal_stale:
        return _ReviewedDecision(
            action=DATA_HOLD,
            replacement_id=None,
            trace=_trace_held(
                h,
                action=DATA_HOLD,
                reason_codes=("REVIEW_TRIGGER", "STALE_SIGNAL"),
                limitation_codes=("STALE_SIGNAL",),
                eligible_count=eligible_count,
                review_trigger=review,
                candidate_target_weight=float(h.current_weight),
            ),
        )

    if str(h.prediction_semantic) != EXPECTED_RETURN or h.expected_return is None:
        return _ReviewedDecision(
            action=DATA_HOLD,
            replacement_id=None,
            trace=_trace_held(
                h,
                action=DATA_HOLD,
                reason_codes=("REVIEW_TRIGGER", "NON_COMPARABLE_PREDICTION"),
                limitation_codes=("NON_COMPARABLE_PREDICTION",),
                eligible_count=eligible_count,
                review_trigger=review,
                candidate_target_weight=float(h.current_weight),
            ),
        )

    if h.price is None or h.price <= 0 or h.quantity <= 0:
        return _ReviewedDecision(
            action=DATA_HOLD,
            replacement_id=None,
            trace=_trace_held(
                h,
                action=DATA_HOLD,
                reason_codes=("REVIEW_TRIGGER", "MISSING_PRICE_OR_QTY"),
                limitation_codes=("MISSING_PRICE",),
                eligible_count=eligible_count,
                review_trigger=review,
                candidate_target_weight=float(h.current_weight),
            ),
        )

    b = _best_replacement(
        replacement_candidates,
        exclude_ids=exclude_ids - {int(h.instrument_id)},
        k_entry=params.k_entry,
    )
    if b is None:
        return _ReviewedDecision(
            action=REVIEW_HOLD,
            replacement_id=None,
            trace=_trace_held(
                h,
                action=REVIEW_HOLD,
                reason_codes=("REVIEW_TRIGGER", "NO_COMPARABLE_REPLACEMENT"),
                limitation_codes=("NO_REPLACEMENT",),
                eligible_count=eligible_count,
                review_trigger=review,
                candidate_target_weight=float(h.current_weight),
            ),
        )

    if b.signal_stale or b.price is None or b.price <= 0:
        return _ReviewedDecision(
            action=DATA_HOLD,
            replacement_id=None,
            trace=_trace_held(
                h,
                action=DATA_HOLD,
                reason_codes=("REVIEW_TRIGGER", "REPLACEMENT_DATA_INCOMPLETE"),
                limitation_codes=("REPLACEMENT_DATA_INCOMPLETE",),
                eligible_count=eligible_count,
                review_trigger=review,
                replacement=b,
                candidate_target_weight=float(h.current_weight),
            ),
        )

    sell_notional = Decimal(str(h.quantity)) * Decimal(str(h.price))
    # Long-only rotation: redeploy sell notional into B (no capital creation / no short).
    buy_notional = sell_notional
    as_of = params.as_of or h.signal_as_of or date.today()

    sell_fee = fee_estimator.broker_fee_estimate(
        side="SELL",
        notional=sell_notional,
        instrument_id=int(h.instrument_id),
        as_of=as_of,
        fee_profile_id=params.fee_profile_id,
        fee_profile_code=params.fee_profile_code,
        instrument_symbol=h.ticker,
    )
    buy_fee = fee_estimator.broker_fee_estimate(
        side="BUY",
        notional=buy_notional,
        instrument_id=int(b.instrument_id),
        as_of=as_of,
        fee_profile_id=params.fee_profile_id,
        fee_profile_code=params.fee_profile_code,
        instrument_symbol=b.ticker,
    )
    if sell_fee is None or buy_fee is None:
        return _ReviewedDecision(
            action=DATA_HOLD,
            replacement_id=None,
            trace=_trace_held(
                h,
                action=DATA_HOLD,
                reason_codes=("REVIEW_TRIGGER", "FEE_MODEL_MISSING"),
                limitation_codes=("FEE_MODEL_MISSING",),
                eligible_count=eligible_count,
                review_trigger=review,
                replacement=b,
                candidate_target_weight=float(h.current_weight),
            ),
        )

    sell_frac, buy_frac, slip_frac, margin_frac = _edge_costs(
        sell_fee=sell_fee,
        buy_fee=buy_fee,
        sell_notional=sell_notional,
        buy_notional=buy_notional,
        slippage_bps=params.slippage_bps,
        min_net_rotation_edge_bps=params.min_net_rotation_edge_bps,
    )
    costs = sell_frac + buy_frac + slip_frac + margin_frac
    gross_edge = Decimal(str(b.expected_return)) - Decimal(str(h.expected_return))
    net_edge = gross_edge - costs

    if net_edge > 0:
        return _ReviewedDecision(
            action=ROTATE,
            replacement_id=int(b.instrument_id),
            trace=_trace_held(
                h,
                action=ROTATE,
                reason_codes=("REVIEW_TRIGGER", "NET_EDGE_POSITIVE", f"ROTATE_TO_{b.ticker}"),
                eligible_count=eligible_count,
                review_trigger=review,
                replacement=b,
                gross_expected_edge=float(gross_edge),
                sell_fee_estimate=float(sell_fee),
                buy_fee_estimate=float(buy_fee),
                slippage_estimate=float(slip_frac * sell_notional),
                net_edge=float(net_edge),
                min_net_rotation_edge_bps=params.min_net_rotation_edge_bps,
                candidate_target_weight=0.0,
            ),
        )

    return _ReviewedDecision(
        action=REVIEW_HOLD,
        replacement_id=None,
        trace=_trace_held(
            h,
            action=REVIEW_HOLD,
            reason_codes=("REVIEW_TRIGGER", "INSUFFICIENT_NET_EDGE"),
            limitation_codes=("INSUFFICIENT_NET_EDGE",),
            eligible_count=eligible_count,
            review_trigger=review,
            replacement=b,
            gross_expected_edge=float(gross_edge),
            sell_fee_estimate=float(sell_fee),
            buy_fee_estimate=float(buy_fee),
            slippage_estimate=float(slip_frac * sell_notional),
            net_edge=float(net_edge),
            min_net_rotation_edge_bps=params.min_net_rotation_edge_bps,
            candidate_target_weight=float(h.current_weight),
        ),
    )


def _trace_held(
    h: HeldName,
    *,
    action: str,
    reason_codes: tuple[str, ...] | list[str],
    eligible_count: int | None,
    limitation_codes: tuple[str, ...] | list[str] = (),
    review_trigger: bool | None = None,
    replacement: ReplacementCandidate | None = None,
    candidate_target_weight: float | None = None,
    gross_expected_edge: float | None = None,
    sell_fee_estimate: float | None = None,
    buy_fee_estimate: float | None = None,
    slippage_estimate: float | None = None,
    net_edge: float | None = None,
    min_net_rotation_edge_bps: float | None = None,
) -> CandidateDecisionTrace:
    return CandidateDecisionTrace(
        instrument_id=int(h.instrument_id),
        ticker=h.ticker,
        decision_action=action,
        reason_codes=tuple(reason_codes),
        limitation_codes=tuple(limitation_codes),
        signal_as_of=h.signal_as_of.isoformat() if h.signal_as_of else None,
        rank=h.rank,
        eligible_count=eligible_count,
        prediction_semantic=h.prediction_semantic,
        predicted_value=h.expected_return if h.prediction_semantic == EXPECTED_RETURN else None,
        held_before=True,
        quantity_before=float(h.quantity),
        current_weight=float(h.current_weight),
        avg_entry=h.avg_entry,
        current_mark=h.price,
        unrealized_pnl=h.unrealized_pnl,
        in_exit_band=h.in_exit_band,
        review_trigger=bool(review_trigger if review_trigger is not None else h.review_trigger),
        candidate_target_weight=candidate_target_weight,
        replacement_instrument_id=int(replacement.instrument_id) if replacement else None,
        replacement_ticker=replacement.ticker if replacement else None,
        gross_expected_edge=gross_expected_edge,
        sell_fee_estimate=sell_fee_estimate,
        buy_fee_estimate=buy_fee_estimate,
        slippage_estimate=slippage_estimate,
        net_edge=net_edge,
        min_net_rotation_edge_bps=min_net_rotation_edge_bps,
    )

