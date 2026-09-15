"""Portfolio Relations Visualization V1 — read-only aggregation of persisted Relations.

Does not recompute correlations. Does not change Candidate / Policy / Research universes.
"""

from __future__ import annotations

from itertools import combinations
from typing import Any
from uuid import UUID

from sqlalchemy import select, tuple_
from sqlalchemy.orm import Session

from app.infrastructure.analytics.relation_models import RelationSet, RelationSnapshot
from app.infrastructure.analytics.relation_repository import load_relation_inputs_by_codes
from app.modules.learning.application.relations_join import instrument_relation_input_code, ordered_pair
from app.modules.relations.relation_config import BASIC_RELATIONS_V1

# UX-only descriptive bands (not investment policy).
HIGH_POSITIVE = 0.70
MODERATE_POSITIVE = 0.40
WEAK_ABS = 0.40
NEGATIVE = -0.40

MAX_PORTFOLIO_SYMBOLS = 12
DEFAULT_WINDOW = 60


def build_portfolio_relations_matrix(
    session: Session,
    *,
    symbols: list[str],
    window: int = DEFAULT_WINDOW,
    relation_set_code: str = BASIC_RELATIONS_V1["code"],
    relation_set_version: int | None = None,
) -> dict[str, Any]:
    """Return pairwise Pearson matrix for Candidate symbols from persisted snapshots."""
    cleaned = _normalize_symbols(symbols)
    if not cleaned:
        return _empty_payload(window=window, reason="NO_SYMBOLS")
    if len(cleaned) > MAX_PORTFOLIO_SYMBOLS:
        return _empty_payload(
            window=window,
            reason="TOO_MANY_SYMBOLS",
            detail=f"Максимум {MAX_PORTFOLIO_SYMBOLS} инструментов для матрицы портфеля.",
            symbols=cleaned,
        )

    rel_set = _resolve_set(session, code=relation_set_code, version=relation_set_version)
    if rel_set is None:
        return _empty_payload(
            window=window,
            reason="RELATION_SET_NOT_FOUND",
            symbols=cleaned,
        )

    codes = [instrument_relation_input_code(sym) for sym in cleaned]
    inputs_by_code = load_relation_inputs_by_codes(session, codes)

    instruments: list[dict[str, Any]] = []
    id_by_symbol: dict[str, UUID] = {}
    for sym, code in zip(cleaned, codes, strict=True):
        row = inputs_by_code.get(code)
        if row is None or not row.is_active:
            instruments.append(
                {
                    "symbol": sym,
                    "status": "INPUT_MISSING",
                    "reason_ru": (
                        "Нет Relations-входа для дневной доходности. "
                        "Типично для облигаций / инструментов вне Relations universe."
                    ),
                    "input_id": None,
                    "input_code": code,
                    "display_name": None,
                }
            )
            continue
        id_by_symbol[sym] = row.id
        instruments.append(
            {
                "symbol": sym,
                "status": "READY",
                "reason_ru": None,
                "input_id": str(row.id),
                "input_code": row.code,
                "display_name": row.display_name,
            }
        )

    ready_symbols = [i["symbol"] for i in instruments if i["status"] == "READY"]
    pair_ids = [
        ordered_pair(id_by_symbol[a], id_by_symbol[b]) for a, b in combinations(ready_symbols, 2)
    ]
    latest = _load_latest_snapshots(
        session,
        relation_set_id=rel_set.id,
        relation_set_version=int(rel_set.version),
        pair_ids=pair_ids,
        window=window,
    )

    cells: list[dict[str, Any]] = []
    available = 0
    unavailable = 0
    valid_values: list[tuple[str, str, float]] = []

    # Diagonal
    for sym in cleaned:
        cells.append(
            {
                "symbol_a": sym,
                "symbol_b": sym,
                "pearson": 1.0 if sym in id_by_symbol else None,
                "spearman": 1.0 if sym in id_by_symbol else None,
                "status": "DIAGONAL" if sym in id_by_symbol else "INPUT_MISSING",
                "is_valid": sym in id_by_symbol,
                "sample_count": None,
                "coverage_ratio": None,
                "as_of_date": None,
                "reason_ru": None if sym in id_by_symbol else "Relations input отсутствует.",
            }
        )

    for a, b in combinations(cleaned, 2):
        if a not in id_by_symbol or b not in id_by_symbol:
            unavailable += 1
            missing = []
            if a not in id_by_symbol:
                missing.append(a)
            if b not in id_by_symbol:
                missing.append(b)
            cells.append(
                {
                    "symbol_a": a,
                    "symbol_b": b,
                    "pearson": None,
                    "spearman": None,
                    "status": "UNSUPPORTED_PAIR",
                    "is_valid": False,
                    "sample_count": None,
                    "coverage_ratio": None,
                    "as_of_date": None,
                    "reason_ru": (
                        "Корреляция недоступна: нет Relations-входа для "
                        + ", ".join(missing)
                        + "."
                    ),
                }
            )
            continue

        key = ordered_pair(id_by_symbol[a], id_by_symbol[b])
        snap = latest.get(key)
        if snap is None:
            unavailable += 1
            cells.append(
                {
                    "symbol_a": a,
                    "symbol_b": b,
                    "pearson": None,
                    "spearman": None,
                    "status": "SNAPSHOT_MISSING",
                    "is_valid": False,
                    "sample_count": None,
                    "coverage_ratio": None,
                    "as_of_date": None,
                    "reason_ru": (
                        "Снимок Relations для этой пары ещё не рассчитан "
                        f"(окно {window} торговых дней)."
                    ),
                }
            )
            continue

        pearson = float(snap.pearson) if snap.pearson is not None else None
        flags = snap.quality_flags or {}
        if not snap.is_valid or pearson is None:
            unavailable += 1
            reason = "Недостаточно пересечения истории доходностей."
            if flags.get("insufficient_samples"):
                reason = "Недостаточно наблюдений / coverage ниже порога Relations."
            elif flags.get("undefined_correlation"):
                reason = "Корреляция не определена (например, постоянный ряд)."
            cells.append(
                {
                    "symbol_a": a,
                    "symbol_b": b,
                    "pearson": None,
                    "spearman": float(snap.spearman) if snap.spearman is not None else None,
                    "status": "INSUFFICIENT_DATA",
                    "is_valid": False,
                    "sample_count": int(snap.sample_count),
                    "coverage_ratio": float(snap.coverage_ratio)
                    if snap.coverage_ratio is not None
                    else None,
                    "as_of_date": snap.as_of_date.isoformat(),
                    "reason_ru": reason,
                    "quality_flags": flags,
                }
            )
            continue

        available += 1
        valid_values.append((a, b, pearson))
        cells.append(
            {
                "symbol_a": a,
                "symbol_b": b,
                "pearson": pearson,
                "spearman": float(snap.spearman) if snap.spearman is not None else None,
                "status": "OK",
                "is_valid": True,
                "sample_count": int(snap.sample_count),
                "coverage_ratio": float(snap.coverage_ratio)
                if snap.coverage_ratio is not None
                else None,
                "as_of_date": snap.as_of_date.isoformat(),
                "reason_ru": None,
                "band": _band(pearson),
            }
        )

    summary = _build_summary(valid_values, available=available, unavailable=unavailable)
    as_of_dates = sorted(
        {c["as_of_date"] for c in cells if c.get("as_of_date")},
        reverse=True,
    )

    return {
        "version": "PORTFOLIO_RELATIONS_VISUALIZATION_V1",
        "metric": {
            "name": "pearson",
            "label_ru": "Корреляция доходностей (Pearson)",
            "return_feature": "log_return_1d",
            "return_label_ru": "дневные лог-доходности",
            "window_observations": window,
            "window_label_ru": f"окно {window} торговых дней",
            "methods": ["pearson", "spearman"],
            "minimum_coverage_ratio": 0.8,
            "note_ru": (
                "Чем ближе значение к +1, тем чаще активы двигались в одном направлении. "
                "Около 0 — слабая историческая связь. Отрицательные значения — чаще в разные стороны. "
                "Историческая корреляция может меняться и не гарантирует будущего поведения. "
                "Корреляция ≠ причинная зависимость."
            ),
        },
        "relation_set": {
            "code": rel_set.code,
            "version": int(rel_set.version),
            "id": str(rel_set.id),
        },
        "symbols": cleaned,
        "instruments": instruments,
        "cells": cells,
        "summary": summary,
        "as_of_date": as_of_dates[0] if as_of_dates else None,
        "bands_ux_only": {
            "high_positive": HIGH_POSITIVE,
            "moderate_positive": MODERATE_POSITIVE,
            "weak_abs": WEAK_ABS,
            "negative": NEGATIVE,
            "note_ru": (
                "Пороги только для описания heatmap, не являются правилами Candidate Policy."
            ),
        },
        "limitations_ru": [
            "Только read-only поверх уже посчитанных Relations snapshots.",
            "Отдельные облигации часто отсутствуют в Relations universe — клетки N/A.",
            "Не используется для автоматической ребалансировки или нового score диверсификации.",
        ],
    }


