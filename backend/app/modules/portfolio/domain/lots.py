"""Manual portfolio lot validation."""

from __future__ import annotations

from decimal import Decimal


class LotValidationError(ValueError):
    def __init__(self, message: str, *, code: str = "LOT_MISMATCH") -> None:
        super().__init__(message)
        self.code = code


def assert_lot_compatible(
    units: Decimal,
    lot_size: int | None,
    *,
    non_standard_lot: bool = False,
) -> None:
    if non_standard_lot:
        return
    if lot_size is None or lot_size <= 0:
        raise LotValidationError(
            "LOTSIZE unknown; set non_standard_lot=true to override",
            code="UNKNOWN_LOTSIZE",
        )
    units_int = int(units)
    if Decimal(units_int) != units:
        raise LotValidationError("units must be integer for lot validation", code="NON_INTEGER_UNITS")
    if units_int % int(lot_size) != 0:
        raise LotValidationError(
            f"units {units_int} not divisible by lot_size {lot_size}",
            code="LOT_MISMATCH",
        )