def _normalize_symbols(symbols: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in symbols:
        sym = str(raw or "").strip().upper()
        if not sym or sym in seen:
            continue
        if sym in {"CASH", "EQUITY_SLEEVE", "FI_SLEEVE"}:
            continue
        seen.add(sym)
        out.append(sym)
    return out


def _resolve_set(
    session: Session, *, code: str, version: int | None
) -> RelationSet | None:
    if version is not None:
        return session.scalar(
            select(RelationSet).where(RelationSet.code == code, RelationSet.version == version)
        )
    return session.scalar(
        select(RelationSet)
        .where(RelationSet.code == code, RelationSet.is_active.is_(True))
        .order_by(RelationSet.version.desc())
    )


def _load_latest_snapshots(
    session: Session,
    *,
    relation_set_id: UUID,
    relation_set_version: int,
    pair_ids: list[tuple[UUID, UUID]],
    window: int,
) -> dict[tuple[UUID, UUID], RelationSnapshot]:
    if not pair_ids:
        return {}
    unique = list({(a, b) for a, b in pair_ids})
    # Latest as_of per unordered pair for the window.
    # Load candidates then keep max as_of in Python (bounded: C(12,2)=66).
    out: dict[tuple[UUID, UUID], RelationSnapshot] = {}
    chunk = 80
    for offset in range(0, len(unique), chunk):
        part = unique[offset : offset + chunk]
        rows = list(
            session.scalars(
                select(RelationSnapshot).where(
                    RelationSnapshot.relation_set_id == relation_set_id,
                    RelationSnapshot.relation_set_version == relation_set_version,
                    RelationSnapshot.window_observations == window,
                    tuple_(RelationSnapshot.input_a_id, RelationSnapshot.input_b_id).in_(part),
                )
            )
        )
        for row in rows:
            key = ordered_pair(row.input_a_id, row.input_b_id)
            prev = out.get(key)
            if prev is None or row.as_of_date > prev.as_of_date:
                out[key] = row
    return out


def _band(pearson: float) -> str:
    if pearson >= HIGH_POSITIVE:
        return "HIGH_POSITIVE"
    if pearson >= MODERATE_POSITIVE:
        return "MODERATE_POSITIVE"
    if pearson <= NEGATIVE:
        return "NEGATIVE"
    if abs(pearson) < WEAK_ABS:
        return "WEAK"
    return "MODERATE_NEGATIVE"


def _build_summary(
    valid_values: list[tuple[str, str, float]],
    *,
    available: int,
    unavailable: int,
) -> dict[str, Any]:
    if not valid_values:
        return {
            "pair_count": available + unavailable,
            "available_pair_count": 0,
            "unavailable_pair_count": unavailable,
            "strongest_positive": None,
            "lowest": None,
            "average_abs_correlation": None,
            "high_positive_pair_count": 0,
            "status": "EMPTY",
            "status_ru": "Нет доступных pairwise корреляций для текущего состава.",
        }
    strongest = max(valid_values, key=lambda x: x[2])
    lowest = min(valid_values, key=lambda x: x[2])
    avg_abs = sum(abs(v) for _, _, v in valid_values) / len(valid_values)
    high_n = sum(1 for _, _, v in valid_values if v >= HIGH_POSITIVE)
    return {
        "pair_count": available + unavailable,
        "available_pair_count": available,
        "unavailable_pair_count": unavailable,
        "strongest_positive": {
            "symbol_a": strongest[0],
            "symbol_b": strongest[1],
            "pearson": strongest[2],
        },
        "lowest": {
            "symbol_a": lowest[0],
            "symbol_b": lowest[1],
            "pearson": lowest[2],
        },
        "average_abs_correlation": avg_abs,
        "high_positive_pair_count": high_n,
        "status": "OK",
        "status_ru": (
            f"Доступно {available} из {available + unavailable} пар. "
            f"Сильных положительных (≥{HIGH_POSITIVE:.2f}): {high_n}."
        ),
    }


def _empty_payload(
    *,
    window: int,
    reason: str,
    detail: str | None = None,
    symbols: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "version": "PORTFOLIO_RELATIONS_VISUALIZATION_V1",
        "metric": {
            "name": "pearson",
            "label_ru": "Корреляция доходностей (Pearson)",
            "return_feature": "log_return_1d",
            "window_observations": window,
            "window_label_ru": f"окно {window} торговых дней",
        },
        "symbols": symbols or [],
        "instruments": [],
        "cells": [],
        "summary": {
            "pair_count": 0,
            "available_pair_count": 0,
            "unavailable_pair_count": 0,
            "status": reason,
            "status_ru": detail or reason,
        },
        "as_of_date": None,
        "error": {"code": reason, "message_ru": detail or reason},
    }
